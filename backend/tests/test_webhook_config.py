"""
2026-09 admin config restructure, Everyticket Integration screen: custom
key/value POST parameters sent with every webhook delivery, an admin-
configurable retry limit overriding WEBHOOK_RETRY_SCHEDULE_MINUTES' own
length, and an escalation email sent once a delivery is EXHAUSTED. Same
no-real-network testing approach as tests/test_webhooks.py (httpx.
MockTransport standing in for the real destination).
"""
from datetime import datetime, timedelta, timezone

import httpx

from app.applications.models import Application
from app.core.enums import WebhookDeliveryStatus
from app.webhooks import service as webhook_service
from app.webhooks.models import WebhookDelivery

from tests.test_email_service import fake_smtp_success


def _application(db_session, **overrides):
    app_row = Application(
        code="TESTAPP2",
        name="Test App 2",
        application_url="http://localhost:9999",
        webhook_url=overrides.get("webhook_url", "http://localhost:9999/webhooks"),
        webhook_secret=overrides.get("webhook_secret", "test-secret"),
        webhook_extra_params=overrides.get("webhook_extra_params"),
        webhook_retry_limit=overrides.get("webhook_retry_limit"),
        webhook_escalation_emails=overrides.get("webhook_escalation_emails"),
        webhook_escalation_email_subject=overrides.get("webhook_escalation_email_subject"),
        webhook_escalation_email_body=overrides.get("webhook_escalation_email_body"),
    )
    db_session.add(app_row)
    db_session.flush()
    return app_row


def test_extra_params_merged_into_outgoing_body(db_session):
    app_row = _application(db_session, webhook_extra_params={"merchant_id": "MERCH-1", "source": "everyticket-subs"})
    webhook_service.queue_event(
        db_session, application=app_row, event_type="subscription.activated",
        entity_type="subscription", entity_id="SUB-PARAMS", payload={"foo": "bar"},
    )
    db_session.commit()

    seen_bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen_bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"received": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    webhook_service.dispatch_pending(db_session, http_client=client)

    assert len(seen_bodies) == 1
    body = seen_bodies[0]
    assert body["merchant_id"] == "MERCH-1"
    assert body["source"] == "everyticket-subs"
    # The event's own fields are never overridden by an extra param sharing
    # the same key - not exercised by name collision here, but the fixed
    # fields must still be present regardless.
    assert body["event_type"] == "subscription.activated"
    assert body["entity_id"] == "SUB-PARAMS"


def test_configured_retry_limit_shorter_than_schedule_exhausts_sooner(db_session):
    # Default schedule has 5 entries (conftest's WEBHOOK_RETRY_SCHEDULE_MINUTES).
    # retry_limit=1 means only 1 retry is ever scheduled after the first
    # failure (2 attempts total before EXHAUSTED), instead of 5. Simulates
    # "the one allowed retry already happened" the same way
    # tests/test_webhooks.py's own exhaustion test simulates the full
    # schedule running out - by presetting attempt_count/next_retry_at
    # directly, rather than actually waiting/re-dispatching through time.
    app_row = _application(db_session, webhook_retry_limit=1)
    webhook_service.queue_event(
        db_session, application=app_row, event_type="subscription.activated",
        entity_type="subscription", entity_id="SUB-SHORTLIMIT", payload={},
    )
    db_session.commit()
    delivery = db_session.query(WebhookDelivery).one()
    delivery.attempt_count = 1  # the one retry_limit=1 allows has already been consumed
    delivery.status = WebhookDeliveryStatus.FAILED.value
    delivery.next_retry_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    webhook_service.dispatch_pending(db_session, http_client=client)

    db_session.refresh(delivery)
    assert delivery.status == WebhookDeliveryStatus.EXHAUSTED.value
    assert delivery.attempt_count == 2
    assert delivery.next_retry_at is None


def test_escalation_email_sent_once_delivery_becomes_exhausted(db_session, fake_smtp_success):
    app_row = _application(
        db_session,
        webhook_retry_limit=1,
        webhook_escalation_emails="ops@example.com, billing@example.com",
        webhook_escalation_email_subject="Webhook down for {{ event_type }}",
        webhook_escalation_email_body="<p>Failed after {{ attempt_count }} attempts hitting {{ destination_url }}.</p>",
    )
    webhook_service.queue_event(
        db_session, application=app_row, event_type="subscription.activated",
        entity_type="subscription", entity_id="SUB-ESCALATE", payload={},
    )
    db_session.commit()
    delivery = db_session.query(WebhookDelivery).one()
    delivery.attempt_count = 1
    delivery.status = WebhookDeliveryStatus.FAILED.value
    delivery.next_retry_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    webhook_service.dispatch_pending(db_session, http_client=client)

    db_session.refresh(delivery)
    assert delivery.status == WebhookDeliveryStatus.EXHAUSTED.value

    # One email per configured recipient, rendered with the real event context.
    assert len(fake_smtp_success) == 2
    recipients = {to_addrs[0] for _from, to_addrs, _message in fake_smtp_success}
    assert recipients == {"ops@example.com", "billing@example.com"}
    _from, _to, message = fake_smtp_success[0]
    assert "Webhook down for subscription.activated" in message
    assert "SUB-ESCALATE" not in message  # entity_id isn't in the body template used here - attempt_count/url are
    assert "Failed after 2 attempts" in message


def test_escalation_email_not_sent_when_no_recipients_configured(db_session, fake_smtp_success):
    app_row = _application(db_session, webhook_retry_limit=1)  # no webhook_escalation_emails set
    webhook_service.queue_event(
        db_session, application=app_row, event_type="subscription.activated",
        entity_type="subscription", entity_id="SUB-NOESCALATE", payload={},
    )
    db_session.commit()
    delivery = db_session.query(WebhookDelivery).one()
    delivery.attempt_count = 1
    delivery.status = WebhookDeliveryStatus.FAILED.value
    delivery.next_retry_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    webhook_service.dispatch_pending(db_session, http_client=client)

    db_session.refresh(delivery)
    assert delivery.status == WebhookDeliveryStatus.EXHAUSTED.value
    assert len(fake_smtp_success) == 0


def test_escalation_email_only_fires_once_not_on_every_later_dispatch(db_session, fake_smtp_success):
    # Once a delivery is EXHAUSTED, dispatch_pending() never picks it back
    # up (it only re-attempts PENDING/FAILED rows) - so a second manual
    # dispatch_pending() call must not send a second escalation email.
    app_row = _application(db_session, webhook_retry_limit=1, webhook_escalation_emails="ops@example.com")
    webhook_service.queue_event(
        db_session, application=app_row, event_type="subscription.activated",
        entity_type="subscription", entity_id="SUB-ONCE", payload={},
    )
    db_session.commit()
    delivery = db_session.query(WebhookDelivery).one()
    delivery.attempt_count = 1
    delivery.status = WebhookDeliveryStatus.FAILED.value
    delivery.next_retry_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    webhook_service.dispatch_pending(db_session, http_client=client)
    webhook_service.dispatch_pending(db_session, http_client=client)  # no-op: nothing due any more (now EXHAUSTED)

    assert len(fake_smtp_success) == 1
