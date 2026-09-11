"""
webhook_service.attempt_soon() (2026-09-11 follow-up: Vishal reported
"webhook called from payment success to everyticket does not show
response and show pending only" - "why its not being called properly on
payment success").

Before this existed, a real business event's very first delivery
attempt depended entirely on the Celery beat schedule (app/core/
celery_app.py) eventually invoking dispatch_pending() - if that
background process wasn't running (the default for a plain `uvicorn`
run per this repo's own README), a queued delivery sat at PENDING with
no response forever. attempt_soon() is called right after the enclosing
transaction commits (see app/payments/service.py) and makes one real,
immediate attempt in a background thread with its own DB session -
Celery beat remains the only thing that ever retries a FAILED delivery.

Tested with threading.Thread patched to run its target synchronously
(deterministic - no sleep/poll for a real background thread to finish)
and SessionLocal patched to hand back this test's own db_session.
attempt_soon() normally opens a brand-new session via
app.core.database.SessionLocal - deliberately NOT the request-scoped
session tests override via the `client`/`db_session` fixtures, since it
is designed to run outside any request's session or transaction -
patching it here is only what lets a test observe the result
synchronously against the same in-memory test database, without a
second real one.
"""
import httpx

from app.applications.models import Application
from app.core.enums import WebhookDeliveryStatus
from app.webhooks import service as webhook_service
from app.webhooks.models import WebhookDelivery, WebhookEvent

from tests.test_invoices import _basic_plan


class _SyncThread:
    """Stands in for threading.Thread: runs target(*args, **kwargs)
    immediately in the calling thread when .start() is called, instead
    of a real background one."""

    def __init__(self, *, target, args=(), kwargs=None, daemon=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)


class _FakeThreadingModule:
    Thread = _SyncThread


def _application(db_session, webhook_url="http://mock-destination.invalid/hook"):
    app_row = Application(
        code="ATTEMPTSOONAPP",
        name="Attempt Soon Test App",
        application_url="http://localhost:9999",
        webhook_url=webhook_url,
        webhook_secret="test-secret",
    )
    db_session.add(app_row)
    db_session.flush()
    return app_row


def _patch_for_sync_attempt(monkeypatch, db_session, handler):
    """Makes attempt_soon() run its background work synchronously,
    against this test's own db_session, over a MockTransport instead of
    real network - see module docstring for why each patch is needed."""
    monkeypatch.setattr(webhook_service, "threading", _FakeThreadingModule)
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(webhook_service, "SessionLocal", lambda: db_session)

    real_client = httpx.Client

    def factory(*, timeout=None, **kwargs):
        return real_client(transport=httpx.MockTransport(handler), timeout=timeout)

    monkeypatch.setattr(webhook_service.httpx, "Client", factory)


def test_attempt_soon_makes_a_real_attempt_right_after_being_called(db_session, monkeypatch):
    app_row = _application(db_session)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ok")

    _patch_for_sync_attempt(monkeypatch, db_session, handler)

    event = webhook_service.queue_event(
        db_session,
        application=app_row,
        event_type="subscription.renewed",
        entity_type="other",
        entity_id="ATTEMPT-SOON-1",
        payload={"subscription_id": "ATTEMPT-SOON-1"},
    )
    db_session.commit()
    delivery = db_session.query(WebhookDelivery).filter(WebhookDelivery.webhook_event_id == event.id).one()
    assert delivery.status == WebhookDeliveryStatus.PENDING.value
    assert delivery.http_status is None

    webhook_service.attempt_soon(event.event_id)

    db_session.refresh(delivery)
    assert delivery.status == WebhookDeliveryStatus.SUCCESS.value
    assert delivery.http_status == 200


def test_attempt_soon_records_a_real_failure_instead_of_leaving_it_blank(db_session, monkeypatch):
    app_row = _application(db_session)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="nope")

    _patch_for_sync_attempt(monkeypatch, db_session, handler)

    event = webhook_service.queue_event(
        db_session,
        application=app_row,
        event_type="subscription.renewed",
        entity_type="other",
        entity_id="ATTEMPT-SOON-2",
        payload={"subscription_id": "ATTEMPT-SOON-2"},
    )
    db_session.commit()
    delivery = db_session.query(WebhookDelivery).filter(WebhookDelivery.webhook_event_id == event.id).one()

    webhook_service.attempt_soon(event.event_id)

    db_session.refresh(delivery)
    assert delivery.status == WebhookDeliveryStatus.FAILED.value
    assert delivery.http_status == 500
    assert delivery.next_retry_at is not None


def test_attempt_soon_is_a_no_op_for_a_none_event_id(monkeypatch):
    # queue_event() returns None when no destination is configured at all
    # (nowhere to send it) - attempt_soon() must tolerate that silently
    # rather than trying to spawn a thread for a nonexistent event.
    spawned = []
    monkeypatch.setattr(
        webhook_service,
        "threading",
        type("_T", (), {"Thread": staticmethod(lambda *a, **k: spawned.append(1))}),
    )
    webhook_service.attempt_soon(None)
    assert spawned == []


def test_attempt_soon_swallows_an_unknown_event_id(db_session, monkeypatch):
    _patch_for_sync_attempt(monkeypatch, db_session, handler=lambda request: httpx.Response(200))
    # Must never raise, even though this event id doesn't exist - the
    # background worker is best-effort by design (see its own docstring).
    webhook_service.attempt_soon("no-such-event-id")



def test_payment_success_triggers_attempt_soon_for_the_queued_activation_event(client, seeded_db, monkeypatch):
    """Integration-level regression test for the exact bug Vishal
    reported ("webhook called from payment success to everyticket does
    not show response and show pending only"): PaymentService.
    process_gateway_result() must itself call webhook_service.
    attempt_soon() with the real, just-queued activation event's id
    right after a payment succeeds - not leave the delivery waiting on
    the Celery beat schedule alone. Patches attempt_soon() itself
    (rather than exercising the real background thread/HTTP call here -
    that's what test_webhook_attempt_soon.py's other tests already cover
    directly) purely to observe that the wiring calls it with the right
    event id, at the right time (after the real subscribe + mock-payment
    round trip through the actual API, not a unit-level call)."""
    application, _plan = _basic_plan(seeded_db)
    application.webhook_url = "http://everyticket.example.com/hooks"
    seeded_db.add(application)
    seeded_db.flush()
    seeded_db.commit()

    calls = []
    monkeypatch.setattr(webhook_service, "attempt_soon", lambda event_id: calls.append(event_id))

    resp = client.post(
        "/api/v1/public/plans/basic/subscribe",
        json={"email": "attemptsoon@example.com", "mobile": "9812345672", "registration_data": {}},
    )
    assert resp.status_code == 200, resp.text
    transaction_id = resp.json()["payment"]["transaction_id"]
    subscription_id = resp.json()["subscription"]["subscription_id"]

    callback = client.post(
        "/api/v1/payment/mock/callback", json={"transaction_id": transaction_id, "scenario": "SUCCESS"}
    )
    assert callback.status_code == 200, callback.text

    event = (
        seeded_db.query(WebhookEvent)
        .filter(WebhookEvent.event_type == "subscription.activated", WebhookEvent.entity_id == subscription_id)
        .one()
    )
    assert calls == [event.event_id]
