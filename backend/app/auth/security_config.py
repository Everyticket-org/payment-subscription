"""Admin-configurable OTP security parameters (spec sections 11, 51, 81's
"Security Configuration" screen). Backed by the same SystemSetting-based
pattern as app/invoices/tax.py, so an admin can retune OTP length/expiry/
attempt limits/resend cooldown at runtime without a redeploy.

Deliberately does NOT cover JWT token expiry or the OTP/MFA bypass
switches: JWT expiry changes affect every issued token's validation
behavior across the whole app (a much larger blast radius than OTP
timing), and the bypass switches are safety-critical, already
env-enforced (Settings.enforce_test_mode_restrictions), and already have
a dedicated runtime toggle (admin_testing.py's OTP/MFA bypass endpoints).
This module's GET response surfaces those bypass flags read-only for
visibility, so an admin has one place to see the full current security
posture, without creating a second, differently-persisted way to change
them.
"""
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.settings_service import get_setting, set_setting

_SETTING_KEY = "otp_security_config"


class SecurityConfigOut(BaseModel):
    otp_length: int
    otp_expiry_seconds: int
    otp_max_attempts: int
    otp_resend_cooldown_seconds: int
    # Read-only visibility into the safety switches (see module docstring)
    # - never set through this screen.
    allow_otp_bypass: bool
    allow_admin_mfa_bypass: bool
    test_mode: bool


class SecurityConfigUpdate(BaseModel):
    otp_length: int = Field(ge=4, le=10)
    otp_expiry_seconds: int = Field(ge=30, le=3600)
    otp_max_attempts: int = Field(ge=1, le=20)
    otp_resend_cooldown_seconds: int = Field(ge=0, le=3600)


def get_security_config(db: Session) -> SecurityConfigOut:
    settings = get_settings()
    value = get_setting(db, key=_SETTING_KEY)
    if value is None:
        otp_length = settings.OTP_LENGTH
        otp_expiry_seconds = settings.OTP_EXPIRY_SECONDS
        otp_max_attempts = settings.OTP_MAX_ATTEMPTS
        otp_resend_cooldown_seconds = settings.OTP_RESEND_COOLDOWN_SECONDS
    else:
        otp_length = value["otp_length"]
        otp_expiry_seconds = value["otp_expiry_seconds"]
        otp_max_attempts = value["otp_max_attempts"]
        otp_resend_cooldown_seconds = value["otp_resend_cooldown_seconds"]

    return SecurityConfigOut(
        otp_length=otp_length,
        otp_expiry_seconds=otp_expiry_seconds,
        otp_max_attempts=otp_max_attempts,
        otp_resend_cooldown_seconds=otp_resend_cooldown_seconds,
        allow_otp_bypass=settings.ALLOW_OTP_BYPASS,
        allow_admin_mfa_bypass=settings.ALLOW_ADMIN_MFA_BYPASS,
        test_mode=settings.TEST_MODE,
    )


def set_security_config(db: Session, *, update: SecurityConfigUpdate) -> SecurityConfigOut:
    set_setting(
        db,
        key=_SETTING_KEY,
        value=update.model_dump(),
        description="Admin-tunable OTP length/expiry/attempt-limit/resend-cooldown (spec section 11).",
    )
    db.commit()
    return get_security_config(db)
