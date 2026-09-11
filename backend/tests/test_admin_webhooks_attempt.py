"""
Admin Webhook Logs "Attempt" button (spec sections 34-37, 51; added per
Vishal: "provide attempt button for each webhook log so we can try again
from there. verify connectivity button get success for same API of
webhook but webhook called from payment success to everyticket does not
show response and show pending only. please review it properly").

POST /api/v1/admin/webhooks/deliveries/{id}/attempt makes one real,
synchronous delivery attempt right now, instead of only ever resetting
the row to PENDING for the Celery beat schedule to eventually pick up
(that's still all /retry does - see admin_webhooks.py's module
docstring for the full root-cause explanation of why a real payment's
subscription.activated delivery can otherwise sit at PENDING with no
response indefinitely). Like /verify, this hits the real
httpx.Client(...) construction inside webhook_service._attempt_one() -
there's no http_client injection point reachable from an HTTP request,
so these tests monkeypatch webhook_service.httpx.Client the same way
tests/test_webhooks.py's send_ad_hoc_webhook tests do.
"""
import httpx

from app.applications.models import Application
from app.core.enums import WebhookDeliveryStatus
from app.webhooks import service as webhook_service
from app.webhooks.models import WebhookDelivery, WebhookEvent

from tests.test_admin_api import _admin_headers

_REAL_HTTPX_CLIENT = httpx.Client


def _mock_client_factory(handler):
    """See tests/test_webhooks.py's _mock_client_factory for why this
    captures the real class first rather than referencing httpx.Client
    again inside factory() - webhook_service.httpx IS the same httpx
    module object, so patching its Client attribute in place would
    otherwise make the replacement recurse into itself."""

    def factory(*, timeout=None, **kwargs):
        return _REAL_HTTPX_CLIENT(transport=httpx.MockTransport(handler), timeout=timeout)

    return factory


def _queue_a_delivery(db_session, *, webhook_url="http://mock-destination.invalid/hook", event_type="subscription.activated", entity_type="subscription", entity_id="SUB-ATTEMPT1"):
    app_row = Application(
        code="ATTEMPTAPP",
        name="Attempt Test App",
        application_url="http://localhost:9999",
        webhook_url=webhook_url,
        webhook_secret="test-secret",
    )
    db_session.add(app_row)
    db_session.flush()

    event = webhook_service.queue_event(
        db_session,
        application=app_row,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        payload={"subscription_id": entity_id},
    )
    db_session.commit()
    delivery = db_session.query(WebhookDelivery).filter(WebhookDelivery.webhook_event_id == event.id).one()
    return app_row, event, delivery


def test_attempt_delivery_makes_a_real_call_and_returns_the_updated_result(client, seeded_db, db_session, monkeypatch):
    """The core regression case Vishal described: a delivery that was
    only ever queued (PENDING, http_status/response_body both null,
    exactly what dispatch_pending() would otherwise leave it at forever
    without a running Celery beat) gets a real, populated response the
    moment an admin clicks Attempt - it does not just flip back to
    PENDING the way /retry does."""
    headers = _admin_headers(client)
    _app_row, _event, delivery = _queue_a_delivery(db_session, entity_type="other", entity_id="ATTEMPT-1")
    assert delivery.http_status is None
    assert delivery.response_body is None

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text='{"ok":true}', headers={"X-Reply-Marker": "pong"})

    monkeypatch.setattr(webhook_service.httpx, "Client", _mock_client_factory(handler))

    resp = client.post(f"/api/v1/admin/webhooks/deliveries/{delivery.id}/attempt", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == WebhookDeliveryStatus.SUCCESS.value
    assert body["http_status"] == 200
    assert body["response_body"] == '{"ok":true}'
    assert body["response_headers"]["x-reply-marker"] == "pong"
    assert body["request_headers"]["X-Webhook-Signature"].startswith("sha256=")
    assert body["attempt_count"] == 1
    assert body["next_retry_at"] is None


def test_attempt_delivery_records_a_real_failure_instead_of_staying_blank(client, seeded_db, db_session, monkeypatch):
    headers = _admin_headers(client)
    _app_row, _event, delivery = _queue_a_delivery(db_session, entity_type="other", entity_id="ATTEMPT-2")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal error")

    monkeypatch.setattr(webhook_service.httpx, "Client", _mock_client_factory(handler))

    resp = client.post(f"/api/v1/admin/webhooks/deliveries/{delivery.id}/attempt", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == WebhookDeliveryStatus.FAILED.value
    assert body["http_status"] == 500
    assert body["attempt_count"] == 1
    assert body["next_retry_at"] is not None


def test_attempt_delivery_requires_webhooks_manage_permission(client, seeded_db, db_session):
    from app.auth import service as auth_service

    _app_row, _event, delivery = _queue_a_delivery(db_session, entity_type="other", entity_id="ATTEMPT-3")

    auth_service.create_admin_user(
        db_session, email="limited-attempt@example.com", full_name="Limited Admin", password="LimitedPass123!", mfa_enabled=False
    )
    db_session.commit()
    login = client.post(
        "/api/v1/admin/auth/login", json={"email": "limited-attempt@example.com", "password": "LimitedPass123!"}
    )
    limited_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = client.post(f"/api/v1/admin/webhooks/deliveries/{delivery.id}/attempt", headers=limited_headers)
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "FORBIDDEN"


def test_attempt_delivery_refuses_to_reattempt_an_already_succeeded_delivery(client, seeded_db, db_session):
    headers = _admin_headers(client)
    _app_row, _event, delivery = _queue_a_delivery(db_session, entity_type="other", entity_id="ATTEMPT-4")
    delivery.status = WebhookDeliveryStatus.SUCCESS.value
    db_session.add(delivery)
    db_session.commit()

    resp = client.post(f"/api/v1/admin/webhooks/deliveries/{delivery.id}/attempt", headers=headers)
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "WEBHOOK_ALREADY_DELIVERED"


def test_attempt_delivery_unknown_id_returns_404(client, seeded_db):
    headers = _admin_headers(client)
    resp = client.post("/api/v1/admin/webhooks/deliveries/999999/attempt", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "WEBHOOK_DELIVERY_NOT_FOUND"


def test_attempt_delivery_audit_logs_the_attempt(client, seeded_db, db_session, monkeypatch):
    headers = _admin_headers(client)
    _app_row, _event, delivery = _queue_a_delivery(db_session, entity_type="other", entity_id="ATTEMPT-5")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ok")

    monkeypatch.setattr(webhook_service.httpx, "Client", _mock_client_factory(handler))

    resp = client.post(f"/api/v1/admin/webhooks/deliveries/{delivery.id}/attempt", headers=headers)
    assert resp.status_code == 200, resp.text

    logs = client.get(
        "/api/v1/admin/audit-logs", params={"action": "WEBHOOK_DELIVERY_ATTEMPTED"}, headers=headers
    )
    assert logs.status_code == 200, logs.text
    assert len(logs.json()["items"]) >= 1
