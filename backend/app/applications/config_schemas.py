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
     Also carries return_url/payu_webhook_base_url (2026-09 follow-up:
     "PayU redirect back to localhost:4200 which is wrong. instead allow
     to configure return URL and PayU webhook URL") - real columns on
     this model, not secrets, echoed back as plain URLs.
  3. Everyticket Integration - the webhook secret ("Secret Key"),
     destination URL, an admin-configurable retry limit, an escalation
     email (recipients + admin-edited subject/body) sent once a delivery
     is EXHAUSTED, an archive_after_days threshold for the archive
     webhook, and webhook_samples - a read-only preview of the exact
     JSON each of the five real event types sends (2026-09 follow-up:
     "Webhook for everyticket app are as below: 1) onboarding... 2)
     status inactive when plan expires... 3) delete/archive when user do
     not renew for x days", plus follow-up 3's "Add one more webhook for
     renew" - see app.webhooks.payloads). `api_url`/`api_credentials`/
     `sso_secret` (SSO is a separate concern from webhook delivery) are
     deliberately not on this screen any more - their columns/behavior
     are unchanged, just not exposed here (SSO already has its own env
     fallback). The custom key/value extra-parameters editor that used
     to live on this screen was removed in follow-up 3 ("Remove feature
     for parameters (key,value) from this section") - the underlying
     Application.webhook_extra_params column is kept (no migration,
     matching this codebase's "dead column" convention for a removed
     admin field) but is no longer read or written by this screen.
  4. Notifications - real SMTP transport (host/port/username/password/
     use_tls, previously env-only) plus the pre-existing sender name/
     address/reply-to overrides, plus a master `notifications_enabled`
     on/off switch (2026-09-13 follow-up: "Enable Notifications?") that
     app.notifications.email.service checks before every send for this
     application, independent of whether SMTP itself is configured
     correctly.

Section 1 (Application) also carries `post_subscription_message`
(2026-09-13 follow-up: "show message '...you will get your credentials
in sometime' for first time subscription... This message also should be
configurable") - free text shown on the public thank-you screen after a
brand-new subscription's first payment succeeds (never on a renewal/
upgrade/downgrade change-plan, since that customer already has
credentials - see app.api.v1.public.PublicMessagesOut and
DEFAULT_POST_SUBSCRIPTION_MESSAGE below).

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

# Shown on the public thank-you screen when an application hasn't
# configured its own post_subscription_message (column defaults to NULL -
# see Application.post_subscription_message) - same "nullable column,
# code-level fallback text" convention as validation_message/
# duplicate_message on registration form fields, so a blank admin field
# never silently means "show nothing" for every new subscriber.
DEFAULT_POST_SUBSCRIPTION_MESSAGE = "You have successfully subscribed, you will get your credentials in sometime."


class ApplicationGeneralOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    name: str
    currency: str
    gateway_mode: str  # test | live - "Live/Test Mode"
    post_subscription_message: str | None = None


class ApplicationGeneralUpdate(BaseModel):
    name: str
    currency: str = "INR"
    gateway_mode: str = "test"
    # None/"" both mean "use the default text" - applied at read time by
    # whoever serves it publicly (app.api.v1.public.get_public_messages),
    # never baked into this column as a hardcoded default.
    post_subscription_message: str | None = None


class PublicMessagesOut(BaseModel):
    """GET /public/messages - the small set of admin-configurable, public-
    facing UI strings (currently just one). Deliberately its own tiny
    endpoint/schema rather than folded into an existing response, since
    it's read from two different, unrelated frontend pages: SubscribePage
    (mock gateway "done" step) and PaymentReturnPage (PayU redirect
    success branch) - see app.api.v1.public.get_public_messages, which
    applies DEFAULT_POST_SUBSCRIPTION_MESSAGE when the admin hasn't set
    one."""
    post_subscription_message: str


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
    # 2026-09 follow-up: "PayU redirect back to localhost:4200 which is
    # wrong. instead allow to configure return URL and PayU webhook URL" -
    # both override an env default (settings.FRONTEND_URL / settings.
    # PAYU_SUCCESS_URL+PAYU_FAILURE_URL) when set; None here means "not
    # configured, currently falling back to the env default".
    return_url: str | None = None  # frontend app URL customers land back on after paying
    payu_webhook_base_url: str | None = None  # this backend's own public base URL PayU calls back to


class PaymentGatewayConfigUpdate(BaseModel):
    default_gateway: str
    payu_test: PayUCredentialsIn | None = None
    payu_live: PayUCredentialsIn | None = None
    return_url: str | None = None
    payu_webhook_base_url: str | None = None


class EveryticketWebhookSampleOut(BaseModel):
    """One entry per real outbound webhook event type (2026-09 follow-up:
    "Webhook for everyticket app are as below..." - show a sample JSON
    payload for each so Everyticket's own endpoint can be built against
    the real shape). `payload` is generated by the SAME function that
    builds a real delivery (app.webhooks.payloads) - see that module's
    docstring - so this can never quietly drift from what's actually
    sent."""
    event: str
    trigger: str
    payload: dict


class EveryticketWebhookFieldCatalogEntry(BaseModel):
    """One field an admin can SEE for one event - either an OPTIONAL one
    they can tick, or a FIXED one shown as an always-included, disabled
    entry (2026-09-14 follow-up: "allow to configure, more data to be
    passed for webhook call..."; 2026-09-14 follow-up 2: "activated does
    not have plan name, code, price... where it has to be... keep
    consistency" - fixed fields are now shown too, so nothing looks
    missing). `field` is the exact JSON key that appears in the outbound
    payload; `label` is a short human-readable description. Sourced
    directly from app.webhooks.field_catalog - see that module for the
    full explanation of what's available/fixed per event and why."""
    field: str
    label: str


class EveryticketIntegrationOut(BaseModel):
    secret_key_is_set: bool
    webhook_url: str | None = None
    retry_limit: int | None = None  # None = use the env schedule's own length
    default_retry_limit: int  # informational: WEBHOOK_RETRY_SCHEDULE_MINUTES's length, shown as a placeholder
    escalation_emails: str | None = None  # comma-separated
    escalation_email_subject: str | None = None
    escalation_email_body: str | None = None
    # None/0 = disabled - "third [webhook] to delete/archive when user do
    # not renew for x days" (2026-09 follow-up).
    archive_after_days: int | None = None
    webhook_samples: list[EveryticketWebhookSampleOut]
    # 2026-09-14 follow-up 3: "when select checkbox for parameters, it
    # should reflect into sample JSON as well" - live, in the browser, as
    # each box is ticked, not only after Save. Same shape as
    # webhook_samples above but built as if EVERY optional field for
    # every event were selected, regardless of what's actually stored -
    # so it carries a real sample value for every possible field. The
    # frontend never invents a value itself; it only shows/hides keys
    # already present here to reflect the checkboxes' current (possibly
    # unsaved) state, so no sample value is ever computed outside
    # app.webhooks.payloads (see build_webhook_samples' own docstring).
    webhook_samples_all_fields: list[EveryticketWebhookSampleOut]
    # 2026-09-14 follow-up: "allow to configure, more data to be passed
    # for webhook call like plan details including name, amount, expiry
    # etc.. so if admin select those parameters then it will be passed to
    # webhook". webhook_field_catalog is every OPTIONAL field selectable
    # per event (event_type -> [{field, label}, ...], in display order) -
    # the frontend renders one checklist group per event from this;
    # webhook_field_selection is this application's CURRENTLY selected
    # subset (event_type -> [field_name, ...]), sanitized against the
    # catalog above so a stale value from a previous catalog version can
    # never be echoed back. webhook_fixed_fields (2026-09-14 follow-up 2)
    # is the complementary always-sent field list per event, display-only
    # (never part of a selection - a builder doesn't need telling to
    # include something it already always includes) - shown alongside
    # webhook_field_catalog so every event's full field picture is
    # visible, not just its optional extras. All three come straight from
    # app.webhooks.field_catalog - see that module's own docstring.
    webhook_field_catalog: dict[str, list[EveryticketWebhookFieldCatalogEntry]]
    webhook_fixed_fields: dict[str, list[EveryticketWebhookFieldCatalogEntry]]
    webhook_field_selection: dict[str, list[str]]
    # --- Everyticket -> this app API credentials (2026-09-13 follow-up 3:
    # "Test SSO Link - Actually this has to be generated by Everyticket
    # platform to login into subscription engine... so need to give API
    # to everyticket Platform to call that which generates token and
    # return a link") - authenticates POST /api/v1/integration/sso/
    # generate-link (app.api.v1.integration), the opposite direction of
    # webhook_secret (which signs OUR calls TO Everyticket). Stored in the
    # existing, previously-unused Application.api_credentials JSON column
    # (no migration needed) as {"api_key": ..., "api_secret": ...}.
    # api_key is shown in plain text (it's an identifier, like a
    # client_id, not a secret by itself); api_secret follows the same
    # masked-boolean convention as every other secret on this screen.
    api_key: str | None = None
    api_secret_is_set: bool = False


class EveryticketIntegrationUpdate(BaseModel):
    secret_key: str | None = None  # None = unchanged, "" clears
    webhook_url: str | None = None
    retry_limit: int | None = None
    escalation_emails: str | None = None
    escalation_email_subject: str | None = None
    escalation_email_body: str | None = None
    archive_after_days: int | None = None
    # 2026-09-14 follow-up: this application's per-event OPTIONAL field
    # selection (event_type -> [field_name, ...]). Replaced outright when
    # given, same "always replace" convention as retry_limit/
    # archive_after_days above (not a secret, so no need for the
    # None=unchanged/""=clear convention those use) - the frontend always
    # sends the full current selection back, never a partial patch. None
    # clears every event's selection back to just the fixed payload
    # shape. Sanitized against app.webhooks.field_catalog before being
    # stored (app.api.v1.admin_config.update_integration_config), so an
    # unrecognized event type or field name is silently dropped rather
    # than rejected outright - keeps this endpoint forward/backward
    # compatible with catalog changes across releases.
    webhook_field_selection: dict[str, list[str]] | None = None
    # None = unchanged, "" clears - same convention as secret_key above.
    api_key: str | None = None
    api_secret: str | None = None


class NotificationConfigOut(BaseModel):
    notifications_enabled: bool
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_username: str | None = None
    smtp_password_is_set: bool
    smtp_use_tls: bool | None = None  # None = inherit the global env default
    email_sender_name: str | None = None
    email_sender_address: str | None = None
    email_reply_to: str | None = None


class NotificationConfigUpdate(BaseModel):
    notifications_enabled: bool = True
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
