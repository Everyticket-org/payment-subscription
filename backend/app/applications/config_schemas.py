"""Pydantic schemas for the Application configuration admin screens.

Restructured 2026-09 (Vishal's explicit 4-section layout) into:
  1. Application - name, currency, Live/Test Mode (gateway_mode) only.
     Every other General field (application_url, logo/favicon, support
     contact, timezone, active) stays on the Application model/DB row
     unchanged - just no longer admin-editable from this screen.
  2. Payment Gateway - a gateway dropdown (default_gateway) plus, for a
     gateway that needs them (PayU today), separate Test and Live
     credential sets - which one is actually used is decided by section
     1's Live/Test Mode, not a per-credential toggle here. Credentials
     are stored via app.payments.gateway_config (system_settings), not a
     column on this model - GET only reports masked *_is_set booleans.
  3. Everyticket Integration - the webhook secret ("Secret Key"),
     destination URL, custom key/value POST parameters sent with every
     delivery, an admin-configurable retry limit, and an escalation
     email (recipients + admin-edited subject/body) sent once a delivery
     is EXHAUSTED. `api_url`/`api_credentials`/`sso_secret` (SSO is a
     separate concern from webhook delivery) are deliberately not on
     this screen any more - their columns/behavior are unchanged, just
     not exposed here (SSO already has its own env fallback).
  4. Notifications - real SMTP transport (host/port/username/password/
     use_tls, previously env-only) plus the pre-existing sender name/
     address/reply-to overrides.

"Subscription rules" and "Security" configuration are unchanged (see
ApplicationSubscriptionRulesOut/Update below and app/auth/security_config.py)
and their enforcement is untouched - they're just not rendered on the
restructured admin Configuration page for now.

Secret-bearing fields (webhook_secret, smtp_password, gateway
credentials) are never echoed back in plaintext on GET - only an
`*_is_set` boolean, per this app's existing convention (see
Application's own model docstring). PUT still accepts the real value to
set/rotate it; None on PUT leaves the stored value unchanged, "" clears
it (see admin_config.py).
"""
from pydantic import BaseModel, ConfigDict


class ApplicationGeneralOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    name: str
    currency: str
    gateway_mode: str  # test | live - "Live/Test Mode"


class ApplicationGeneralUpdate(BaseModel):
    name: str
    currency: str = "INR"
    gateway_mode: str = "test"


class PayUCredentialsOut(BaseModel):
    merchant_key_is_set: bool
    merchant_salt_is_set: bool


class PayUCredentialsIn(BaseModel):
    # None = leave the currently-stored value unchanged; "" clears it.
    merchant_key: str | None = None
    merchant_salt: str | None = None


class PaymentGatewayConfigOut(BaseModel):
    default_gateway: str
    available_gateways: list[str]
    payu_test: PayUCredentialsOut
    payu_live: PayUCredentialsOut


class PaymentGatewayConfigUpdate(BaseModel):
    default_gateway: str
    payu_test: PayUCredentialsIn | None = None
    payu_live: PayUCredentialsIn | None = None


class EveryticketIntegrationOut(BaseModel):
    secret_key_is_set: bool
    webhook_url: str | None = None
    extra_params: dict[str, str]
    retry_limit: int | None = None  # None = use the env schedule's own length
    default_retry_limit: int  # informational: WEBHOOK_RETRY_SCHEDULE_MINUTES's length, shown as a placeholder
    escalation_emails: str | None = None  # comma-separated
    escalation_email_subject: str | None = None
    escalation_email_body: str | None = None


class EveryticketIntegrationUpdate(BaseModel):
    secret_key: str | None = None  # None = unchanged, "" clears
    webhook_url: str | None = None
    extra_params: dict[str, str] | None = None
    retry_limit: int | None = None
    escalation_emails: str | None = None
    escalation_email_subject: str | None = None
    escalation_email_body: str | None = None


class NotificationConfigOut(BaseModel):
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_username: str | None = None
    smtp_password_is_set: bool
    smtp_use_tls: bool | None = None  # None = inherit the global env default
    email_sender_name: str | None = None
    email_sender_address: str | None = None
    email_reply_to: str | None = None


class NotificationConfigUpdate(BaseModel):
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_username: str | None = None
    smtp_password: str | None = None  # None = unchanged, "" clears
    smtp_use_tls: bool | None = None
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
    payment_gateway: PaymentGatewayConfigOut
    integration: EveryticketIntegrationOut
    notification: NotificationConfigOut
    subscription_rules: ApplicationSubscriptionRulesOut
