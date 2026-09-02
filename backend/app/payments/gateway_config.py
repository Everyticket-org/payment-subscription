"""Admin-configurable, per-mode payment gateway credentials (2026-09
admin config restructure): "Payment Gateway" admin screen lets an admin
pick a gateway (dropdown) and, for gateways that need them, fill in
separate Test and Live credential sets - which one is actually used for
a real payment is decided by Application.gateway_mode ("Live/Test Mode",
now surfaced on the Application screen, not this one).

Stored via the existing generic system_settings key/value store
(app.core.settings_service - same pattern already used for the invoice
tax config and OTP security config) under one key, keyed by gateway code
then mode, rather than a new column per gateway/mode/field - this stays
extensible if a second gateway needing credentials is added later without
another migration.

Falls back to the env-configured PAYU_MERCHANT_KEY/SALT when nothing is
stored for that mode yet, matching this codebase's existing DB-row-
overrides-env-fallback pattern (webhook_secret, sso_secret).
"""
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.settings_service import get_setting, set_setting

_SETTINGS_KEY = "payment_gateway_credentials"


def _stored(db: Session) -> dict:
    return get_setting(db, key=_SETTINGS_KEY) or {}


def get_payu_credentials_status(db: Session) -> dict:
    """Returns {"test": {"merchant_key_is_set": bool, "merchant_salt_is_set": bool}, "live": {...}}
    - never the raw secret values (masked, same convention as every other
    secret in this app - see Application model's own docstring)."""
    stored = _stored(db).get("payu") or {}
    settings = get_settings()
    result = {}
    for mode in ("test", "live"):
        mode_cfg = stored.get(mode) or {}
        env_fallback_key = settings.PAYU_MERCHANT_KEY if mode == "test" else ""
        env_fallback_salt = settings.PAYU_MERCHANT_SALT if mode == "test" else ""
        result[mode] = {
            "merchant_key_is_set": bool(mode_cfg.get("merchant_key") or env_fallback_key),
            "merchant_salt_is_set": bool(mode_cfg.get("merchant_salt") or env_fallback_salt),
        }
    return result


def set_payu_credentials(db: Session, *, mode: str, merchant_key: str | None, merchant_salt: str | None) -> None:
    """None = leave the currently-stored value for that field unchanged;
    "" explicitly clears it - same convention as every other secret
    PUT endpoint in this app (see admin_config.py)."""
    stored = _stored(db)
    payu_cfg = stored.setdefault("payu", {})
    mode_cfg = payu_cfg.setdefault(mode, {})
    if merchant_key is not None:
        mode_cfg["merchant_key"] = merchant_key or None
    if merchant_salt is not None:
        mode_cfg["merchant_salt"] = merchant_salt or None
    set_setting(db, key=_SETTINGS_KEY, value=stored, description="Per-gateway, per-mode payment credentials (admin-configured)")


def resolve_payu_credentials(db: Session, *, mode: str) -> dict:
    """DB-configured PayU credentials for `mode` ('test'|'live'), falling
    back to the env vars (test mode only - there is no separate LIVE env
    var in this codebase's Settings, so a live-mode admin MUST configure
    live credentials here rather than via .env)."""
    stored = _stored(db).get("payu") or {}
    mode_cfg = stored.get(mode) or {}
    settings = get_settings()
    if mode == "test":
        merchant_key = mode_cfg.get("merchant_key") or settings.PAYU_MERCHANT_KEY
        merchant_salt = mode_cfg.get("merchant_salt") or settings.PAYU_MERCHANT_SALT
        base_url = settings.PAYU_BASE_URL or "https://test.payu.in"
    else:
        merchant_key = mode_cfg.get("merchant_key") or ""
        merchant_salt = mode_cfg.get("merchant_salt") or ""
        base_url = "https://secure.payu.in"
    return {"merchant_key": merchant_key, "merchant_salt": merchant_salt, "base_url": base_url}
