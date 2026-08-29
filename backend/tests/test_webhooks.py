"""
Unit tests for outbound webhook queuing + dispatch (spec sections 34-37).
No Celery/real network involved anywhere here - queue_event() is a pure
DB write, and dispatch_pending() is exercised with an httpx.MockTransport
standing in for the real destination, exactly the pattern
app/webhooks/service.py's own docstring describes as the point of
splitting queue/dispatch into two phases.
"""
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.applications.models import Application
from app.core.config import get_settings
from app.core.time import ensure_aware
from app.core.enums import WebhookDeliveryStatus
from app.webhooks import service as webhook_service
from app.webhooks.models import WebhookDelivery, WebhookEvent


def _application(db_session, **overrides):
    app_row = Application(
        code="TESTAPP",
        name="Test App",
        application_url="http://localhost:9999",
        webhook_url=overrides.get("webhook_url", "http://localhost:9999/webhooks"),
        webhook_secret=overrides.get("webhook_secret", "test-secret"),
    )
    db_session.add(app_row)
    db_session.flush()
    return app_row


def test_queue_event_creates_pending_delivery(db_session):
    app_row = _application(db_session)
    event = webhook_service.queue_event(
        db_session,
        application=app_row,
        event_type="subscription.activated",
        entity_type="subscription",
        entity_id="SUB-TEST1",
        payload={"foo": "bar"},
    )
    db_session.commit()

    assert event is not None
    delivery = db_session.query(WebhookDelivery).filter(WebhookDelivery.webhook_event_id == event.id).one()
    assert delivery.status == WebhookDeliveryStatus.PENDING.value
    assert delivery.destination_url == "http://localhost:9999/webhooks"
    assert delivery.attempt_count == 0


def test_queue_event_falls_back_to_everyticket_webhook_url_setting(db_session, monkeypatch):
    monkeypatch.setenv("EVERYTICKET_WEBHOOK_URL", "http://fallback.example/webhooks")
    get_settings.cache_clear()
    app_row = _application(db_session, webhook_url=None)
    app_row.webhook_url = None
    db_session.flush()

    event = webhook_service.queue_event(
        db_session, application=app_row, event_type="subscription.activated",
        entity_type="subscription", entity_id="SUB-TEST2", payload={},
    )
    db_session.commit()
    get_settings.cache_clear()

    delivery = db_session.query(WebhookDelivery).filter(WebhookDelivery.webhook_event_id == event.id).one()
    assert delivery.destination_url == "http://fallback.example/webhooks"


def test_dispatch_pending_marks_success_on_2xx(db_session):
    app_row = _application(db_session)
    webhook_service.queue_event(
        db_session, application=app_row, event_type="subscription.activated",
        entity_type="subscription", entity_id="SUB-OK", payload={"x": 1},
    )
    db_session.commit()

    seen_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(200, json={"received": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    attempted = webhook_service.dispatch_pending(db_session, http_client=client)

    assert attempted == 1
    assert len(seen_requests) == 1
    # HMAC signature header present since the application has a secret.
    assert seen_requests[0].headers["X-Webhook-Signature"].startswith("sha256=")

    delivery = db_session.query(WebhookDelivery).one()
    assert delivery.status == WebhookDeliveryStatus.SUCCESS.value
    assert delivery.attempt_count == 1
    assert delivery.next_retry_at is None
    assert delivery.http_status == 200


def test_dispatch_pending_schedules_retry_on_failure(db_session):
    app_row = _application(db_session)
    webhook_service.queue_event(
        db_session, application=app_row, event_type="subscription.activated",
        entity_type="subscription", entity_id="SUB-FAIL", payload={},
    )
    db_session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    webhook_service.dispatch_pending(db_session, http_client=client)

    delivery = db_session.query(WebhookDelivery).one()
    assert delivery.status == WebhookDeliveryStatus.FAILED.value
    assert delivery.attempt_count == 1
    # First retry step per the default WEBHOOK_RETRY_SCHEDULE_MINUTES=5,...
    assert delivery.next_retry_at is not None
    # SQLite (this test DB) round-trips DateTime(timezone=True) columns as
    # naive even though they were stored aware - same pre-existing quirk
    # app/core/time.ensure_aware() exists for elsewhere in this codebase.
    assert ensure_aware(delivery.next_retry_at) > datetime.now(timezone.utc) + timedelta(minutes=4)


def test_dispatch_pending_exhausts_after_schedule_runs_out(db_session):
    app_row = _application(db_session)
    webhook_service.queue_event(
        db_session, application=app_row, event_type="subscription.activated",
        entity_type="subscription", entity_id="SUB-EXHAUST", payload={},
    )
    db_session.commit()
    delivery = db_session.query(WebhookDelivery).one()
    schedule_len = len(get_settings().webhook_retry_schedule)
    delivery.attempt_count = schedule_len  # simulate every retry already used
    delivery.status = WebhookDeliveryStatus.FAILED.value
    delivery.next_retry_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db_session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="still failing")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    webhook_service.dispatch_pending(db_session, http_client=client)

    db_session.refresh(delivery)
    assert delivery.status == WebhookDeliveryStatus.EXHAUSTED.value
    assert delivery.next_retry_at is None


def test_dispatch_pending_ignores_deliveries_not_yet_due(db_session):
    app_row = _application(db_session)
    webhook_service.queue_event(
        db_session, application=app_row, event_type="subscription.activated",
        entity_type="subscription", entity_id="SUB-FUTURE", payload={},
    )
    db_session.commit()
    delivery = db_session.query(WebhookDelivery).one()
    delivery.next_retry_at = datetime.now(timezone.utc) + timedelta(hours=1)
    db_session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not be called - delivery isn't due yet")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    attempted = webhook_service.dispatch_pending(db_session, http_client=client)
    assert attempted == 0
