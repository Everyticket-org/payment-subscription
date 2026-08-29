"""
Everyticket SSO (spec section 47).

Everyticket generates a short-lived, HMAC-signed token (customer_id,
external_customer_id, user_identifier, issued_at, expires_at, nonce) when
its admin clicks "Manage Subscription"; this app validates the signature
and expiry, and - critically - the nonce against a DB row so the exact
same token can never be redeemed twice. Replay protection is NOT just the
JWT's own exp claim: a token intercepted before it expires could
otherwise be replayed any number of times within that window. The
SsoSession row (already modeled in app.auth.models) is the actual guard -
`used` flips to True on first redemption and every later attempt with the
same nonce is refused, independent of whether the JWT itself would still
verify.

Signing uses a secret distinct from this app's own internal JWT_SECRET
(app.core.security): `application.sso_secret` if the admin has configured
a per-application override, else settings.SSO_SECRET - because in a real
deployment Everyticket and this app share that secret out-of-band, and
this app's internal JWT_SECRET (used for admin/customer session tokens)
is never handed to Everyticket.

Everyticket itself doesn't exist in this build, so `create_sso_token()`
below - which in production only Everyticket would ever call - is also
exposed through a TEST_MODE-gated admin action (see
app/api/v1/admin_customers.py's `/sso-link` endpoint) purely so this flow
is exercisable end-to-end without a real Everyticket instance, mirroring
how OTP verification has a TEST_MODE `debug_otp_code` convenience for the
same reason. That test endpoint is never available outside TEST_MODE
(itself force-disabled in production by Settings.enforce_test_mode_restrictions).
"""
import secrets
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.applications.models import Application
from app.auth.models import SsoSession
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.ids import new_sso_session_id
from app.core.time import ensure_aware
from app.customers.models import Customer

_ALGORITHM = "HS256"


class SsoTokenInvalid(AppError):
    http_status = 401
    error_code = "SSO_TOKEN_INVALID"


class SsoTokenExpired(AppError):
    http_status = 401
    error_code = "SSO_TOKEN_EXPIRED"


class SsoTokenAlreadyUsed(AppError):
    http_status = 401
    error_code = "SSO_TOKEN_ALREADY_USED"


def _resolve_secret(application: Application) -> str:
    settings = get_settings()
    return application.sso_secret or settings.SSO_SECRET


def create_sso_token(
    db: Session, *, application: Application, customer: Customer, user_identifier: str | None = None
) -> str:
    """Creates the signed token AND its DB-backed SsoSession row in one
    step - the row, not the JWT's own exp claim, is what makes replay
    protection real. Caller commits."""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=settings.SSO_TOKEN_TTL_SECONDS)
    nonce = secrets.token_urlsafe(24)

    mapping = next((m for m in customer.application_mappings if m.application_id == application.id), None)
    external_customer_id = mapping.external_customer_id if mapping else None

    session = SsoSession(
        sso_session_id=new_sso_session_id(),
        customer_id=customer.customer_id,
        external_customer_id=external_customer_id,
        user_identifier=user_identifier,
        nonce=nonce,
        issued_at=now,
        expires_at=expires_at,
        used=False,
    )
    db.add(session)
    db.flush()

    payload = {
        "sub": customer.customer_id,
        "external_customer_id": external_customer_id,
        "user_identifier": user_identifier,
        "iat": now,
        "exp": expires_at,
        "nonce": nonce,
        "type": "sso",
    }
    return jwt.encode(payload, _resolve_secret(application), algorithm=_ALGORITHM)


def redeem_sso_token(db: Session, *, application: Application, token: str) -> Customer:
    """Validates signature + expiry (JWT-level) AND the nonce against its
    DB row (app-level - the actual replay guard). Marks the session used
    and returns the Customer row; caller issues the real portal session
    token and commits."""
    try:
        payload = jwt.decode(token, _resolve_secret(application), algorithms=[_ALGORITHM])
    except JWTError:
        raise SsoTokenInvalid("SSO token is invalid, malformed, or signed with the wrong secret")

    if payload.get("type") != "sso":
        raise SsoTokenInvalid("Not an SSO token")

    nonce = payload.get("nonce")
    session = db.query(SsoSession).filter(SsoSession.nonce == nonce).first()
    if session is None:
        raise SsoTokenInvalid("Unknown SSO token")
    if session.used:
        raise SsoTokenAlreadyUsed("This SSO link has already been used")

    now = datetime.now(timezone.utc)
    if ensure_aware(session.expires_at) < now:
        raise SsoTokenExpired("This SSO link has expired")

    session.used = True
    db.add(session)
    db.flush()

    customer = db.query(Customer).filter(Customer.customer_id == session.customer_id).first()
    if customer is None:
        raise SsoTokenInvalid("Customer for this SSO token no longer exists")
    return customer
