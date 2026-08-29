"""
Customer OTP (spec section 11).

OTP codes are never stored in plaintext (hashed the same way passwords
are, via passlib/bcrypt). Bypass ("BYPASS" as the submitted code) is only
honored when settings.ALLOW_OTP_BYPASS is true AND the environment is not
production - both checked here at the point of use, not just trusted from
config, mirroring app.auth.service's MFA bypass. Every bypass is
audit-logged.

LIMITATION: there is no real SMS/email delivery channel yet (see
docs/implementation-status.md), so the plaintext code is only ever
returned directly in the API response, and only when settings.TEST_MODE
is true (which itself can never be true in production - see
Settings.enforce_test_mode_restrictions). This is a deliberate stand-in
for "the code was sent to the user's phone/email" until a real
notification channel exists - it is not a production-safe delivery
mechanism.

OTP_LENGTH/OTP_EXPIRY_SECONDS/OTP_MAX_ATTEMPTS/OTP_RESEND_COOLDOWN_SECONDS
are admin-tunable at runtime via app.auth.security_config (spec
section 51's Security Configuration screen) - env/Settings values are
only the default until an admin saves an override.
"""
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.audit import service as audit_service
from app.auth.models import OtpSession
from app.auth.security_config import get_security_config
from app.core.config import get_settings
from app.core.exceptions import OtpInvalidOrExpired, OtpRateLimited
from app.core.ids import new_otp_session_id
from app.core.security import hash_password, verify_password
from app.core.time import ensure_aware

settings = get_settings()
_BYPASS_CODE = "BYPASS"


def _generate_code(length: int) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(length))


def assert_resend_allowed(db: Session, *, email: str | None, mobile: str | None, purpose: str) -> None:
    """
    OTP resend rate limiting (spec section 11). Looks up the most
    recently created OtpSession matching this exact email+mobile+purpose
    and, if one was created within OTP_RESEND_COOLDOWN_SECONDS, raises
    OtpRateLimited rather than letting the caller issue (and email/SMS)
    yet another code. Matches on BOTH email and mobile (not either alone)
    so this can never rate-limit an unrelated customer who happens to
    share just one of the two fields.
    """
    last_session = (
        db.query(OtpSession)
        .filter(OtpSession.email == email, OtpSession.mobile == mobile, OtpSession.purpose == purpose)
        .order_by(OtpSession.created_at.desc())
        .first()
    )
    if last_session is None:
        return

    now = datetime.now(timezone.utc)
    elapsed = (now - ensure_aware(last_session.created_at)).total_seconds()
    cooldown = get_security_config(db).otp_resend_cooldown_seconds
    if elapsed < cooldown:
        wait_seconds = int(cooldown - elapsed) + 1
        raise OtpRateLimited(f"Please wait {wait_seconds} more second(s) before requesting another OTP code")


def create_otp_session(
    db: Session, *, email: str | None, mobile: str | None, customer_id: str | None, purpose: str
) -> tuple[OtpSession, str]:
    """Returns (session, plaintext_code). Caller decides whether/how to
    surface the plaintext code (see module docstring - only in
    TEST_MODE)."""
    security_config = get_security_config(db)
    code = _generate_code(security_config.otp_length)
    now = datetime.now(timezone.utc)

    session = OtpSession(
        otp_session_id=new_otp_session_id(),
        email=email,
        mobile=mobile,
        customer_id=customer_id,
        purpose=purpose,
        otp_hash=hash_password(code),
        expires_at=now + timedelta(seconds=security_config.otp_expiry_seconds),
        max_attempts=security_config.otp_max_attempts,
    )
    db.add(session)
    db.flush()
    return session, code


def get_session(db: Session, *, otp_session_id: str) -> OtpSession:
    session = db.query(OtpSession).filter(OtpSession.otp_session_id == otp_session_id).first()
    if session is None:
        raise OtpInvalidOrExpired("Unknown OTP session")
    return session


def verify_otp(db: Session, *, otp_session_id: str, code: str, ip_address: str | None = None) -> OtpSession:
    session = get_session(db, otp_session_id=otp_session_id)

    if session.verified:
        return session  # already verified - idempotent re-check (e.g. page refresh)

    if session.attempt_count >= session.max_attempts:
        raise OtpRateLimited("Maximum verification attempts exceeded for this OTP session")

    now = datetime.now(timezone.utc)
    if now > ensure_aware(session.expires_at):
        raise OtpInvalidOrExpired("OTP has expired")

    if code == _BYPASS_CODE:
        if not settings.ALLOW_OTP_BYPASS or settings.is_production:
            raise OtpInvalidOrExpired("OTP bypass is not permitted in this environment")
        session.verified = True
        session.bypassed = True
        session.bypassed_by = "system"
        db.add(session)
        audit_service.record(
            db,
            actor="system",
            action="OTP_BYPASSED",
            entity_type="otp_session",
            entity_id=session.otp_session_id,
            ip_address=ip_address,
        )
        db.flush()
        return session

    session.attempt_count += 1
    db.add(session)

    if not verify_password(code, session.otp_hash):
        db.flush()
        if session.attempt_count >= session.max_attempts:
            raise OtpRateLimited("Maximum verification attempts exceeded for this OTP session")
        raise OtpInvalidOrExpired("Incorrect OTP code")

    session.verified = True
    db.add(session)
    db.flush()
    return session
