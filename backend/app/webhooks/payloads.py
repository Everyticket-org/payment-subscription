"""
Pure payload-shaping functions for the five real outbound Everyticket
webhook events (2026-09 follow-up 3 - Vishal's own numbered list:
"Add one more webhook for renew"; trimmed every payload down to exactly
the fields he listed, and simplified the wire envelope to just
event_type + payload):

  1. onboarding_payload  - subscription.activated, first-time signup.
     Payload: subscription_id, email, phone_number, plan_code, plan_name,
     price, is_trial, expires_at, plus every registration-form answer
     merged in FLAT at the top level (2026-09-11 follow-up: "Keep the
     key for email and phone number as below shown in JSON... Pass
     payload like this flat structure including registration form
     data.." - registration_data used to be nested under its own key;
     it is now spread directly alongside the other fields instead, and
     the phone number's wire key changed from "mobile" to
     "phone_number" - the Customer model's own column is still called
     mobile, only the outbound JSON key name changed).
  2. renewed_payload  - subscription.renewed, an existing subscription
     is renewed on its current plan. Payload: subscription_id only.
  3. expiry_payload   - subscription.expired, plan expires unrenewed.
     Payload: subscription_id only.
  4. cancelled_payload - subscription.cancelled, a customer cancels.
     Payload: subscription_id only.
  5. archive_payload  - subscription.archived, still unrenewed after the
     admin-configured archive_after_days window. Payload: subscription_id
     only.

Deliberately built from primitives, not ORM objects, so the exact same
function that shapes a REAL delivery's payload (app.payments.service /
app.subscriptions.service) also shapes the admin Configuration screen's
read-only "sample JSON" preview (app.api.v1.admin_config) - one source
of truth, so the documentation can never quietly drift from what's
actually sent over the wire. The wire envelope itself (event_type +
payload) is built by app.webhooks.service.build_wire_body().
"""


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

    Still no customer_id or external identity here - trimmed to exactly
    the fields Vishal asked to keep. Everyticket's own response to THIS
    delivery is what assigns the external identity (spec section 32) -
    see app.webhooks.service._handle_activation_outcome, which upserts
    CustomerApplicationMapping from that response."""
    return {
        **registration_data,
        "subscription_id": subscription_id,
        "email": email,
        "phone_number": mobile,
        "plan_code": plan_code,
        "plan_name": plan_name,
        "price": price,
        "is_trial": is_trial,
        "expires_at": expires_at,
    }


def _subscription_id_only_payload(subscription_id: str) -> dict:
    """Shared shape for every lifecycle event Vishal asked to trim down
    to just the subscription identifier - renew, expire, cancel, archive
    all resolve everything else about the subscription by looking it up
    with this ID, rather than carrying a snapshot of fields that can go
    stale between when the event is queued and when Everyticket reads
    it."""
    return {"subscription_id": subscription_id}


def renewed_payload(*, subscription_id: str) -> dict:
    """subscription.renewed - fires once an existing subscription's
    RENEWAL payment succeeds (app.payments.service.process_gateway_result),
    extending expires_at on the same plan."""
    return _subscription_id_only_payload(subscription_id)


def expiry_payload(*, subscription_id: str) -> dict:
    """subscription.expired - fires once when an ACTIVE subscription's
    expires_at passes without a renewal (app.subscriptions.service.
    expire_due_subscriptions, a Celery beat sweep - see celery_app.py's
    beat_schedule)."""
    return _subscription_id_only_payload(subscription_id)


def cancelled_payload(*, subscription_id: str) -> dict:
    """subscription.cancelled - fires once a customer (or an admin, via
    the Testing module) cancels a subscription immediately (spec section
    43: no refund, no future renewal) - see
    app.subscriptions.service.cancel_subscription."""
    return _subscription_id_only_payload(subscription_id)


def archive_payload(*, subscription_id: str) -> dict:
    """subscription.archived - fires once an EXPIRED subscription has
    stayed unrenewed for at least the application's admin-configured
    archive_after_days (app.subscriptions.service.archive_stale_subscriptions,
    also a Celery beat sweep)."""
    return _subscription_id_only_payload(subscription_id)
