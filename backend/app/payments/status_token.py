"""
Short-lived signed token that lets the frontend's /payment/return page read
one payment's status without the customer being signed in (most first-time
subscribers are guests).

The backend adds it to the redirect it sends after PayU's surl/furl
callback (app.api.v1.payment._handle_payu_return), and the status endpoint
only answers for the transaction the token names. Knowing a transaction ID
alone is not enough to read its status.

Signed with a key derived from JWT_SECRET plus a fixed purpose label, so
it can never be used as (or confused with) a customer/admin access token,
which are signed with JWT_SECRET itself.
"""
import hashlib
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.core.config import get_settings

_PURPOSE = "payment-status"
_ALGORITHM = "HS256"


def _signing_key() -> str:
    secret = get_settings().JWT_SECRET
    return hashlib.sha256(f"{_PURPOSE}:{secret}".encode("utf-8")).hexdigest()


def create_status_token(transaction_id: str, *, now: datetime | None = None) -> str:
    issued = now or datetime.now(timezone.utc)
    ttl = timedelta(minutes=get_settings().PAYMENT_STATUS_TOKEN_TTL_MINUTES)
    claims = {"sub": transaction_id, "purpose": _PURPOSE, "iat": issued, "exp": issued + ttl}
    return jwt.encode(claims, _signing_key(), algorithm=_ALGORITHM)


def token_matches(token: str | None, transaction_id: str) -> bool:
    """True only for an unexpired token issued for exactly this transaction."""
    if not token:
        return False
    try:
        claims = jwt.decode(token, _signing_key(), algorithms=[_ALGORITHM])
    except JWTError:
        return False
    return claims.get("purpose") == _PURPOSE and claims.get("sub") == transaction_id
