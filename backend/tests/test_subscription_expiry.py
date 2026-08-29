"""
Subscription expiry sweep (spec section 40) + its webhook side-effect
(spec sections 19, 31). Drives the same public API the existing e2e
tests use to get a real ACTIVE subscription, then exercises the sweep
function directly - no Celery involved (see
app/subscriptions/tasks.py's docstring for why the task itself is just a
thin wrapper around this).
"""
from datetime import datetime, timedelta, timezone

from app.core.enums import SubscriptionStatus
from app.subscriptions import service as subscription_service
from app.subscriptions.models import Subscription
from app.webhooks.models import WebhookDelivery, WebhookEvent


def _activate_a_subscription(client, seeded_db, email="expiry-test@museum.example") -> Subscription:
    resp = client.post(
        "/api/v1/public/plans/basic/subscribe",
        json={"email": email, "mobile": "9812345670", "registration_data": {}},
    )
    assert resp.status_code == 200, resp.text
    transaction_id = resp.json()["payment"]["transaction_id"]
    subscription_id = resp.json()["subscription"]["subscription_id"]

    callback = client.post(
        "/api/v1/payment/mock/callback", json={"transaction_id": transaction_id, "scenario": "SUCCESS"}
    )
    assert callback.status_code == 200, callback.text

    return seeded_db.query(Subscription).filter(Subscription.subscription_id == subscription_id).one()


def test_expire_due_subscriptions_flips_status_and_queues_webhook(client, seeded_db):
    subscription = _activate_a_subscription(client, seeded_db)
    assert subscription.status == SubscriptionStatus.ACTIVE.value

    # Force it into the past - a real subscription would get here by time
    # passing, not by being created in the past.
    subscription.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    seeded_db.commit()

    expired_count = subscription_service.expire_due_subscriptions(seeded_db)
    assert expired_count == 1

    seeded_db.refresh(subscription)
    assert subscription.status == SubscriptionStatus.EXPIRED.value
    assert any(h.event_type == "expired" for h in subscription.history)

    events = seeded_db.query(WebhookEvent).filter(WebhookEvent.event_type == "subscription.expired").all()
    assert len(events) == 1
    assert events[0].entity_id == subscription.subscription_id
    delivery = seeded_db.query(WebhookDelivery).filter(WebhookDelivery.webhook_event_id == events[0].id).one()
    assert delivery.status == "PENDING"


def test_expire_due_subscriptions_ignores_subscriptions_not_yet_expired(client, seeded_db):
    subscription = _activate_a_subscription(client, seeded_db, email="not-expired@museum.example")
    subscription.expires_at = datetime.now(timezone.utc) + timedelta(days=10)
    seeded_db.commit()

    expired_count = subscription_service.expire_due_subscriptions(seeded_db)
    assert expired_count == 0

    seeded_db.refresh(subscription)
    assert subscription.status == SubscriptionStatus.ACTIVE.value


def test_successful_payment_queues_activation_webhook(client, seeded_db):
    subscription = _activate_a_subscription(client, seeded_db, email="webhook-on-activate@museum.example")
    events = (
        seeded_db.query(WebhookEvent)
        .filter(WebhookEvent.event_type == "subscription.activated", WebhookEvent.entity_id == subscription.subscription_id)
        .all()
    )
    assert len(events) == 1
