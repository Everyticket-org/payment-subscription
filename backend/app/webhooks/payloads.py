"""
Pure payload-shaping functions for the three real outbound Everyticket
webhook events (2026-09 follow-up - admin Configuration > Everyticket
Integration should document exactly what each event sends, per Vishal's
own numbered list):

  1. onboarding_payload - subscription.activated, first-time signup.
  2. expiry_payload - subscription.expired, plan expires unrenewed.
  3. archive_payload - subscription.archived, still unrenewed after the
     admin-configured archive_after_days window.

Deliberately built from primitives, not ORM objects, so the exact same
function that shapes a REAL delivery's payload (app.payments.service /
app.subscriptions.service) also shapes the admin Configuration screen's
read-only "sample JSON" preview (app.api.v1.admin_config) - one source
of truth, so the documentation can never quietly drift from what's
actually sent over the wire.
"""


def onboarding_payload(
    *,
    subscription_id: str,
    customer_id: str,
    email: str | None,
    mobile: str | None,
    plan_code: str,
    plan_name: str,
    currency: str,
    price: float,
    is_trial: bool,
    status: str,
    starts_at: str | None,
    expires_at: str | None,
    transaction_id: str,
    registration_data: dict,
) -> dict:
    """subscription.activated - fires exactly once, the moment a NEW
    subscription's payment succeeds (never on renew/upgrade/downgrade -
    see app.payments.service.process_gateway_result's payment_type
    branch, which routes those three to their own event_type instead).
    Carries every registration-form answer the customer submitted at
    signup (registration_data - see app.customers.models.
    CustomerRegistrationData) so Everyticket can provision the account
    without a second round-trip to ask for the same details.

    Deliberately no external_customer_id/external_instance_id here:
    Everyticket's own response to THIS delivery is what assigns those
    (spec section 32) - see app.webhooks.service._handle_activation_outcome,
    which upserts CustomerApplicationMapping from that response."""
    return {
        "event": "subscription.activated",
        "subscription_id": subscription_id,
        "customer_id": customer_id,
        "email": email,
        "mobile": mobile,
        "plan_code": plan_code,
        "plan_name": plan_name,
        "currency": currency,
        "price": price,
        "is_trial": is_trial,
        "status": status,
        "starts_at": starts_at,
        "expires_at": expires_at,
        "transaction_id": transaction_id,
        "registration_data": registration_data,
    }


def expiry_payload(
    *,
    subscription_id: str,
    customer_id: str,
    external_customer_id: str | None,
    external_instance_id: str | None,
    plan_code: str,
    status: str,
    expired_at: str | None,
) -> dict:
    """subscription.expired - fires once when an ACTIVE subscription's
    expires_at passes without a renewal (app.subscriptions.service.
    expire_due_subscriptions, a Celery beat sweep - see celery_app.py's
    beat_schedule). Carries external_customer_id/external_instance_id -
    the identity Everyticket itself returned back on onboarding - so
    Everyticket can deactivate the RIGHT account without having to look
    it up by our internal customer_id, which means nothing on their
    side."""
    return {
        "event": "subscription.expired",
        "subscription_id": subscription_id,
        "customer_id": customer_id,
        "external_customer_id": external_customer_id,
        "external_instance_id": external_instance_id,
        "plan_code": plan_code,
        "status": status,
        "expired_at": expired_at,
    }


def archive_payload(
    *,
    subscription_id: str,
    customer_id: str,
    external_customer_id: str | None,
    external_instance_id: str | None,
    plan_code: str,
    status: str,
    expired_at: str | None,
    days_since_expiry: int,
) -> dict:
    """subscription.archived - fires once an EXPIRED subscription has
    stayed unrenewed for at least the application's admin-configured
    archive_after_days (app.subscriptions.service.archive_stale_subscriptions,
    also a Celery beat sweep). Same identity fields as expiry_payload -
    "delete/archive when user does not renew for x days" needs the same
    external identity to act on."""
    return {
        "event": "subscription.archived",
        "subscription_id": subscription_id,
        "customer_id": customer_id,
        "external_customer_id": external_customer_id,
        "external_instance_id": external_instance_id,
        "plan_code": plan_code,
        "status": status,
        "expired_at": expired_at,
        "days_since_expiry": days_since_expiry,
    }
