"""
The five real outbound Everyticket webhook events + their trimmed
payload shapes (2026-09 follow-up: "Webhook for everyticket app are as
below: 1) onboarding... 2) status inactive when plan expires... 3)
delete/archive when user do not renew for x days"; follow-up 3: "Add
one more webhook for renew" plus an explicit trim of every payload):

  - subscription.activated ("onboarding") carries subscription_id,
    email, phone_number, plan code/name/price, is_trial, expires_at,
    and the customer's full registration-form answers spread FLAT at
    the top level (not nested under a "registration_data" key) - the
    fields Vishal's follow-up 3 list asked to keep, email/phone_number
    re-added in a follow-up ("customer data also need to be there"),
    and flattened + the mobile number's wire key renamed from "mobile"
    to "phone_number" in a further follow-up ("Keep the key for email
    and phone number as below shown in JSON... Pass payload like this
    flat structure including registration form data..").
  - subscription.renewed / subscription.expired / subscription.cancelled
    / subscription.archived all carry subscription_id ONLY - Everyticket
    resolves anything else about the subscription by looking it up with
    that ID.

Also covers app.webhooks.service.build_wire_body(), the pure function
that wraps a queued event's payload into the exact JSON body a real
delivery sends - now just {event_type, payload}, nothing else (follow-up
3: "Keep only event_type" at the top level; the custom extra_params
merge feature was removed in the same pass) - the same function
app.api.v1.admin_config's "sample JSON" preview calls, so these tests
indirectly protect that preview from drifting too.
"""
from datetime import datetime, timedelta, timezone

import httpx

from app.applications.models import Application, CustomerApplicationMapping
from app.core.enums import SubscriptionStatus
from app.subscriptions import service as subscription_service
from app.subscriptions.models import Subscription
from app.webhooks import service as webhook_service
from app.webhooks.models import WebhookEvent

from tests.test_invoices import _basic_plan


def _subscribe_with_registration_data(client, seeded_db, *, email: str, registration_data: dict) -> Subscription:
    resp = client.post(
        "/api/v1/public/plans/basic/subscribe",
        json={"email": email, "mobile": "9812345671", "registration_data": registration_data},
    )
    assert resp.status_code == 200, resp.text
    transaction_id = resp.json()["payment"]["transaction_id"]
    subscription_id = resp.json()["subscription"]["subscription_id"]

    callback = client.post(
        "/api/v1/payment/mock/callback", json={"transaction_id": transaction_id, "scenario": "SUCCESS"}
    )
    assert callback.status_code == 200, callback.text

    return seeded_db.query(Subscription).filter(Subscription.subscription_id == subscription_id).one()


def _customer_token(client, email: str, mobile: str) -> str:
    identify = client.post("/api/v1/public/identify", json={"email": email, "mobile": mobile})
    otp_session_id = identify.json()["otp_session_id"]
    verify = client.post("/api/v1/public/otp/verify", json={"otp_session_id": otp_session_id, "code": "BYPASS"})
    return verify.json()["access_token"]


def _configure_webhook_destination(db) -> Application:
    application, _plan = _basic_plan(db)
    application.webhook_url = "http://everyticket.example.com/hooks"
    db.add(application)
    db.flush()
    return application


def test_onboarding_webhook_payload_has_exactly_the_fields_vishal_asked_to_keep(client, seeded_db):
    _configure_webhook_destination(seeded_db)
    registration_data = {"museum_name": "CSMVS", "contact_person": "Asha Rao"}
    subscription = _subscribe_with_registration_data(
        client, seeded_db, email="onboarding-data@museum.example", registration_data=registration_data
    )

    event = (
        seeded_db.query(WebhookEvent)
        .filter(WebhookEvent.event_type == "subscription.activated", WebhookEvent.entity_id == subscription.subscription_id)
        .one()
    )
    # Subscription ID, customer identity (email/phone_number), plan
    # code, name, price, is_trial, expiry date, and every registration
    # form answer spread flat at the top level (not nested under a
    # "registration_data" key) - exactly these keys, nothing more (no
    # customer_id/currency/status/starts_at/transaction_id/external
    # identity).
    assert set(event.payload) == {
        "subscription_id",
        "email",
        "phone_number",
        "plan_code",
        "plan_name",
        "price",
        "is_trial",
        "expires_at",
        *registration_data.keys(),
    }
    assert event.payload["subscription_id"] == subscription.subscription_id
    assert event.payload["email"] == subscription.customer.email
    assert event.payload["phone_number"] == subscription.customer.mobile
    assert event.payload["museum_name"] == "CSMVS"
    assert event.payload["contact_person"] == "Asha Rao"
    assert "registration_data" not in event.payload
    assert event.payload["plan_code"] == subscription.plan.plan_code
    assert event.payload["is_trial"] is False


def test_onboarding_webhook_adds_no_extra_keys_when_no_registration_data_submitted(client, seeded_db):
    _configure_webhook_destination(seeded_db)
    subscription = _subscribe_with_registration_data(
        client, seeded_db, email="onboarding-nodata@museum.example", registration_data={}
    )
    event = (
        seeded_db.query(WebhookEvent)
        .filter(WebhookEvent.event_type == "subscription.activated", WebhookEvent.entity_id == subscription.subscription_id)
        .one()
    )
    assert set(event.payload) == {
        "subscription_id",
        "email",
        "phone_number",
        "plan_code",
        "plan_name",
        "price",
        "is_trial",
        "expires_at",
    }


def test_onboarding_webhook_fixed_fields_win_over_a_colliding_registration_form_key(client, seeded_db):
    """A registration form field_key can technically collide with one of
    the fixed identity/plan fields (e.g. an admin names a custom field
    "email"). The fixed field must always win, since it's the account-
    level identity Everyticket relies on - a customer-editable form
    answer must never be able to silently override it."""
    _configure_webhook_destination(seeded_db)
    subscription = _subscribe_with_registration_data(
        client, seeded_db, email="onboarding-collision@museum.example",
        registration_data={"email": "attacker-supplied@example.com", "plan_code": "FORGED"},
    )
    event = (
        seeded_db.query(WebhookEvent)
        .filter(WebhookEvent.event_type == "subscription.activated", WebhookEvent.entity_id == subscription.subscription_id)
        .one()
    )
    assert event.payload["email"] == subscription.customer.email
    assert event.payload["plan_code"] == subscription.plan.plan_code


def test_renewed_webhook_payload_is_subscription_id_only(client, seeded_db):
    _configure_webhook_destination(seeded_db)
    subscription = _subscribe_with_registration_data(
        client, seeded_db, email="renew-webhook@museum.example", registration_data={}
    )
    token = _customer_token(client, "renew-webhook@museum.example", "9812345671")
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(f"/api/v1/customer/subscriptions/{subscription.subscription_id}/renew", headers=headers)
    assert resp.status_code == 200, resp.text
    txn = resp.json()["payment"]["transaction_id"]
    callback = client.post("/api/v1/payment/mock/callback", json={"transaction_id": txn, "scenario": "SUCCESS"})
    assert callback.status_code == 200, callback.text

    event = (
        seeded_db.query(WebhookEvent)
        .filter(WebhookEvent.event_type == "subscription.renewed", WebhookEvent.entity_id == subscription.subscription_id)
        .one()
    )
    assert event.payload == {"subscription_id": subscription.subscription_id}


def test_expiry_webhook_payload_is_subscription_id_only(client, seeded_db):
    application = _configure_webhook_destination(seeded_db)
    subscription = _subscribe_with_registration_data(
        client, seeded_db, email="expiry-webhook@museum.example", registration_data={}
    )

    # Simulate Everyticket's own successful response to the onboarding
    # webhook (real provisioning still happens - CustomerApplicationMapping
    # is upserted from Everyticket's response, unaffected by the payload
    # trim, which only concerns what THIS app sends out).
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True, "external_customer_id": "MUSEUM-9001", "instance_id": "INSTANCE-9001"})

    webhook_service.dispatch_pending(seeded_db, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    mapping = (
        seeded_db.query(CustomerApplicationMapping)
        .filter(CustomerApplicationMapping.customer_id == subscription.customer_id, CustomerApplicationMapping.application_id == application.id)
        .one()
    )
    assert mapping.external_customer_id == "MUSEUM-9001"

    seeded_db.refresh(subscription)
    subscription.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    seeded_db.commit()

    expired_count = subscription_service.expire_due_subscriptions(seeded_db)
    assert expired_count == 1

    event = (
        seeded_db.query(WebhookEvent)
        .filter(WebhookEvent.event_type == "subscription.expired", WebhookEvent.entity_id == subscription.subscription_id)
        .one()
    )
    assert event.payload == {"subscription_id": subscription.subscription_id}


def test_cancelled_webhook_payload_is_subscription_id_only(client, seeded_db):
    _configure_webhook_destination(seeded_db)
    subscription = _subscribe_with_registration_data(
        client, seeded_db, email="cancel-webhook@museum.example", registration_data={}
    )
    token = _customer_token(client, "cancel-webhook@museum.example", "9812345671")
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        f"/api/v1/customer/subscriptions/{subscription.subscription_id}/cancel",
        json={"reason": "no longer needed"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    event = (
        seeded_db.query(WebhookEvent)
        .filter(WebhookEvent.event_type == "subscription.cancelled", WebhookEvent.entity_id == subscription.subscription_id)
        .one()
    )
    assert event.payload == {"subscription_id": subscription.subscription_id}


def test_archive_sweep_is_disabled_by_default(client, seeded_db):
    """archive_after_days is None on a freshly-seeded application -
    archiving must never happen unless an admin opts in."""
    _configure_webhook_destination(seeded_db)
    subscription = _subscribe_with_registration_data(client, seeded_db, email="archive-disabled@museum.example", registration_data={})
    subscription.status = SubscriptionStatus.EXPIRED.value
    seeded_db.commit()

    archived_count = subscription_service.archive_stale_subscriptions(seeded_db)
    assert archived_count == 0
    seeded_db.refresh(subscription)
    assert subscription.status == SubscriptionStatus.EXPIRED.value


def _expire_and_backdate(db, subscription, *, days_ago: int) -> None:
    """expire_due_subscriptions() always stamps SubscriptionHistory's
    EXPIRED row with "now" (it runs shortly after the real expiry, same
    as a real periodic sweep would) - to test archive_stale_subscriptions'
    day-threshold math, backdate that row the same way a subscription
    that actually expired `days_ago` days ago would have it, rather than
    only backdating expires_at (which expire_due_subscriptions itself
    doesn't read for the history timestamp)."""
    from app.subscriptions.models import SubscriptionHistory

    subscription.expires_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    db.commit()
    subscription_service.expire_due_subscriptions(db)
    history = (
        db.query(SubscriptionHistory)
        .filter(SubscriptionHistory.subscription_id == subscription.id, SubscriptionHistory.event_type == "expired")
        .one()
    )
    history.occurred_at = datetime.now(timezone.utc) - timedelta(days=days_ago)
    db.commit()


def test_archive_sweep_ignores_subscriptions_not_yet_past_the_threshold(client, seeded_db):
    application = _configure_webhook_destination(seeded_db)
    application.archive_after_days = 30
    seeded_db.commit()

    subscription = _subscribe_with_registration_data(client, seeded_db, email="archive-tooearly@museum.example", registration_data={})
    _expire_and_backdate(seeded_db, subscription, days_ago=10)

    archived_count = subscription_service.archive_stale_subscriptions(seeded_db)
    assert archived_count == 0
    seeded_db.refresh(subscription)
    assert subscription.status == SubscriptionStatus.EXPIRED.value


def test_archive_sweep_archives_past_threshold_and_queues_webhook(client, seeded_db):
    application = _configure_webhook_destination(seeded_db)
    application.archive_after_days = 30
    seeded_db.commit()

    subscription = _subscribe_with_registration_data(client, seeded_db, email="archive-due@museum.example", registration_data={})

    # Simulate onboarding having provisioned successfully, then the
    # subscription having expired 40 days ago - past the 30-day threshold.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True, "external_customer_id": "MUSEUM-7001", "instance_id": "INSTANCE-7001"})

    webhook_service.dispatch_pending(seeded_db, http_client=httpx.Client(transport=httpx.MockTransport(handler)))

    seeded_db.refresh(subscription)
    _expire_and_backdate(seeded_db, subscription, days_ago=40)

    archived_count = subscription_service.archive_stale_subscriptions(seeded_db)
    assert archived_count == 1

    seeded_db.refresh(subscription)
    assert subscription.status == SubscriptionStatus.ARCHIVED.value
    assert any(h.event_type == "archived" for h in subscription.history)

    event = (
        seeded_db.query(WebhookEvent)
        .filter(WebhookEvent.event_type == "subscription.archived", WebhookEvent.entity_id == subscription.subscription_id)
        .one()
    )
    assert event.payload == {"subscription_id": subscription.subscription_id}

    # Idempotent: running the sweep again must not re-archive/re-queue.
    again = subscription_service.archive_stale_subscriptions(seeded_db)
    assert again == 0
    events = seeded_db.query(WebhookEvent).filter(WebhookEvent.event_type == "subscription.archived").all()
    assert len(events) == 1


def test_build_wire_body_is_just_event_type_and_payload(seeded_db):
    body = webhook_service.build_wire_body(
        event_type="subscription.activated",
        payload={"subscription_id": "SUB-1"},
    )
    assert body == {"event_type": "subscription.activated", "payload": {"subscription_id": "SUB-1"}}
