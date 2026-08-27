"""
Admin authentication service (spec section 12).

Two-step login: password -> pre_mfa_token (short-lived, type=pre_mfa) ->
MFA code -> full access/refresh token pair. MFA can be bypassed with the
literal code "BYPASS" ONLY when settings.ALLOW_ADMIN_MFA_BYPASS is true
AND the environment is not production (both are checked here, not just
trusted from config - see Settings.enforce_test_mode_restrictions, which
already zeroes these flags in production, but this is a second,
independent check at the point of use per spec section 55: "backend must
enforce, not just hide"). Every bypass is audit-logged.
"""
from datetime import datetime, timedelta, timezone

import pyotp
from jose import JWTError
from sqlalchemy.orm import Session

from app.audit import service as audit_service
from app.auth.models import AdminUser
from app.core.config import get_settings
from app.core.exceptions import Forbidden, Unauthorized
from app.core.security import create_access_token, decode_token, hash_password, verify_password

settings = get_settings()

_PRE_MFA_TOKEN_TTL_MINUTES = 5
_MFA_BYPASS_CODE = "BYPASS"


def authenticate_password(db: Session, *, email: str, password: str) -> AdminUser:
    user = db.query(AdminUser).filter(AdminUser.email == email).first()
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        raise Unauthorized("Invalid email or password")
    return user


def create_pre_mfa_token(user: AdminUser) -> str:
    now = datetime.now(timezone.utc)
    from jose import jwt  # local import to keep module-level surface small

    payload = {
        "sub": user.email,
        "iat": now,
        "exp": now + timedelta(minutes=_PRE_MFA_TOKEN_TTL_MINUTES),
        "type": "pre_mfa",
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def resolve_pre_mfa_token(db: Session, *, pre_mfa_token: str) -> AdminUser:
    try:
        payload = decode_token(pre_mfa_token)
    except JWTError:
        raise Unauthorized("Invalid or expired pre-MFA token")
    if payload.get("type") != "pre_mfa":
        raise Unauthorized("Invalid token type")
    user = db.query(AdminUser).filter(AdminUser.email == payload.get("sub")).first()
    if user is None or not user.is_active:
        raise Unauthorized("Invalid or expired pre-MFA token")
    return user


def verify_mfa_code(db: Session, *, user: AdminUser, code: str, ip_address: str | None = None) -> None:
    """Raises Unauthorized/Forbidden on failure. Returns None on success."""
    if code == _MFA_BYPASS_CODE:
        if not settings.ALLOW_ADMIN_MFA_BYPASS or settings.is_production:
            raise Forbidden("MFA bypass is not permitted in this environment")
        audit_service.record(
            db,
            actor=user.email,
            action="MFA_BYPASSED",
            entity_type="admin_user",
            entity_id=user.email,
            ip_address=ip_address,
        )
        db.commit()
        return

    if not user.mfa_secret:
        raise Unauthorized("MFA is not configured for this account")

    totp = pyotp.TOTP(user.mfa_secret)
    if not totp.verify(code, valid_window=1):
        raise Unauthorized("Invalid MFA code")


def issue_tokens(user: AdminUser) -> tuple[str, str]:
    claims = {"token_kind": "admin"}
    access_token = create_access_token(user.email, extra_claims=claims)
    from app.core.security import create_refresh_token

    refresh_token = create_refresh_token(user.email)
    return access_token, refresh_token


def new_totp_secret() -> str:
    return pyotp.random_base32()


def create_admin_user(
    db: Session, *, email: str, full_name: str, password: str, mfa_enabled: bool = True
) -> AdminUser:
    user = AdminUser(
        email=email,
        full_name=full_name,
        password_hash=hash_password(password),
        mfa_enabled=mfa_enabled,
        mfa_secret=new_totp_secret() if mfa_enabled else None,
    )
    db.add(user)
    db.flush()
    return user
