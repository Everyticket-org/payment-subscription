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
        code=overrides.get("code", "TESTAPP"),
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


def test_dispatch_pending_captures_request_and_response_headers_on_success(db_session):
    app_row = _application(db_session)
    webhook_service.queue_event(
        db_session, application=app_row, event_type="subscription.activated",
        entity_type="subscription", entity_id="SUB-HDRS-OK", payload={"x": 1},
    )
    db_session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"received": True}, headers={"X-Custom-Marker": "abc123"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    webhook_service.dispatch_pending(db_session, http_client=client)

    delivery = db_session.query(WebhookDelivery).one()
    # Request headers: what this app actually sent - signature included
    # since the application has a secret configured.
    assert delivery.request_headers["Content-Type"] == "application/json"
    assert delivery.request_headers["X-Webhook-Signature"].startswith("sha256=")
    # Response headers: httpx normalizes header names to lowercase.
    assert delivery.response_headers["x-custom-marker"] == "abc123"


def test_dispatch_pending_records_call_time_and_duration(db_session):
    """Vishal: "Log webhook call time and response completion time" -
    attempt_started_at/duration_ms should be populated on a real attempt,
    with started_at strictly before (or equal to, under a fast mock
    transport) the existing last_attempt_at completion timestamp."""
    app_row = _application(db_session)
    webhook_service.queue_event(
        db_session, application=app_row, event_type="subscription.activated",
        entity_type="subscription", entity_id="SUB-TIMING-1", payload={"x": 1},
    )
    db_session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"received": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    webhook_service.dispatch_pending(db_session, http_client=client)

    delivery = db_session.query(WebhookDelivery).one()
    assert delivery.attempt_started_at is not None
    assert delivery.duration_ms is not None
    assert delivery.duration_ms >= 0
    assert delivery.attempt_started_at <= delivery.last_attempt_at


def test_dispatch_pending_leaves_response_headers_null_on_connection_error(db_session):
    app_row = _application(db_session)
    webhook_service.queue_event(
        db_session, application=app_row, event_type="subscription.activated",
        entity_type="subscription", entity_id="SUB-HDRS-ERR", payload={},
    )
    db_session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    webhook_service.dispatch_pending(db_session, http_client=client)

    delivery = db_session.query(WebhookDelivery).one()
    # The request was still built and sent (headers known before the
    # attempt), even though no response ever came back.
    assert delivery.request_headers is not None
    assert delivery.request_headers["X-Webhook-Signature"].startswith("sha256=")
    assert delivery.response_headers is None


def test_dispatch_pending_captures_request_body_sent(db_session):
    """Vishal: "Show request data as well where currently showing
    response data only" - the exact wire body (the {event_type, payload}
    envelope build_wire_body() constructs) must be persisted on the
    delivery row, not just the response."""
    app_row = _application(db_session)
    webhook_service.queue_event(
        db_session, application=app_row, event_type="subscription.activated",
        entity_type="subscription", entity_id="SUB-REQBODY", payload={"plan_code": "PRO"},
    )
    db_session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"received": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    webhook_service.dispatch_pending(db_session, http_client=client)

    delivery = db_session.query(WebhookDelivery).one()
    assert delivery.request_body is not None
    assert '"event_type":"subscription.activated"' in delivery.request_body
    assert '"plan_code":"PRO"' in delivery.request_body


def test_queue_event_stores_customer_reference(db_session):
    """Vishal: "Keep reference of why that webhook called and show in
    logs - like for which customer it has been called."""
    app_row = _application(db_session)
    event = webhook_service.queue_event(
        db_session, application=app_row, event_type="subscription.activated",
        entity_type="subscription", entity_id="SUB-CUSTREF", payload={},
        customer_reference="CUS-ABC123",
    )
    db_session.commit()

    assert event.customer_reference == "CUS-ABC123"
    delivery = db_session.query(WebhookDelivery).filter(WebhookDelivery.webhook_event_id == event.id).one()
    # Proxied straight from the parent event via a model @property, so a
    # flat delivery row already carries its own event context.
    assert delivery.customer_reference == "CUS-ABC123"
    assert delivery.event_type == "subscription.activated"
    assert delivery.entity_type == "subscription"
    assert delivery.entity_id == "SUB-CUSTREF"


def test_queue_event_customer_reference_defaults_to_none(db_session):
    """Synthetic/test events (e.g. the admin webhook failure simulator)
    have no real customer to reference - must stay None, not error."""
    app_row = _application(db_session)
    event = webhook_service.queue_event(
        db_session, application=app_row, event_type="test.webhook_failure_simulation",
        entity_type="test", entity_id="TEST-SIM-1", payload={},
    )
    db_session.commit()
    assert event.customer_reference is None


def test_json_status_fail_marks_delivery_failed_despite_http_200(db_session):
    """Vishal: "Any response with JSON, check status - if 'fail' then
    trigger 'Escalation on failure' email." A 2xx HTTP response whose JSON
    body reports {"status": "fail"} must be treated as a failed delivery
    (scheduled for retry), not a success - this is a generic check across
    every event type, unlike the activation-only success:false
    convention."""
    app_row = _application(db_session)
    webhook_service.queue_event(
        db_session, application=app_row, event_type="subscription.renewed",
        entity_type="subscription", entity_id="SUB-JSONFAIL", payload={},
    )
    db_session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "fail", "reason": "unknown customer"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    webhook_service.dispatch_pending(db_session, http_client=client)

    delivery = db_session.query(WebhookDelivery).one()
    assert delivery.http_status == 200
    assert delivery.status == WebhookDeliveryStatus.FAILED.value
    assert delivery.next_retry_at is not None


def test_json_status_fail_is_case_insensitive_and_ignores_non_matching_bodies(db_session):
    app_row = _application(db_session)
    webhook_service.queue_event(
        db_session, application=app_row, event_type="subscription.renewed",
        entity_type="subscription", entity_id="SUB-JSONFAIL-CASE", payload={},
    )
    db_session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "FAIL"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    webhook_service.dispatch_pending(db_session, http_client=client)

    delivery = db_session.query(WebhookDelivery).one()
    assert delivery.status == WebhookDeliveryStatus.FAILED.value


def test_json_status_ok_or_non_json_body_still_succeeds(db_session):
    app_row = _application(db_session)
    webhook_service.queue_event(
        db_session, application=app_row, event_type="subscription.renewed",
        entity_type="subscription", entity_id="SUB-JSONOK", payload={},
    )
    db_session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    webhook_service.dispatch_pending(db_session, http_client=client)

    delivery = db_session.query(WebhookDelivery).one()
    assert delivery.status == WebhookDeliveryStatus.SUCCESS.value

    # A non-JSON (plain text) 2xx body must never be treated as a failure
    # either - only a JSON object with status=="fail" counts.
    app_row2 = _application(db_session, code="TESTAPP-PLAINTEXT", webhook_url="http://localhost:9999/webhooks-2")
    webhook_service.queue_event(
        db_session, application=app_row2, event_type="subscription.renewed",
        entity_type="subscription", entity_id="SUB-PLAINTEXT", payload={},
    )
    db_session.commit()

    def handler2(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="OK")

    client2 = httpx.Client(transport=httpx.MockTransport(handler2))
    webhook_service.dispatch_pending(db_session, http_client=client2)

    delivery2 = db_session.query(WebhookDelivery).filter(WebhookDelivery.destination_url.like("%webhooks-2")).one()
    assert delivery2.status == WebhookDeliveryStatus.SUCCESS.value


_REAL_HTTPX_CLIENT = httpx.Client


def _mock_client_factory(handler):
    """Stands in for app.webhooks.service's internal `httpx.Client(...)`
    construction inside send_ad_hoc_webhook(), which - unlike
    dispatch_pending()/attempt_delivery_with_client() - takes no
    injectable http_client parameter (it always owns a short-lived
    client of its own). Monkeypatching the module's `httpx.Client`
    reference is the only way to run it against a MockTransport instead
    of real network - note this patches the httpx module itself (the
    same object app.webhooks.service imported), so the factory must call
    the real class captured above rather than `httpx.Client` again, or
    it recurses into itself."""

    def factory(*, timeout=None, **kwargs):
        return _REAL_HTTPX_CLIENT(transport=httpx.MockTransport(handler), timeout=timeout)

    return factory


def test_send_ad_hoc_webhook_includes_response_headers_on_success(db_session, monkeypatch):
    app_row = _application(db_session, webhook_url="http://mock-destination.invalid/hook")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ok", headers={"X-Reply-Marker": "pong"})

    monkeypatch.setattr(webhook_service.httpx, "Client", _mock_client_factory(handler))

    result = webhook_service.send_ad_hoc_webhook(application=app_row, payload={"ping": True})

    assert result["sent"] is True
    assert result["response_headers"]["x-reply-marker"] == "pong"
    assert result["request"]["headers"]["X-Webhook-Signature"].startswith("sha256=")


def test_record_ad_hoc_delivery_persists_request_and_response_headers(db_session, monkeypatch):
    app_row = _application(db_session, webhook_url="http://mock-destination.invalid/hook")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ok", headers={"X-Reply-Marker": "pong"})

    monkeypatch.setattr(webhook_service.httpx, "Client", _mock_client_factory(handler))

    result = webhook_service.send_ad_hoc_webhook(application=app_row, payload={"ping": True})
    delivery = webhook_service.record_ad_hoc_delivery(
        db_session,
        application=app_row,
        event_type="webhook.connectivity_check",
        entity_id="VERIFY-TEST1",
        payload={"ping": True},
        result=result,
    )
    db_session.commit()

    assert delivery is not None
    assert delivery.request_headers["X-Webhook-Signature"].startswith("sha256=")
    assert delivery.response_headers["x-reply-marker"] == "pong"


def test_send_ad_hoc_webhook_and_record_ad_hoc_delivery_capture_call_timing(db_session, monkeypatch):
    """Vishal: "Log webhook call time and response completion time" -
    covers the ad-hoc/Verify connectivity path (send_ad_hoc_webhook's own
    return dict, and what record_ad_hoc_delivery persists from it), as a
    complement to the real-dispatch-path timing test above."""
    app_row = _application(db_session, webhook_url="http://mock-destination.invalid/hook")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ok")

    monkeypatch.setattr(webhook_service.httpx, "Client", _mock_client_factory(handler))

    result = webhook_service.send_ad_hoc_webhook(application=app_row, payload={"ping": True})
    assert result["started_at"] is not None
    assert result["elapsed_ms"] is not None

    delivery = webhook_service.record_ad_hoc_delivery(
        db_session,
        application=app_row,
        event_type="webhook.connectivity_check",
        entity_id="VERIFY-TIMING-1",
        payload={"ping": True},
        result=result,
    )
    db_session.commit()

    assert delivery is not None
    assert delivery.attempt_started_at is not None
    assert delivery.duration_ms is not None
    assert delivery.attempt_started_at <= delivery.last_attempt_at


def test_record_ad_hoc_delivery_returns_none_when_no_destination_configured(db_session, monkeypatch):
    # app.webhook_url=None alone isn't enough - _resolve_destination()
    # falls back to settings.EVERYTICKET_WEBHOOK_URL, which itself
    # defaults to a non-empty value (app/core/config.py), so the
    # fallback must be cleared too to actually exercise "no destination
    # configured at all".
    monkeypatch.setenv("EVERYTICKET_WEBHOOK_URL", "")
    get_settings.cache_clear()
    try:
        app_row = _application(db_session, webhook_url=None)
        app_row.webhook_url = None
        db_session.flush()

        result = webhook_service.send_ad_hoc_webhook(application=app_row, payload={"ping": True})
        assert "request" not in result  # no destination -> never attempted

        delivery = webhook_service.record_ad_hoc_delivery(
            db_session,
            application=app_row,
            event_type="webhook.connectivity_check",
            entity_id="VERIFY-TEST2",
            payload={"ping": True},
            result=result,
        )
        assert delivery is None
    finally:
        get_settings.cache_clear()
