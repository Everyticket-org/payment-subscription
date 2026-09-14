"""
Pure payload-shaping functions for the seven outbound Everyticket webhook
events (2026-09 follow-up 3 - Vishal's own numbered list: "Add one more
webhook for renew"; trimmed every payload down to exactly the fields he
listed, and simplified the wire envelope to just event_type + payload;
2026-09-14 follow-up: "allow to configure, more data to be passed for
webhook call like plan details including name, amount, expiry etc.. so if
admin select those parameters then it will be passed to webhook to
everyticket" - every builder below now also accepts every OPTIONAL field
app.webhooks.field_catalog.AVAILABLE_FIELDS lists for that event, plus a
`selected_fields` list, and merges in only the ones the admin actually
selected):

  1. onboarding_payload  - subscription.activated, first-time signup.
     Fixed payload: subscription_id, email, phone_number, plan_code,
     plan_name, price, is_trial, expires_at, plus every registration-form
     answer merged in FLAT at the top level (2026-09-11 follow-up: "Keep
     the key for email and phone number as below shown in JSON... Pass
     payload like this flat structure including registration form
     data.." - registration_data used to be nested under its own key;
     it is now spread directly alongside the other fields instead, and
     the phone number's wire key changed from "mobile" to
     "phone_number" - the Customer model's own column is still called
     mobile, only the outbound JSON key name changed).
  2. renewed_payload    - subscription.renewed, an existing subscription
     is renewed on its current plan. Fixed payload: subscription_id only.
  3. expiry_payload     - subscription.expired, plan expires unrenewed.
     Fixed payload: subscription_id only.
  4. cancelled_payload  - subscription.cancelled, a customer cancels.
     Fixed payload: subscription_id only.
  5. archive_payload    - subscription.archived, still unrenewed after
     the admin-configured archive_after_days window. Fixed payload:
     subscription_id only.
  6. upgraded_payload   - subscription.upgraded, a paid plan change goes
     up in price. Fixed payload: subscription_id, customer_id, plan_code,
     status, expires_at, transaction_id (unchanged from before this
     event type was brought into the configurable-fields system).
  7. downgraded_payload - subscription.downgraded, a paid plan change
     goes down in price. Same fixed payload shape as upgraded_payload.

Deliberately built from primitives, not ORM objects, so the exact same
function that shapes a REAL delivery's payload (app.payments.service /
app.subscriptions.service) also shapes the admin Configuration screen's
read-only "sample JSON" preview (app.api.v1.admin_config) - one source
of truth, so the documentation can never quietly drift from what's
actually sent over the wire. The wire envelope itself (event_type +
payload) is built by app.webhooks.service.build_wire_body().

Every builder's OPTIONAL fields default to None and are only merged into
the returned payload when the caller both passes a non-default value AND
lists that field's name in `selected_fields` (normally
application.webhook_field_selection[event_type], already sanitized once
via app.webhooks.field_catalog.sanitize_selection when read out of the
Application row - see _select_optional_fields() below for the second,
defense-in-depth sanitize pass done here). A caller that never passes
selected_fields (or passes an empty/None one) gets EXACTLY today's fixed
payload shape - existing behavior for every application that hasn't
opted in is completely unchanged.

Precedence on key collisions, applied consistently across every builder:
fixed fields always win, then admin-selected optional fields, then (for
onboarding_payload only) the customer's own registration-form answers.
This matches the precedence rule onboarding_payload already documented
for fixed-vs-registration_data, extended one level: a real structured
data field the admin explicitly chose to include is still more
trustworthy than an arbitrarily-named customer form answer that happens
to collide with it.

build_webhook_samples() below (2026-09-13 follow-up: moved here, out of
admin_config.py, so the admin Testing page's "Test Everyticket webhook"
event dropdown - app.api.v1.admin_testing.get_webhook_samples - can
reuse the EXACT same sample bodies the Configuration screen's preview
shows, rather than a second, easily-drifting copy) builds the full list
of {event, trigger, payload} samples for all seven real event types,
application-aware (reflects this application's actual registration-form
fields, an active plan when one exists, and its current
webhook_field_selection).
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session


def _select_optional_fields(*, event_type: str, values: dict[str, object], selected_fields: list[str] | None) -> dict:
    """Given every OPTIONAL field's raw value for one event (field_name ->
    value, covering everything app.webhooks.field_catalog.AVAILABLE_FIELDS
    lists for event_type) and the admin's selected_fields list, returns
    just the subset of `values` to merge into the final payload: only
    names that are BOTH selected AND recognized for this event.

    The recognized-for-this-event check is a second, defense-in-depth
    sanitize pass - selected_fields is normally already the output of
    field_catalog.sanitize_selection() applied when
    Application.webhook_field_selection was read out of the DB - so a
    stale selection saved against an older version of the catalog (a
    field renamed or removed since) can never make it into a real
    payload even if that first sanitize pass were ever skipped by a
    future caller."""
    if not selected_fields:
        return {}
    from app.webhooks.field_catalog import AVAILABLE_FIELDS

    available = AVAILABLE_FIELDS.get(event_type, [])
    return {name: values[name] for name in selected_fields if name in available and name in values}


def onboarding_payload(
    *,
    subscription_id: str,
    email: str | None,
    mobile: str | None,
    plan_code: str,
    plan_name: str,
    price: float,
    is_trial: bool,
    expires_at: str | None,
    registration_data: dict,
    currency: str | None = None,
    billing_interval: str | None = None,
    billing_frequency: int | None = None,
    trial_period_days: int | None = None,
    starts_at: str | None = None,
    customer_id: str | None = None,
    transaction_id: str | None = None,
    payment_type: str | None = None,
    gateway: str | None = None,
    invoice_id: str | None = None,
    total_amount: float | None = None,
    tax_amount: float | None = None,
    selected_fields: list[str] | None = None,
) -> dict:
    """subscription.activated - fires exactly once, the moment a NEW
    subscription's payment succeeds (never on renew/upgrade/downgrade -
    see app.payments.service.process_gateway_result's payment_type
    branch, which routes those to their own event_type instead).
    Carries every registration-form answer the customer submitted at
    signup (registration_data - see app.customers.models.
    CustomerRegistrationData) so Everyticket can provision the account
    without a second round-trip to ask for the same details.

    email/mobile were re-added in an earlier follow-up ("in activated
    json, customer data also need to be there.. email and mobile as
    part of payload or registration data") - kept as their own
    top-level fields rather than folded into registration_data, since
    they're account-level identity, not a form answer, and every
    subscribe flow has them regardless of what the registration form
    asks.

    2026-09-11 follow-up ("Keep the key for email and phone number as
    below shown in JSON: {email, phone_number}... Pass payload like
    this flat structure including registration form data.."): the wire
    key for the customer's mobile number is now "phone_number" (this
    function's own `mobile` parameter name is unchanged - it still maps
    onto the Customer model's own `mobile` column, only the JSON key
    sent over the wire changed), and registration_data's fields are now
    spread directly at the top level of the payload instead of nested
    under a "registration_data" key - the fixed fields below always
    win if a registration form's field_key happens to collide with one
    of them, so a customer-editable form answer can never silently
    overwrite subscription_id/email/phone_number/plan/price/trial/expiry.

    Still no customer_id or external identity in the FIXED shape -
    trimmed to exactly the fields Vishal originally asked to keep.
    Everyticket's own response to THIS delivery is what assigns the
    external identity (spec section 32) - see
    app.webhooks.service._handle_activation_outcome, which upserts
    CustomerApplicationMapping from that response. customer_id (and the
    plan/payment/invoice detail params above) are available as OPT-IN
    extras an admin can select via Configuration > Everyticket
    integration - see app.webhooks.field_catalog.AVAILABLE_FIELDS[
    "subscription.activated"]."""
    fixed = {
        "subscription_id": subscription_id,
        "email": email,
        "phone_number": mobile,
        "plan_code": plan_code,
        "plan_name": plan_name,
        "price": price,
        "is_trial": is_trial,
        "expires_at": expires_at,
    }
    optional_values = {
        "currency": currency,
        "billing_interval": billing_interval,
        "billing_frequency": billing_frequency,
        "trial_period_days": trial_period_days,
        "starts_at": starts_at,
        "customer_id": customer_id,
        "transaction_id": transaction_id,
        "payment_type": payment_type,
        "gateway": gateway,
        "invoice_id": invoice_id,
        "total_amount": total_amount,
        "tax_amount": tax_amount,
    }
    selected = _select_optional_fields(
        event_type="subscription.activated", values=optional_values, selected_fields=selected_fields
    )
    return {**registration_data, **selected, **fixed}


def renewed_payload(
    *,
    subscription_id: str,
    plan_code: str | None = None,
    plan_name: str | None = None,
    price: float | None = None,
    currency: str | None = None,
    billing_interval: str | None = None,
    billing_frequency: int | None = None,
    trial_period_days: int | None = None,
    is_trial: bool | None = None,
    starts_at: str | None = None,
    expires_at: str | None = None,
    customer_id: str | None = None,
    email: str | None = None,
    phone_number: str | None = None,
    transaction_id: str | None = None,
    payment_type: str | None = None,
    amount: float | None = None,
    invoice_id: str | None = None,
    total_amount: float | None = None,
    selected_fields: list[str] | None = None,
) -> dict:
    """subscription.renewed - fires once an existing subscription's
    RENEWAL payment succeeds (app.payments.service.process_gateway_result),
    extending expires_at on the same plan. Fixed payload: subscription_id
    only (2026-09 follow-up 3) - every other parameter here is an OPT-IN
    extra, see app.webhooks.field_catalog.AVAILABLE_FIELDS[
    "subscription.renewed"]."""
    optional_values = {
        "plan_code": plan_code,
        "plan_name": plan_name,
        "price": price,
        "currency": currency,
        "billing_interval": billing_interval,
        "billing_frequency": billing_frequency,
        "trial_period_days": trial_period_days,
        "is_trial": is_trial,
        "starts_at": starts_at,
        "expires_at": expires_at,
        "customer_id": customer_id,
        "email": email,
        "phone_number": phone_number,
        "transaction_id": transaction_id,
        "payment_type": payment_type,
        "amount": amount,
        "invoice_id": invoice_id,
        "total_amount": total_amount,
    }
    selected = _select_optional_fields(
        event_type="subscription.renewed", values=optional_values, selected_fields=selected_fields
    )
    return {**selected, "subscription_id": subscription_id}


def _plan_lifecycle_payload(
    *,
    event_type: str,
    subscription_id: str,
    plan_code: str | None,
    plan_name: str | None,
    price: float | None,
    currency: str | None,
    billing_interval: str | None,
    billing_frequency: int | None,
    trial_period_days: int | None,
    is_trial: bool | None,
    starts_at: str | None,
    expires_at: str | None,
    customer_id: str | None,
    email: str | None,
    phone_number: str | None,
    selected_fields: list[str] | None,
    extra_values: dict[str, object] | None = None,
) -> dict:
    """Shared shape for subscription.expired/archived (identical optional
    field lists - see field_catalog.AVAILABLE_FIELDS) and the base of
    subscription.cancelled (same list plus three cancellation-only
    fields passed in via extra_values by cancelled_payload below). No
    payment/invoice fields for any of these three - nothing was charged
    at the moment a subscription simply expires, gets archived, or is
    cancelled, so offering those fields here would just be admin-visible
    nulls (Vishal's own decision when this was scoped)."""
    optional_values = {
        "plan_code": plan_code,
        "plan_name": plan_name,
        "price": price,
        "currency": currency,
        "billing_interval": billing_interval,
        "billing_frequency": billing_frequency,
        "trial_period_days": trial_period_days,
        "is_trial": is_trial,
        "starts_at": starts_at,
        "expires_at": expires_at,
        "customer_id": customer_id,
        "email": email,
        "phone_number": phone_number,
        **(extra_values or {}),
    }
    selected = _select_optional_fields(event_type=event_type, values=optional_values, selected_fields=selected_fields)
    return {**selected, "subscription_id": subscription_id}


def expiry_payload(
    *,
    subscription_id: str,
    plan_code: str | None = None,
    plan_name: str | None = None,
    price: float | None = None,
    currency: str | None = None,
    billing_interval: str | None = None,
    billing_frequency: int | None = None,
    trial_period_days: int | None = None,
    is_trial: bool | None = None,
    starts_at: str | None = None,
    expires_at: str | None = None,
    customer_id: str | None = None,
    email: str | None = None,
    phone_number: str | None = None,
    selected_fields: list[str] | None = None,
) -> dict:
    """subscription.expired - fires once when an ACTIVE subscription's
    expires_at passes without a renewal (app.subscriptions.service.
    expire_due_subscriptions, a Celery beat sweep - see celery_app.py's
    beat_schedule). Fixed payload: subscription_id only (2026-09
    follow-up 3) - every other parameter is an OPT-IN extra, see
    app.webhooks.field_catalog.AVAILABLE_FIELDS["subscription.expired"]."""
    return _plan_lifecycle_payload(
        event_type="subscription.expired",
        subscription_id=subscription_id,
        plan_code=plan_code,
        plan_name=plan_name,
        price=price,
        currency=currency,
        billing_interval=billing_interval,
        billing_frequency=billing_frequency,
        trial_period_days=trial_period_days,
        is_trial=is_trial,
        starts_at=starts_at,
        expires_at=expires_at,
        customer_id=customer_id,
        email=email,
        phone_number=phone_number,
        selected_fields=selected_fields,
    )


def archive_payload(
    *,
    subscription_id: str,
    plan_code: str | None = None,
    plan_name: str | None = None,
    price: float | None = None,
    currency: str | None = None,
    billing_interval: str | None = None,
    billing_frequency: int | None = None,
    trial_period_days: int | None = None,
    is_trial: bool | None = None,
    starts_at: str | None = None,
    expires_at: str | None = None,
    customer_id: str | None = None,
    email: str | None = None,
    phone_number: str | None = None,
    selected_fields: list[str] | None = None,
) -> dict:
    """subscription.archived - fires once an EXPIRED subscription has
    stayed unrenewed for at least the application's admin-configured
    archive_after_days (app.subscriptions.service.archive_stale_subscriptions,
    also a Celery beat sweep). Fixed payload: subscription_id only
    (2026-09 follow-up 3) - every other parameter is an OPT-IN extra, see
    app.webhooks.field_catalog.AVAILABLE_FIELDS["subscription.archived"]."""
    return _plan_lifecycle_payload(
        event_type="subscription.archived",
        subscription_id=subscription_id,
        plan_code=plan_code,
        plan_name=plan_name,
        price=price,
        currency=currency,
        billing_interval=billing_interval,
        billing_frequency=billing_frequency,
        trial_period_days=trial_period_days,
        is_trial=is_trial,
        starts_at=starts_at,
        expires_at=expires_at,
        customer_id=customer_id,
        email=email,
        phone_number=phone_number,
        selected_fields=selected_fields,
    )


def cancelled_payload(
    *,
    subscription_id: str,
    plan_code: str | None = None,
    plan_name: str | None = None,
    price: float | None = None,
    currency: str | None = None,
    billing_interval: str | None = None,
    billing_frequency: int | None = None,
    trial_period_days: int | None = None,
    is_trial: bool | None = None,
    starts_at: str | None = None,
    expires_at: str | None = None,
    customer_id: str | None = None,
    email: str | None = None,
    phone_number: str | None = None,
    cancelled_at: str | None = None,
    cancelled_by: str | None = None,
    cancellation_reason: str | None = None,
    selected_fields: list[str] | None = None,
) -> dict:
    """subscription.cancelled - fires once a customer (or an admin, via
    the Testing module) cancels a subscription immediately (spec section
    43: no refund, no future renewal) - see
    app.subscriptions.service.cancel_subscription. Fixed payload:
    subscription_id only (2026-09 follow-up 3) - every other parameter,
    including the three cancellation-specific ones that only exist on
    this event, is an OPT-IN extra, see app.webhooks.field_catalog.
    AVAILABLE_FIELDS["subscription.cancelled"]."""
    return _plan_lifecycle_payload(
        event_type="subscription.cancelled",
        subscription_id=subscription_id,
        plan_code=plan_code,
        plan_name=plan_name,
        price=price,
        currency=currency,
        billing_interval=billing_interval,
        billing_frequency=billing_frequency,
        trial_period_days=trial_period_days,
        is_trial=is_trial,
        starts_at=starts_at,
        expires_at=expires_at,
        customer_id=customer_id,
        email=email,
        phone_number=phone_number,
        selected_fields=selected_fields,
        extra_values={
            "cancelled_at": cancelled_at,
            "cancelled_by": cancelled_by,
            "cancellation_reason": cancellation_reason,
        },
    )


def _plan_change_payload(
    *,
    event_type: str,
    subscription_id: str,
    customer_id: str,
    plan_code: str,
    status: str,
    expires_at: str | None,
    transaction_id: str,
    plan_name: str | None,
    price: float | None,
    currency: str | None,
    billing_interval: str | None,
    billing_frequency: int | None,
    trial_period_days: int | None,
    is_trial: bool | None,
    starts_at: str | None,
    email: str | None,
    phone_number: str | None,
    payment_type: str | None,
    gateway: str | None,
    amount: float | None,
    invoice_id: str | None,
    total_amount: float | None,
    tax_amount: float | None,
    selected_fields: list[str] | None,
) -> dict:
    """Shared shape for subscription.upgraded/downgraded (identical
    fixed AND optional field lists - see field_catalog.AVAILABLE_FIELDS -
    the two only ever differ in event_type and which direction the plan
    change went). Fixed payload (unchanged from before this event type
    was brought into the configurable-fields system): subscription_id,
    customer_id, plan_code, status, expires_at, transaction_id."""
    fixed = {
        "subscription_id": subscription_id,
        "customer_id": customer_id,
        "plan_code": plan_code,
        "status": status,
        "expires_at": expires_at,
        "transaction_id": transaction_id,
    }
    optional_values = {
        "plan_name": plan_name,
        "price": price,
        "currency": currency,
        "billing_interval": billing_interval,
        "billing_frequency": billing_frequency,
        "trial_period_days": trial_period_days,
        "is_trial": is_trial,
        "starts_at": starts_at,
        "email": email,
        "phone_number": phone_number,
        "payment_type": payment_type,
        "gateway": gateway,
        "amount": amount,
        "invoice_id": invoice_id,
        "total_amount": total_amount,
        "tax_amount": tax_amount,
    }
    selected = _select_optional_fields(event_type=event_type, values=optional_values, selected_fields=selected_fields)
    return {**selected, **fixed}


def upgraded_payload(
    *,
    subscription_id: str,
    customer_id: str,
    plan_code: str,
    status: str,
    expires_at: str | None,
    transaction_id: str,
    plan_name: str | None = None,
    price: float | None = None,
    currency: str | None = None,
    billing_interval: str | None = None,
    billing_frequency: int | None = None,
    trial_period_days: int | None = None,
    is_trial: bool | None = None,
    starts_at: str | None = None,
    email: str | None = None,
    phone_number: str | None = None,
    payment_type: str | None = None,
    gateway: str | None = None,
    amount: float | None = None,
    invoice_id: str | None = None,
    total_amount: float | None = None,
    tax_amount: float | None = None,
    selected_fields: list[str] | None = None,
) -> dict:
    """subscription.upgraded - fires once a paid plan-change payment
    succeeds and the new plan costs MORE than the old one (
    app.payments.service.process_gateway_result, PaymentType.UPGRADE).
    2026-09-14 follow-up: brought into the same configurable-fields
    system as the other six events - see
    app.webhooks.field_catalog.AVAILABLE_FIELDS["subscription.upgraded"]
    for the full opt-in list."""
    return _plan_change_payload(
        event_type="subscription.upgraded",
        subscription_id=subscription_id,
        customer_id=customer_id,
        plan_code=plan_code,
        status=status,
        expires_at=expires_at,
        transaction_id=transaction_id,
        plan_name=plan_name,
        price=price,
        currency=currency,
        billing_interval=billing_interval,
        billing_frequency=billing_frequency,
        trial_period_days=trial_period_days,
        is_trial=is_trial,
        starts_at=starts_at,
        email=email,
        phone_number=phone_number,
        payment_type=payment_type,
        gateway=gateway,
        amount=amount,
        invoice_id=invoice_id,
        total_amount=total_amount,
        tax_amount=tax_amount,
        selected_fields=selected_fields,
    )


def downgraded_payload(
    *,
    subscription_id: str,
    customer_id: str,
    plan_code: str,
    status: str,
    expires_at: str | None,
    transaction_id: str,
    plan_name: str | None = None,
    price: float | None = None,
    currency: str | None = None,
    billing_interval: str | None = None,
    billing_frequency: int | None = None,
    trial_period_days: int | None = None,
    is_trial: bool | None = None,
    starts_at: str | None = None,
    email: str | None = None,
    phone_number: str | None = None,
    payment_type: str | None = None,
    gateway: str | None = None,
    amount: float | None = None,
    invoice_id: str | None = None,
    total_amount: float | None = None,
    tax_amount: float | None = None,
    selected_fields: list[str] | None = None,
) -> dict:
    """subscription.downgraded - fires once a paid plan-change payment
    succeeds and the new plan costs LESS than the old one (
    app.payments.service.process_gateway_result, PaymentType.DOWNGRADE).
    2026-09-14 follow-up: brought into the same configurable-fields
    system as the other six events - see
    app.webhooks.field_catalog.AVAILABLE_FIELDS["subscription.downgraded"]
    for the full opt-in list."""
    return _plan_change_payload(
        event_type="subscription.downgraded",
        subscription_id=subscription_id,
        customer_id=customer_id,
        plan_code=plan_code,
        status=status,
        expires_at=expires_at,
        transaction_id=transaction_id,
        plan_name=plan_name,
        price=price,
        currency=currency,
        billing_interval=billing_interval,
        billing_frequency=billing_frequency,
        trial_period_days=trial_period_days,
        is_trial=is_trial,
        starts_at=starts_at,
        email=email,
        phone_number=phone_number,
        payment_type=payment_type,
        gateway=gateway,
        amount=amount,
        invoice_id=invoice_id,
        total_amount=total_amount,
        tax_amount=tax_amount,
        selected_fields=selected_fields,
    )


def _sample_value_for_field(field) -> object:
    """Illustrative, obviously-fake example value for one registration
    field, type-appropriate so the onboarding sample below reads as real
    data rather than a wall of "string" placeholders."""
    if field.options:
        first = field.options[0]
        return first.get("value", first) if isinstance(first, dict) else first
    if field.field_type in ("number", "integer"):
        return 42
    if field.field_type in ("checkbox", "boolean"):
        return True
    if field.field_type == "email":
        return "sample@example.com"
    if field.placeholder:
        return field.placeholder
    return f"Sample {field.label}"


def build_webhook_samples(
    db: Session, application, *, selection_override: dict[str, list[str]] | None = None
) -> list:
    """Read-only preview of the exact JSON each of the seven real
    outbound webhook events sends (2026-09 follow-up: "Webhook for
    everyticket app are as below: 1) onboarding... 2) status inactive
    when plan expires... 3) delete/archive when user do not renew for x
    days"; follow-up 3: "Add one more webhook for renew"; upgraded/
    downgraded were already real events, brought into this same sample
    list in the 2026-09-14 configurable-fields follow-up). Registration-
    field keys are pulled from this application's real, currently-
    configured form (falling back to two generic example fields if none
    are configured yet), and plan_code/name/price come from a real active
    plan when one exists, so the onboarding sample reflects this
    application's actual setup rather than being entirely made up.

    Every sample also reflects this application's CURRENT
    webhook_field_selection (sanitized via field_catalog.sanitize_selection,
    so a stale/edited-away selection can never surface a field this
    catalog no longer knows about) - ticking a box on the Configuration
    screen updates the matching sample here too, since both go through
    the exact same payload-builder functions a real delivery uses.

    `selection_override` (2026-09-14 follow-up: "when select checkbox for
    parameters, it should reflect into sample JSON as well" - live, as
    the admin ticks boxes, not only after Save) lets a caller build the
    SAME samples against a DIFFERENT selection than the one actually
    stored on `application` - e.g. app.api.v1.admin_config also calls
    this once with every event mapped to its full AVAILABLE_FIELDS list,
    producing a "maximal" sample carrying every optional field's real
    sample value. The frontend then does its own live, no-round-trip
    preview by filtering that maximal payload down to whatever is
    currently ticked in the browser (unsaved or not) - it never
    reconstructs a payload's VALUES itself, only hides/shows keys this
    function already computed, so the "one source of truth" property
    below still holds: no sample value is ever invented in the frontend.
    None (the default) keeps today's behavior exactly - the application's
    own stored, sanitized selection.

    Used by BOTH the admin Configuration screen's read-only preview
    (app.api.v1.admin_config) and the admin Testing page's "Test
    Everyticket webhook" event dropdown (app.api.v1.admin_testing) - one
    shared function so the two can never quietly drift apart. Local
    imports avoid a circular import (app.applications.config_schemas and
    app.forms.models/app.plans.models don't need to know about this
    module; only this function needs them)."""
    from app.applications.config_schemas import EveryticketWebhookSampleOut
    from app.forms.models import RegistrationFormField
    from app.plans.models import Plan
    from app.webhooks.field_catalog import sanitize_selection
    from app.webhooks.service import build_wire_body

    now = datetime.now(timezone.utc)
    fields = (
        db.query(RegistrationFormField)
        .filter(RegistrationFormField.application_id == application.id, RegistrationFormField.active.is_(True))
        .order_by(RegistrationFormField.display_order)
        .all()
    )
    registration_data = (
        {f.field_key: _sample_value_for_field(f) for f in fields}
        if fields
        else {"organization_name": "Sample Museum", "contact_person": "Jane Doe"}
    )

    plan = (
        db.query(Plan)
        .filter(Plan.application_id == application.id, Plan.active.is_(True), Plan.is_trial.is_(False))
        .order_by(Plan.price)
        .first()
    )
    plan_code = plan.plan_code if plan else "PRO"
    plan_name = plan.name if plan else "Pro Plan"
    price = float(plan.price) if plan else 999.0
    currency = plan.currency if plan else "INR"
    billing_interval = plan.billing_interval if plan else "month"
    billing_frequency = plan.billing_frequency if plan else 1
    trial_period_days = plan.trial_period_days if plan and plan.is_trial else None

    selection = (
        sanitize_selection(selection_override)
        if selection_override is not None
        else sanitize_selection(application.webhook_field_selection)
    )
    sample_subscription_id = "SUB-000123"
    sample_starts_at = now.isoformat()
    sample_expires_at = (now + timedelta(days=30)).isoformat()

    onboarding = onboarding_payload(
        subscription_id=sample_subscription_id,
        email="customer@example.com",
        mobile="9999999999",
        plan_code=plan_code,
        plan_name=plan_name,
        price=price,
        is_trial=False,
        expires_at=sample_expires_at,
        registration_data=registration_data,
        currency=currency,
        billing_interval=billing_interval,
        billing_frequency=billing_frequency,
        trial_period_days=trial_period_days,
        starts_at=sample_starts_at,
        customer_id="CUS-000456",
        transaction_id="TXN-000789",
        payment_type="NEW",
        gateway="mock",
        invoice_id="INV-000111",
        total_amount=price,
        tax_amount=0.0,
        selected_fields=selection.get("subscription.activated"),
    )
    renewed = renewed_payload(
        subscription_id=sample_subscription_id,
        plan_code=plan_code,
        plan_name=plan_name,
        price=price,
        currency=currency,
        billing_interval=billing_interval,
        billing_frequency=billing_frequency,
        trial_period_days=trial_period_days,
        is_trial=False,
        starts_at=sample_starts_at,
        expires_at=sample_expires_at,
        customer_id="CUS-000456",
        email="customer@example.com",
        phone_number="9999999999",
        transaction_id="TXN-000790",
        payment_type="RENEWAL",
        amount=price,
        invoice_id="INV-000112",
        total_amount=price,
        selected_fields=selection.get("subscription.renewed"),
    )
    expired = expiry_payload(
        subscription_id=sample_subscription_id,
        plan_code=plan_code,
        plan_name=plan_name,
        price=price,
        currency=currency,
        billing_interval=billing_interval,
        billing_frequency=billing_frequency,
        trial_period_days=trial_period_days,
        is_trial=False,
        starts_at=sample_starts_at,
        expires_at=sample_expires_at,
        customer_id="CUS-000456",
        email="customer@example.com",
        phone_number="9999999999",
        selected_fields=selection.get("subscription.expired"),
    )
    cancelled = cancelled_payload(
        subscription_id=sample_subscription_id,
        plan_code=plan_code,
        plan_name=plan_name,
        price=price,
        currency=currency,
        billing_interval=billing_interval,
        billing_frequency=billing_frequency,
        trial_period_days=trial_period_days,
        is_trial=False,
        starts_at=sample_starts_at,
        expires_at=sample_expires_at,
        customer_id="CUS-000456",
        email="customer@example.com",
        phone_number="9999999999",
        cancelled_at=now.isoformat(),
        cancelled_by="customer@example.com",
        cancellation_reason="No longer needed",
        selected_fields=selection.get("subscription.cancelled"),
    )
    archived = archive_payload(
        subscription_id=sample_subscription_id,
        plan_code=plan_code,
        plan_name=plan_name,
        price=price,
        currency=currency,
        billing_interval=billing_interval,
        billing_frequency=billing_frequency,
        trial_period_days=trial_period_days,
        is_trial=False,
        starts_at=sample_starts_at,
        expires_at=sample_expires_at,
        customer_id="CUS-000456",
        email="customer@example.com",
        phone_number="9999999999",
        selected_fields=selection.get("subscription.archived"),
    )
    upgraded = upgraded_payload(
        subscription_id=sample_subscription_id,
        customer_id="CUS-000456",
        plan_code=plan_code,
        status="ACTIVE",
        expires_at=sample_expires_at,
        transaction_id="TXN-000791",
        plan_name=plan_name,
        price=price,
        currency=currency,
        billing_interval=billing_interval,
        billing_frequency=billing_frequency,
        trial_period_days=trial_period_days,
        is_trial=False,
        starts_at=sample_starts_at,
        email="customer@example.com",
        phone_number="9999999999",
        payment_type="UPGRADE",
        gateway="mock",
        amount=price,
        invoice_id="INV-000113",
        total_amount=price,
        tax_amount=0.0,
        selected_fields=selection.get("subscription.upgraded"),
    )
    downgraded = downgraded_payload(
        subscription_id=sample_subscription_id,
        customer_id="CUS-000456",
        plan_code=plan_code,
        status="ACTIVE",
        expires_at=sample_expires_at,
        transaction_id="TXN-000792",
        plan_name=plan_name,
        price=price,
        currency=currency,
        billing_interval=billing_interval,
        billing_frequency=billing_frequency,
        trial_period_days=trial_period_days,
        is_trial=False,
        starts_at=sample_starts_at,
        email="customer@example.com",
        phone_number="9999999999",
        payment_type="DOWNGRADE",
        gateway="mock",
        amount=price,
        invoice_id="INV-000114",
        total_amount=price,
        tax_amount=0.0,
        selected_fields=selection.get("subscription.downgraded"),
    )

    # Wrapped via the SAME build_wire_body() a real delivery uses (see
    # app.webhooks.service._attempt_one) - just {event_type, payload}, so
    # the preview below is the literal JSON body Everyticket's endpoint
    # would receive, not just the inner event data.
    events = [
        ("subscription.activated", onboarding, "Onboarding: fires once, the first time a new customer's payment succeeds."),
        ("subscription.renewed", renewed, "Renew: fires once an existing subscription's renewal payment succeeds."),
        ("subscription.upgraded", upgraded, "Upgrade: fires once a plan-change payment succeeds moving to a higher-priced plan."),
        ("subscription.downgraded", downgraded, "Downgrade: fires once a plan-change payment succeeds moving to a lower-priced plan."),
        ("subscription.expired", expired, "Status inactive: fires once when an active subscription's plan expires unrenewed."),
        ("subscription.cancelled", cancelled, "Cancel: fires once a customer cancels their subscription immediately."),
        (
            "subscription.archived",
            archived,
            "Delete/archive: fires once an expired subscription has stayed unrenewed past the Archive after "
            "threshold below (disabled until that field is set).",
        ),
    ]
    return [
        EveryticketWebhookSampleOut(
            event=event_type,
            trigger=trigger,
            payload=build_wire_body(event_type=event_type, payload=event_payload),
        )
        for event_type, event_payload, trigger in events
    ]
