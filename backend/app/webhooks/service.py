"""
Outbound webhook dispatch (spec sections 30-37).

Two-phase design so the whole app stays testable without any live broker
or network (spec section 73, matching this codebase's existing "no real
external dependency required" philosophy for the payment gateways):

  - queue_event() is a pure DB write - always safe to call, including
    from inside PaymentService's transaction (spec section 58: no
    external HTTP call held open inside a financial-transaction commit).
    It creates a durable WebhookEvent + WebhookDelivery(PENDING) row and
    touches no network and no Celery/Redis at all.
  - dispatch_pending() is the actual delivery sweep: finds every
    delivery that's due (PENDING, or FAILED with next_retry_at in the
    past) and attempts each once over HTTP, updating retry bookkeeping
    per WEBHOOK_RETRY_SCHEDULE_MINUTES. app/webhooks/tasks.py's Celery
    beat task calls this periodically in a running deployment; a test
    can call it directly (optionally with a fake httpx client) with zero
    Celery involved.

Every delivery is HMAC-SHA256 signed (X-Webhook-Signature: sha256=<hex>,
over the raw JSON body) using the destination application's own
webhook_secret if set, else EVERYTICKET_WEBHOOK_SECRET - the same
override/fallback pattern PayU's credentials use (env vars are the
production source of truth; the Application row is a per-application
override, per that model's own docstring).
"""
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.orm import Session

from app.applications.models import Application
from app.core.config import get_settings
from app.core.enums import WebhookDeliveryStatus
from app.core.ids import new_event_id
from app.webhooks.models import WebhookDelivery, WebhookEvent

logger = logging.getLogger("subscription")


def _resolve_destination(application: Application | None) -> tuple[str | None, str | None]:
    settings = get_settings()
    if application is None:
        return settings.EVERYTICKET_WEBHOOK_URL or None, settings.EVERYTICKET_WEBHOOK_SECRET or None
    url = application.webhook_url or settings.EVERYTICKET_WEBHOOK_URL or None
    secret = application.webhook_secret or settings.EVERYTICKET_WEBHOOK_SECRET or None
    return url, secret


def queue_event(
    db: Session,
    *,
    application: Application,
    event_type: str,
    entity_type: str,
    entity_id: str,
    payload: dict,
) -> WebhookEvent | None:
    """Durable, DB-only enqueue - never makes a network call. Returns
    None (and queues nothing) if there's no destination configured at
    all (neither the application's own webhook_url nor the
    EVERYTICKET_WEBHOOK_URL fallback), since there's nowhere to send it."""
    url, _secret = _resolve_destination(application)
    if not url:
        logger.info(
            "No webhook destination configured for application %s - skipping %s event",
            application.code,
            event_type,
        )
        return None

    event = WebhookEvent(
        event_id=new_event_id(),
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        payload=payload,
    )
    db.add(event)
    db.flush()

    delivery = WebhookDelivery(
        webhook_event_id=event.id,
        destination_application_id=application.id,
        destination_url=url,
        status=WebhookDeliveryStatus.PENDING.value,
        attempt_count=0,
        next_retry_at=datetime.now(timezone.utc),
    )
    db.add(delivery)
    db.flush()
    return event


def _sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _attempt_one(db: Session, delivery: WebhookDelivery, *, http_client: httpx.Client | None = None) -> bool:
    """Makes one delivery attempt and updates the row in place. Returns
    True iff it succeeded (2xx). Owns its own short-lived httpx.Client
    unless one is passed in (tests inject a transport-mocked client so
    nothing here ever needs real network access)."""
    settings = get_settings()
    event = delivery.event
    application = db.get(Application, delivery.destination_application_id)
    _url, secret = _resolve_destination(application)

    body = json.dumps(
        {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "entity_type": event.entity_type,
            "entity_id": event.entity_id,
            "payload": event.payload,
        },
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["X-Webhook-Signature"] = f"sha256={_sign(secret, body)}"

    owns_client = http_client is None
    client = http_client or httpx.Client(timeout=10.0)
    try:
        response = client.post(delivery.destination_url, content=body, headers=headers)
        delivery.http_status = response.status_code
        delivery.response_body = response.text[:4000]
        succeeded = 200 <= response.status_code < 300
    except httpx.HTTPError as exc:
        delivery.http_status = None
        delivery.response_body = str(exc)[:4000]
        succeeded = False
    finally:
        if owns_client:
            client.close()

    delivery.attempt_count += 1
    delivery.last_attempt_at = datetime.now(timezone.utc)

    if succeeded:
        delivery.status = WebhookDeliveryStatus.SUCCESS.value
        delivery.next_retry_at = None
    else:
        schedule = settings.webhook_retry_schedule
        if delivery.attempt_count <= len(schedule):
            delay_minutes = schedule[delivery.attempt_count - 1]
            delivery.status = WebhookDeliveryStatus.FAILED.value
            delivery.next_retry_at = datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)
        else:
            delivery.status = WebhookDeliveryStatus.EXHAUSTED.value
            delivery.next_retry_at = None

    db.add(delivery)
    db.commit()
    return succeeded


def attempt_delivery_with_client(
    db: Session, delivery: WebhookDelivery, *, http_client: httpx.Client | None = None
) -> bool:
    """Public entry point for the admin Testing module's WEBHOOK FAILURE
    SIMULATOR (spec section 54): attempts exactly ONE specific delivery
    (never the whole due-queue dispatch_pending() would pick up) through
    an optionally-injected http_client - e.g. an httpx.MockTransport that
    always returns a chosen status code or raises a timeout - so an admin
    can verify the real retry-schedule/EXHAUSTED bookkeeping logic in
    _attempt_one() without ever touching any *other* pending delivery a
    real integration might have queued at the same time."""
    return _attempt_one(db, delivery, http_client=http_client)


def send_ad_hoc_webhook(
    *, application: Application, payload: dict, extra_headers: dict[str, str] | None = None, timeout: float = 10.0
) -> dict:
    """TEST EVERYTICKET WEBHOOK (spec section 54): a one-off signed POST
    of admin-supplied JSON to the application's configured webhook
    destination. Unlike queue_event()/dispatch_pending(), this never
    writes a WebhookEvent/WebhookDelivery row - it's a live diagnostic
    tool for an admin to poke the destination directly, not a real
    business event, so there is nothing here to retry or track. Returns
    a dict of exactly what the spec asks the UI to show: the request that
    was sent, the response (or error) that came back, the HTTP status,
    and elapsed time - never raises, since a failed test send (including
    "no destination configured", a connection error, or a timeout) is
    itself a valid, informative test result rather than a 500."""
    import time as _time

    url, secret = _resolve_destination(application)
    if not url:
        return {
            "sent": False,
            "error": "No webhook destination configured for this application (no webhook_url and no EVERYTICKET_WEBHOOK_URL fallback)",
        }

    body = json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")
    headers = {"Content-Type": "application/json", **(extra_headers or {})}
    if secret:
        headers["X-Webhook-Signature"] = f"sha256={_sign(secret, body)}"

    started = _time.monotonic()
    try:
        with httpx.Client(timeout=timeout) as client:
            response = client.post(url, content=body, headers=headers)
        elapsed_ms = round((_time.monotonic() - started) * 1000, 1)
        return {
            "sent": True,
            "request": {"url": url, "headers": headers, "body": payload},
            "http_status": response.status_code,
            "response_body": response.text[:4000],
            "elapsed_ms": elapsed_ms,
        }
    except httpx.HTTPError as exc:
        elapsed_ms = round((_time.monotonic() - started) * 1000, 1)
        return {
            "sent": False,
            "request": {"url": url, "headers": headers, "body": payload},
            "http_status": None,
            "error": str(exc),
            "elapsed_ms": elapsed_ms,
        }


def dispatch_pending(db: Session, *, limit: int = 50, http_client: httpx.Client | None = None) -> int:
    """Finds every delivery due right now (PENDING, or FAILED with
    next_retry_at already in the past) and attempts each once. Returns
    how many were attempted. This is what the Celery beat task calls
    periodically (app/webhooks/tasks.py) - and what a test can call
    directly with a fake http_client, with no Celery/network involved."""
    now = datetime.now(timezone.utc)
    due = (
        db.query(WebhookDelivery)
        .filter(
            WebhookDelivery.status.in_([WebhookDeliveryStatus.PENDING.value, WebhookDeliveryStatus.FAILED.value]),
            WebhookDelivery.next_retry_at.isnot(None),
            WebhookDelivery.next_retry_at <= now,
        )
        .order_by(WebhookDelivery.next_retry_at.asc())
        .limit(limit)
        .all()
    )
    for delivery in due:
        _attempt_one(db, delivery, http_client=http_client)
    return len(due)
