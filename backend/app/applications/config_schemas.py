"""Pydantic schemas for the Application configuration admin screens (spec
sections 13, 51, 81): "Payment Gateway Configuration", "Everyticket
Integration Configuration", "Notification Configuration", and "System
Configuration" all read/write different field groups of the same single
V1 Application row (there is exactly one - EVERYTICKET). "Security
Configuration" is separate (app/auth/security_config.py) since its
fields live on Settings/system_settings, not Application.

Secret-bearing fields (webhook_secret, sso_secret, api_credentials) are
never echoed back in plaintext on GET - only an `*_is_set` boolean, per
this app's existing convention (see Application's own model docstring).
PUT still accepts the real value to set/rotate it; omitting a secret
field on PUT leaves the stored value unchanged (see admin_config.py).
"""
from pydantic import BaseModel, ConfigDict


class ApplicationGeneralOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    name: str
    application_url: str
    logo_url: str | None = None
    favicon_url: str | None = None
    support_email: str | None = None
    support_phone: str | None = None
    timezone: str
    currency: str
    active: bool


class ApplicationGeneralUpdate(BaseModel):
    name: str
    application_url: str
    logo_url: str | None = None
    favicon_url: str | None = None
    support_email: str | None = None
    support_phone: str | None = None
    timezone: str = "Asia/Kolkata"
    currency: str = "INR"
    active: bool = True


class ApplicationIntegrationOut(BaseModel):
    api_url: str | None = None
    api_credentials_is_set: bool
    webhook_url: str | None = None
    webhook_secret_is_set: bool
    sso_secret_is_set: bool


class ApplicationIntegrationUpdate(BaseModel):
    api_url: str | None = None
    api_credentials: dict | None = None
    webhook_url: str | None = None
    # None = leave the currently-stored secret unchanged; "" would clear it.
    webhook_secret: str | None = None
    sso_secret: str | None = None


class ApplicationPaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    default_gateway: str
    gateway_mode: str


class ApplicationPaymentUpdate(BaseModel):
    default_gateway: str
    gateway_mode: str = "test"


class ApplicationNotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    email_provider: str
    email_sender_name: str | None = None
    email_sender_address: str | None = None
    email_reply_to: str | None = None


class ApplicationNotificationUpdate(BaseModel):
    email_provider: str = "smtp"
    email_sender_name: str | None = None
    email_sender_address: str | None = None
    email_reply_to: str | None = None


class ApplicationSubscriptionRulesOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    allow_upgrade: bool
    allow_downgrade: bool
    allow_cancellation: bool
    cancellation_behavior: str
    renewal_enabled: bool
    repurchase_enabled: bool


class ApplicationSubscriptionRulesUpdate(BaseModel):
    allow_upgrade: bool = True
    allow_downgrade: bool = True
    allow_cancellation: bool = True
    cancellation_behavior: str = "IMMEDIATE"
    renewal_enabled: bool = True
    repurchase_enabled: bool = True


class ApplicationConfigOut(BaseModel):
    """The full config surface in one response, for a single overview
    read - PUTs are still split per screen/group (see admin_config.py)."""
    general: ApplicationGeneralOut
    integration: ApplicationIntegrationOut
    payment: ApplicationPaymentOut
    notification: ApplicationNotificationOut
    subscription_rules: ApplicationSubscriptionRulesOut
