"""
The three real outbound Everyticket webhook events + their payload
shapes (2026-09 follow-up: "Webhook for everyticket app are as below:
1) onboarding... 2) status inactive when plan expires... 3) delete/
archive when user do not renew for x days"):

  - subscription.activated ("onboarding") now carries the customer's full
    registration-form answers, not just bare identifiers.
  - subscription.expired ("status inactive") now carries the external
    customer/instance identity Everyticket itself assigned at onboarding.
  - subscription.archived ("delete/archive after x days") is an entirely
    new sweep (app.subscriptions.service.archive_stale_subscriptions),
    opt-in per application via Application.archive_after_days.

Also covers app.webhooks.service.build_wire_body(), the pure function
that wraps a queued event's payload into the exact JSON body a real
delivery sends (event envelope + admin-configured extra_params merged
in) - the same function app.api.v1.admin_config's "sample JSON" preview
calls, so these tests indirectly protect that preview from drifting too.
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


def _configure_webhook_destination(db) -> Application:
    application, _plan = _basic_plan(db)
    application.webhook_url = "http://everyticket.example.com/hooks"
    db.add(application)
    db.flush()
    return application


def test_onboarding_webhook_carries_full_registration_data(client, seeded_db):
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
    assert event.payload["registration_data"] == registration_data
    assert event.payload["customer_id"] == subscription.customer.customer_id
    assert event.payload["plan_code"] == subscription.plan.plan_code
    assert event.payload["status"] == "ACTIVE"
    # Never present at queue-time - Everyticket's own response to this
    # delivery is what assigns it (see app.webhooks.service._handle_activation_outcome).
    assert "external_customer_id" not in event.payload


def test_onboarding_webhook_registration_data_defaults_to_empty_dict_when_none_submitted(client, seeded_db):
    _configure_webhook_destination(seeded_db)
    subscription = _subscribe_with_registration_data(
        client, seeded_db, email="onboarding-nodata@museum.example", registration_data={}
    )
    event = (
        seeded_db.query(WebhookEvent)
        .filter(WebhookEvent.event_type == "subscription.activated", WebhookEvent.entity_id == subscription.subscription_id)
        .one()
    )
    assert event.payload["registration_data"] == {}


def test_expiry_webhook_carries_external_identity_once_onboarding_provisioned(client, seeded_db):
    application = _configure_webhook_destination(seeded_db)
    subscription = _subscribe_with_registration_data(
        client, seeded_db, email="expiry-identity@museum.example", registration_data={}
    )

    # Simulate Everyticket's own successful response to the onboarding
    # webhook, which is what assigns the external identity (same pattern
    # tests/test_provisioning.py establishes).
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
    assert event.payload["external_customer_id"] == "MUSEUM-9001"
    assert event.payload["external_instance_id"] == "INSTANCE-9001"


def test_expiry_webhook_identity_fields_are_none_when_never_provisioned(client, seeded_db):
    _configure_webhook_destination(seeded_db)
    subscription = _subscribe_with_registration_data(
        client, seeded_db, email="expiry-noidentity@museum.example", registration_data={}
    )
    subscription.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    seeded_db.commit()

    subscription_service.expire_due_subscriptions(seeded_db)

    event = (
        seeded_db.query(WebhookEvent)
        .filter(WebhookEvent.event_type == "subscription.expired", WebhookEvent.entity_id == subscription.subscription_id)
        .one()
    )
    assert event.payload["external_customer_id"] is None
    assert event.payload["external_instance_id"] is None


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
    assert event.payload["external_customer_id"] == "MUSEUM-7001"
    assert event.payload["external_instance_id"] == "INSTANCE-7001"
    assert event.payload["days_since_expiry"] >= 40
    assert event.payload["status"] == "ARCHIVED"

    # Idempotent: running the sweep again must not re-archive/re-queue.
    again = subscription_service.archive_stale_subscriptions(seeded_db)
    assert again == 0
    events = seeded_db.query(WebhookEvent).filter(WebhookEvent.event_type == "subscription.archived").all()
    assert len(events) == 1


def test_build_wire_body_merges_extra_params_without_overriding_envelope_fields(seeded_db):
    application, _plan = _basic_plan(seeded_db)
    application.webhook_extra_params = {"merchant_id": "MERCH-1", "event_type": "should-not-win"}
    seeded_db.commit()

    body = webhook_service.build_wire_body(
        event_id="EVT-1",
        event_type="subscription.activated",
        entity_type="subscription",
        entity_id="SUB-1",
        payload={"subscription_id": "SUB-1"},
        application=application,
    )
    assert body["event_type"] == "subscription.activated"  # extra_params never overrides a fixed envelope field
    assert body["merchant_id"] == "MERCH-1"
    assert body["payload"] == {"subscription_id": "SUB-1"}
