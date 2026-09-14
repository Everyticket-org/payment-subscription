"""
Catalog of every field an admin can SEE for each outbound Everyticket
webhook event, split into two groups (2026-09-14 follow-up: "allow to
configure[...] more data to be passed for webhook call like plan details
including name, amount, expiry etc.. so if admin select those parameters
then it will be passed to webhook"; 2026-09-14 follow-up 2: "subscription
.activated does not have plan name, code, price etc.. where it has to
be, same for renewed event there is no plan code, please keep
consistency" - the admin Configuration screen originally showed ONLY the
optional group below, so an event whose plan_code/plan_name/price happen
to be FIXED (always sent - activated, upgraded, downgraded) looked like
it was missing them entirely, while an event where they're genuinely
optional (renewed/expired/cancelled/archived) showed them as ordinary
checkboxes - an inconsistent picture of the same underlying fields
across events. FIXED_FIELDS below makes every event's full field
picture visible - "always sent" plus "optional" - so nothing looks
missing, it's just correctly labeled):

  - FIXED_FIELDS: event_type -> the ordered list of field keys that
    event's payload builder ALWAYS includes, with no admin action
    needed (e.g. plan_code/plan_name/price for subscription.activated).
    Purely informational/display - shown in the Configuration screen's
    checklist as pre-ticked, disabled entries so an admin can see the
    whole payload shape at a glance, never sent to the backend as part
    of a selection (a payload builder doesn't need to be told to include
    something it already always includes).
  - AVAILABLE_FIELDS: event_type -> the ordered list of OPTIONAL field
    keys that event's payload builder (app.webhooks.payloads) can ALSO
    fill in if selected. This is the single source of truth for "what
    can an admin tick for this event" - the admin Configuration screen's
    checklist (EveryticketIntegrationOut.webhook_field_catalog) is built
    directly from this, and app.webhooks.payloads validates against it
    too, so the two can never drift apart.
  - FIELD_LABELS: field key -> short human-readable label, for rendering
    both groups above (e.g. "phone_number" -> "Customer phone number").

Every field listed here (fixed or optional) is already sitting on an ORM
object already loaded in memory at the one call site that fires each
event (see app.payments.service.process_gateway_result for activated/
renewed/upgraded/downgraded, app.subscriptions.service for expired/
cancelled/archived) - none of this requires an extra DB query to satisfy.

Deliberately excluded, per Vishal's own decision when this was scoped:
payment/invoice fields for expired/cancelled/archived - nothing was
actually charged at the moment those fire, so there is no real payment or
invoice to report; offering those fields there would just be admin-visible
nulls.

Field names are the exact JSON keys that will appear in the outbound
payload - chosen to match the wire-naming convention the fixed fields
already use (e.g. "phone_number", not the Customer model's own "mobile"
column name - see app.webhooks.payloads.onboarding_payload's own
docstring for why that rename happened).
"""

# --- Field labels, for the admin Configuration screen's checklist ---
FIELD_LABELS: dict[str, str] = {
    "subscription_id": "Subscription ID",
    "status": "Subscription status (ACTIVE/EXPIRED/CANCELLED/...)",
    # Plan
    "plan_code": "Plan code",
    "plan_name": "Plan name",
    "price": "Plan price",
    "currency": "Currency",
    "billing_interval": "Billing interval (month/year)",
    "billing_frequency": "Billing frequency (every N intervals)",
    "is_trial": "Is a free trial",
    "trial_period_days": "Trial period (days)",
    # Subscription
    "starts_at": "Subscription start date/time",
    "expires_at": "Subscription expiry date/time",
    # Customer
    "customer_id": "Customer ID",
    "email": "Customer email",
    "phone_number": "Customer phone number",
    # Cancellation detail (subscription.cancelled only)
    "cancelled_at": "Cancelled at (date/time)",
    "cancelled_by": "Cancelled by (customer/admin identifier)",
    "cancellation_reason": "Cancellation reason",
    # Payment / invoice (activated, renewed, upgraded, downgraded only -
    # these are the only four events where a real payment/invoice exists)
    "transaction_id": "Payment transaction ID",
    "payment_type": "Payment type (NEW/RENEWAL/UPGRADE/DOWNGRADE)",
    "gateway": "Payment gateway used (mock/payu)",
    "amount": "Payment amount",
    "invoice_id": "Invoice ID",
    "total_amount": "Invoice total amount",
    "tax_amount": "Invoice tax amount",
}

# --- Per-event FIXED field lists (always sent today, no admin action
# needed - display-only, see the module docstring above). Must be kept
# in sync with each builder's own "fixed" dict in app.webhooks.payloads -
# there's no shared code path to enforce that automatically since these
# are never passed back INTO a builder (unlike AVAILABLE_FIELDS, which
# payloads.py itself validates selections against). ---
FIXED_FIELDS: dict[str, list[str]] = {
    "subscription.activated": [
        "subscription_id", "email", "phone_number", "plan_code", "plan_name", "price", "is_trial", "expires_at",
    ],
    "subscription.renewed": ["subscription_id"],
    "subscription.upgraded": ["subscription_id", "customer_id", "plan_code", "status", "expires_at", "transaction_id"],
    "subscription.downgraded": ["subscription_id", "customer_id", "plan_code", "status", "expires_at", "transaction_id"],
    "subscription.expired": ["subscription_id"],
    "subscription.cancelled": ["subscription_id"],
    "subscription.archived": ["subscription_id"],
}

# --- Per-event optional field lists (order = display order in the UI) ---
_PLAN_CORE = ["plan_code", "plan_name", "price", "currency", "billing_interval", "billing_frequency"]
_PAYMENT_INVOICE = ["transaction_id", "payment_type", "gateway", "amount", "invoice_id", "total_amount", "tax_amount"]

AVAILABLE_FIELDS: dict[str, list[str]] = {
    # Fixed/always-sent today: subscription_id, email, phone_number,
    # plan_code, plan_name, price, is_trial, expires_at, plus every
    # registration-form answer flattened in - see onboarding_payload().
    "subscription.activated": [
        "currency", "billing_interval", "billing_frequency", "trial_period_days",
        "starts_at", "customer_id",
        "transaction_id", "payment_type", "gateway", "invoice_id", "total_amount", "tax_amount",
    ],
    # Fixed/always-sent today: subscription_id only.
    "subscription.renewed": [
        *_PLAN_CORE, "trial_period_days", "is_trial",
        "starts_at", "expires_at",
        "customer_id", "email", "phone_number",
        "transaction_id", "payment_type", "amount", "invoice_id", "total_amount",
    ],
    # Fixed/always-sent today: subscription_id, customer_id, plan_code,
    # status, expires_at, transaction_id.
    "subscription.upgraded": [
        "plan_name", "price", "currency", "billing_interval", "billing_frequency", "trial_period_days", "is_trial",
        "starts_at",
        "email", "phone_number",
        "payment_type", "gateway", "amount", "invoice_id", "total_amount", "tax_amount",
    ],
    "subscription.downgraded": [
        "plan_name", "price", "currency", "billing_interval", "billing_frequency", "trial_period_days", "is_trial",
        "starts_at",
        "email", "phone_number",
        "payment_type", "gateway", "amount", "invoice_id", "total_amount", "tax_amount",
    ],
    # Fixed/always-sent today: subscription_id only. No payment/invoice
    # fields - nothing was charged when a subscription simply expires.
    "subscription.expired": [
        *_PLAN_CORE, "trial_period_days", "is_trial",
        "starts_at", "expires_at",
        "customer_id", "email", "phone_number",
    ],
    # Fixed/always-sent today: subscription_id only. Same as expired, plus
    # the three cancellation-specific fields that only exist on this event.
    "subscription.cancelled": [
        *_PLAN_CORE, "trial_period_days", "is_trial",
        "starts_at", "expires_at",
        "customer_id", "email", "phone_number",
        "cancelled_at", "cancelled_by", "cancellation_reason",
    ],
    # Fixed/always-sent today: subscription_id only. Same shape as expired.
    "subscription.archived": [
        *_PLAN_CORE, "trial_period_days", "is_trial",
        "starts_at", "expires_at",
        "customer_id", "email", "phone_number",
    ],
}

EVENT_TYPES: list[str] = list(AVAILABLE_FIELDS.keys())


def sanitize_selection(raw: dict | None) -> dict[str, list[str]]:
    """Drops any event key this catalog doesn't know about and any field
    name not in that event's own AVAILABLE_FIELDS list, so a stale/tampered
    stored selection (e.g. after this catalog is edited in a future
    release) can never make a payload builder try to fill in a field it no
    longer - or doesn't yet - support. Used both when reading a stored
    selection back out and when saving a new one from the admin API."""
    if not raw:
        return {}
    cleaned: dict[str, list[str]] = {}
    for event_type, field_names in raw.items():
        available = AVAILABLE_FIELDS.get(event_type)
        if not available or not isinstance(field_names, list):
            continue
        kept = [f for f in field_names if f in available]
        if kept:
            cleaned[event_type] = kept
    return cleaned
