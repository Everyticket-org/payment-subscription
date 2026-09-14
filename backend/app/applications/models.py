"""
Application configuration (spec section 13).

V1 has exactly one row: code="EVERYTICKET". The model is deliberately
generic so a second external application can be onboarded later without a
schema change - just insert another row.

Highly sensitive values (webhook secret, gateway credentials, SSO secret)
are stored here so they're admin-configurable per spec section 81, but the
admin API layer must never return them in plaintext in list/detail
responses (mask them), and production deployments should prefer setting
them via environment variables and treating these columns as
overrides/fallback only.
"""
from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin


class Application(Base, TimestampMixin):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # --- General ---
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)  # e.g. EVERYTICKET
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    application_url: Mapped[str] = mapped_column(String(500), nullable=False)
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    favicon_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    support_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    support_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    timezone: Mapped[str] = mapped_column(String(50), default="Asia/Kolkata", nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # --- Integration ---
    api_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    api_credentials: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # masked in API responses
    webhook_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    webhook_secret: Mapped[str | None] = mapped_column(String(500), nullable=True)  # masked in API responses
    sso_secret: Mapped[str | None] = mapped_column(String(500), nullable=True)  # masked in API responses

    # --- Payment ---
    default_gateway: Mapped[str] = mapped_column(String(50), default="mock", nullable=False)
    gateway_mode: Mapped[str] = mapped_column(String(20), default="test", nullable=False)  # test | live

    # --- Email ---
    email_provider: Mapped[str] = mapped_column(String(50), default="smtp", nullable=False)
    email_sender_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_sender_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email_reply_to: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # --- Subscription rules ---
    allow_upgrade: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    allow_downgrade: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    allow_cancellation: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    cancellation_behavior: Mapped[str] = mapped_column(String(50), default="IMMEDIATE", nullable=False)
    renewal_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    repurchase_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # --- Everyticket integration: extra webhook POST params, retry limit,
    # escalation email on EXHAUSTED delivery (2026-09 admin config restructure) ---
    webhook_extra_params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    webhook_retry_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)  # None = use WEBHOOK_RETRY_SCHEDULE_MINUTES's own length
    webhook_escalation_emails: Mapped[str | None] = mapped_column(String(1000), nullable=True)  # comma-separated
    webhook_escalation_email_subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    webhook_escalation_email_body: Mapped[str | None] = mapped_column(Text, nullable=True)  # sanitized rich text, see app.plans.sanitize
    # Per-event selection of OPTIONAL extra fields to include in outbound
    # Everyticket webhook payloads (2026-09-14 follow-up: "allow to
    # configure, more data to be passed for webhook call like plan details
    # including name, amount, expiry etc.. so if admin select those
    # parameters then it will be passed to webhook"). Shape:
    # {event_type: [field_name, ...]}, e.g. {"subscription.renewed":
    # ["plan_name", "amount"]}. Only event types/field names present in
    # app.webhooks.field_catalog.AVAILABLE_FIELDS are ever honored - see
    # field_catalog.sanitize_selection(), applied both on save and on read
    # so a stale value from a previous catalog version can never make a
    # payload builder look for a field it no longer supports. None/missing
    # key = no optional fields for that event, i.e. today's fixed payload.
    webhook_field_selection: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # --- Notifications: real SMTP transport override (previously env-only via Settings.SMTP_*) ---
    smtp_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    smtp_port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    smtp_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    smtp_password: Mapped[str | None] = mapped_column(String(500), nullable=True)  # masked in API responses
    smtp_use_tls: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # None = inherit env default
    # Master on/off switch for this application's email sending (2026-09-13
    # follow-up: "add one more field... 'Enable Notifications?'... if its
    # enabled, email service will work otherwise it will skip") - checked
    # by app.notifications.email.service before every send, regardless of
    # how correctly SMTP itself is configured above. Defaults True so
    # every existing application keeps sending exactly as it does today.
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # --- Payment redirect / webhook URLs (2026-09 follow-up: "PayU redirect
    # back to localhost:4200 which is wrong. instead allow to configure
    # return URL and PayU webhook URL") - both override an env default
    # (settings.FRONTEND_URL / settings.PAYU_SUCCESS_URL+PAYU_FAILURE_URL)
    # the same way every other per-application override in this app does. ---
    return_url: Mapped[str | None] = mapped_column(String(500), nullable=True)  # frontend app URL: /payment/return, /sso/consume
    payu_webhook_base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)  # this backend's own public base URL

    # --- Everyticket integration: archive/delete after N days of non-renewal
    # (2026-09 follow-up, third webhook type) - None/0 = disabled. ---
    archive_after_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- Post-subscription confirmation message (2026-09-13 follow-up:
    # "show message 'You have successfully subscribed, you will get your
    # credentials in sometime' for first time subscription... This message
    # also should be configurable") - shown on the public thank-you screen
    # (SubscribePage's mock "done" step, PaymentReturnPage's PayU success
    # branch) only after a NEW subscription's first payment succeeds, never
    # on a renewal/upgrade/downgrade - see app.payments.schemas.
    # PaymentTransactionOut.payment_type, which is what the frontend
    # actually gates this on. Nullable: unset means "use the built-in
    # default text" (app.applications.config_schemas.
    # DEFAULT_POST_SUBSCRIPTION_MESSAGE), same fallback pattern as
    # duplicate_message/validation_message on registration form fields -
    # never a hardcoded value baked into a migration's server_default. ---
    post_subscription_message: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # --- Testing (spec section 55: also always gated on ENVIRONMENT != production at runtime) ---
    test_mode: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    otp_bypass_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mfa_bypass_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    payment_simulation_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    plans: Mapped[list["Plan"]] = relationship(back_populates="application")
    form_fields: Mapped[list["RegistrationFormField"]] = relationship(back_populates="application")


class CustomerApplicationMapping(Base, TimestampMixin):
    """
    Permanent mapping: CUS-xxxx <-> external application identity
    (spec section 8). One row per (customer, application); unique on
    (application_id, external_customer_id) too so we never create a second
    Everyticket instance for the same external identity.
    """
    __tablename__ = "customer_application_mappings"
    __table_args__ = (
        UniqueConstraint("customer_id", "application_id", name="uq_customer_application"),
        UniqueConstraint("application_id", "external_customer_id", name="uq_application_external_customer"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False, index=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), nullable=False, index=True)
    external_customer_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)  # e.g. MUSEUM-4587
    external_instance_id: Mapped[str | None] = mapped_column(String(100), nullable=True)  # e.g. INSTANCE-1001

    customer: Mapped["Customer"] = relationship(back_populates="application_mappings")
    application: Mapped["Application"] = relationship()
