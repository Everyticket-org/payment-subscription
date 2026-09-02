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

PROVISIONING (spec sections 32, 37): a "subscription.activated" delivery
is special-cased. Everyticket's response body - not just the HTTP status -
carries the real provisioning result (spec section 32: "Everyticket should
return its external identity" as {success, external_customer_id,
instance_id}), so _handle_activation_outcome() below parses it and:
  - on success: sets Subscription.provisioning_status=SUCCESS and
    upserts the CustomerApplicationMapping (permanent customer<->
    external-identity mapping, spec section 8) with whatever identity
    Everyticket returned - never inserting a second mapping row for the
    same customer+application (spec section 32: no duplicate instances).
  - on failure (network error, non-2xx, or a 2xx body that explicitly
    says success:false): sets provisioning_status=FAILED and sends a
    one-time "provisioning_issue" notification (spec section 37: "Customer
    should receive an appropriate status message"). The payment/
    subscription itself is NEVER touched here (spec section 30:
    "Everyticket provisioning failure does not make payment fail") -
    only this delivery's own retry/backoff bookkeeping, which already
    gives provisioning its "retried automatically" behavior (spec section
    31) for free, and the admin "manual retry" endpoint
    (app/api/v1/admin_webhooks.py) covers "Admin can manually retry".
"""
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.orm import Session

from app.applications.models import Application, CustomerApplicationMapping
from app.core.config import get_settings
from app.core.enums import ProvisioningStatus, WebhookDeliveryStatus
from app.core.ids import new_event_id
from app.subscriptions.models import Subscription
from app.webhooks.models import WebhookDelivery, WebhookEvent

logger = logging.getLogger("subscription")

_ACTIVATION_EVENT_TYPE = "subscription.activated"


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

    if event_type == _ACTIVATION_EVENT_TYPE and entity_type == "subscription":
        # Spec sections 20, 37: provisioning genuinely starts now - a
        # delivery attempt for it is durably queued - rather than staying
        # NOT_STARTED until the first HTTP attempt actually fires.
        subscription = db.query(Subscription).filter(Subscription.subscription_id == entity_id).first()
        if subscription is not None and subscription.provisioning_status == ProvisioningStatus.NOT_STARTED.value:
            subscription.provisioning_status = ProvisioningStatus.IN_PROGRESS.value
            db.add(subscription)
            db.flush()

    return event


def _sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def build_wire_body(*, event_type: str, payload: dict) -> dict:
    """The exact top-level JSON object POSTed to the destination webhook
    URL - deliberately just two fields (2026-09 follow-up 3: "Keep only
    event_type" at the top level, everything else about the event lives
    in payload). The custom key/value extra-parameters feature that used
    to get merged in here was removed in the same pass - a delivery's
    wire body is now exactly {event_type, payload}, nothing more.

    Pulled out of _attempt_one() into its own pure function so
    app.api.v1.admin_config's read-only "sample JSON" preview (2026-09
    follow-up: "show JSON with all data passing") can build the EXACT
    same shape a real delivery sends, rather than a hand-maintained
    approximation that could quietly drift from it."""
    return {"event_type": event_type, "payload": payload}


def _attempt_one(db: Session, delivery: WebhookDelivery, *, http_client: httpx.Client | None = None) -> bool:
    """Makes one delivery attempt and updates the row in place. Returns
    True iff it succeeded (2xx). Owns its own short-lived httpx.Client
    unless one is passed in (tests inject a transport-mocked client so
    nothing here ever needs real network access)."""
    settings = get_settings()
    event = delivery.event
    application = db.get(Application, delivery.destination_application_id)
    _url, secret = _resolve_destination(application)

    body_dict = build_wire_body(event_type=event.event_type, payload=event.payload)
    body = json.dumps(body_dict, separators=(",", ":"), default=str).encode("utf-8")
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

    if event.event_type == _ACTIVATION_EVENT_TYPE and event.entity_type == "subscription":
        # May downgrade `succeeded` to False if Everyticket returned a 2xx
        # but its body explicitly reported success:false - see this
        # module's docstring. A bug in this best-effort side effect must
        # never break the delivery's own retry bookkeeping below, hence
        # the broad try/except.
        try:
            succeeded = _handle_activation_outcome(
                db,
                application=application,
                subscription_id=event.entity_id,
                http_succeeded=succeeded,
                response_body=delivery.response_body,
            )
        except Exception:
            logger.exception(
                "Provisioning-outcome handling failed for subscription %s - leaving delivery status as-is",
                event.entity_id,
            )

    delivery.attempt_count += 1
    delivery.last_attempt_at = datetime.now(timezone.utc)

    if succeeded:
        delivery.status = WebhookDeliveryStatus.SUCCESS.value
        delivery.next_retry_at = None
    else:
        schedule = _effective_retry_schedule(settings, application)
        if delivery.attempt_count <= len(schedule):
            delay_minutes = schedule[delivery.attempt_count - 1]
            delivery.status = WebhookDeliveryStatus.FAILED.value
            delivery.next_retry_at = datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)
        else:
            delivery.status = WebhookDeliveryStatus.EXHAUSTED.value
            delivery.next_retry_at = None
            # Everyticket Integration screen's "Retry limit... if all retry
            # options failed, send an email" - fires exactly once, on the
            # transition INTO EXHAUSTED (this branch only runs when a
            # delivery is being marked EXHAUSTED right now, never again for
            # an already-EXHAUSTED row, since dispatch_pending() only
            # re-attempts PENDING/FAILED deliveries).
            _notify_webhook_exhausted(db, delivery=delivery, application=application)

    db.add(delivery)
    db.commit()
    return succeeded


def _handle_activation_outcome(
    db: Session,
    *,
    application: Application | None,
    subscription_id: str,
    http_succeeded: bool,
    response_body: str | None,
) -> bool:
    """Interprets Everyticket's response to a subscription.activated
    delivery attempt (spec section 32) and updates
    Subscription.provisioning_status accordingly. Returns the effective
    "did provisioning actually succeed" outcome, which the caller also
    uses as the delivery's own success/failure for retry purposes (a 2xx
    HTTP response with a body that explicitly says success:false is NOT
    a successful delivery - Everyticket didn't actually provision
    anything, so it must be retried same as a network/HTTP failure).

    Best-effort only: an unknown subscription_id (e.g. a unit test that
    queues an event without a real Subscription row) is logged and
    ignored rather than raised, so this never breaks delivery dispatch
    itself.
    """
    provisioning_ok = http_succeeded
    external_customer_id: str | None = None
    external_instance_id: str | None = None

    if http_succeeded and response_body:
        try:
            parsed = json.loads(response_body)
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            if parsed.get("success") is False:
                provisioning_ok = False
            external_customer_id = parsed.get("external_customer_id")
            external_instance_id = parsed.get("instance_id")

    subscription = db.query(Subscription).filter(Subscription.subscription_id == subscription_id).first()
    if subscription is None:
        logger.warning("Provisioning outcome received for unknown subscription %s - ignoring", subscription_id)
        return provisioning_ok

    was_failed = subscription.provisioning_status == ProvisioningStatus.FAILED.value
    subscription.provisioning_status = (
        ProvisioningStatus.SUCCESS.value if provisioning_ok else ProvisioningStatus.FAILED.value
    )
    db.add(subscription)

    if provisioning_ok:
        if application is not None and (external_customer_id or external_instance_id):
            _upsert_external_mapping(
                db,
                customer_id=subscription.customer_id,
                application_id=application.id,
                external_customer_id=external_customer_id,
                external_instance_id=external_instance_id,
            )
    elif not was_failed:
        # Only on the transition INTO failure - not on every subsequent
        # retry attempt that also fails - so a customer isn't emailed
        # repeatedly while the automatic retry schedule works through
        # its backoff (spec section 35's default schedule).
        _notify_provisioning_issue(db, subscription=subscription, application=application)

    return provisioning_ok


def _upsert_external_mapping(
    db: Session,
    *,
    customer_id: int,
    application_id: int,
    external_customer_id: str | None,
    external_instance_id: str | None,
) -> None:
    """Spec section 8: one permanent mapping row per (customer,
    application) - update it in place rather than inserting a second one,
    which is also what makes a repurchase-after-expiry re-activation (spec
    section 41: "reuse external_customer_id", no new museum) safe even
    though it re-sends a fresh subscription.activated event."""
    mapping = (
        db.query(CustomerApplicationMapping)
        .filter(
            CustomerApplicationMapping.customer_id == customer_id,
            CustomerApplicationMapping.application_id == application_id,
        )
        .first()
    )
    if mapping is None:
        mapping = CustomerApplicationMapping(customer_id=customer_id, application_id=application_id)
    if external_customer_id:
        mapping.external_customer_id = external_customer_id
    if external_instance_id:
        mapping.external_instance_id = external_instance_id
    db.add(mapping)


def _notify_provisioning_issue(db: Session, *, subscription: Subscription, application: Application | None) -> None:
    """Spec section 37: "Customer should receive an appropriate status
    message." A notification failure must never break provisioning
    bookkeeping, so this is best-effort/logged, never raised - matching
    every other notification call site in this codebase
    (app.payments.service's own invoice-email send is wrapped the same way)."""
    from app.notifications.email import service as email_service  # local import: avoids a module-load cycle

    try:
        customer = subscription.customer
        plan = subscription.plan
        email_service.send_templated_email(
            db,
            template_code="provisioning_issue",
            to=customer.email if customer else None,
            context={
                "plan_name": plan.name if plan else "",
                "subscription_id": subscription.subscription_id,
            },
            related_entity_type="subscription",
            related_entity_id=subscription.subscription_id,
            application=application,
        )
    except Exception:
        logger.exception(
            "Failed to send provisioning_issue email for subscription %s", subscription.subscription_id
        )


def _effective_retry_schedule(settings, application: "Application | None") -> list[int]:
    """WEBHOOK_RETRY_SCHEDULE_MINUTES's own list, unless the admin
    configured a different retry_limit (Everyticket Integration screen,
    2026-09 restructure) - a shorter limit truncates the schedule, a
    longer one repeats the schedule's last delay for the extra retries."""
    schedule = settings.webhook_retry_schedule
    limit = application.webhook_retry_limit if application is not None else None
    if not limit or limit <= 0:
        return schedule
    if limit <= len(schedule):
        return schedule[:limit]
    return schedule + [schedule[-1]] * (limit - len(schedule))


def _notify_webhook_exhausted(db: Session, *, delivery: WebhookDelivery, application: "Application | None") -> None:
    """Admin-configured escalation email (Everyticket Integration screen):
    sent to webhook_escalation_emails once a delivery is marked EXHAUSTED
    (all retries failed), with admin-edited subject/body rather than a
    NotificationTemplate the admin would have to go to a different screen
    to edit - "Email content as editor" was the explicit ask. Uses the
    same per-application SMTP override resolution as every other email in
    this app (app.notifications.email.service), so a configured SMTP
    override (also 2026-09) is honored here too. Best-effort/logged only,
    same as every other notification call site - a broken escalation
    email must never break delivery bookkeeping."""
    if application is None or not application.webhook_escalation_emails:
        return

    from jinja2 import Template

    from app.notifications.email import service as email_service

    recipients = [addr.strip() for addr in application.webhook_escalation_emails.split(",") if addr.strip()]
    if not recipients:
        return

    event = delivery.event
    context = {
        "event_type": event.event_type,
        "entity_type": event.entity_type,
        "entity_id": event.entity_id,
        "destination_url": delivery.destination_url,
        "attempt_count": delivery.attempt_count,
        "http_status": delivery.http_status,
    }
    subject_template = application.webhook_escalation_email_subject or "Webhook delivery failed after all retries"
    body_template = application.webhook_escalation_email_body or (
        "<p>A webhook delivery to {{ destination_url }} for event "
        "<strong>{{ event_type }}</strong> ({{ entity_type }} {{ entity_id }}) has "
        "failed after {{ attempt_count }} attempts and will not be retried "
        "automatically.</p>"
    )
    try:
        subject = Template(subject_template).render(**context)
        body_html = Template(body_template).render(**context)
    except Exception:
        logger.exception("Failed to render webhook-exhausted escalation email for delivery %s", delivery.id)
        return

    for to in recipients:
        try:
            email_service.send_direct_email(
                db,
                to=to,
                subject=subject,
                body_html=body_html,
                template_code="webhook_delivery_exhausted",
                related_entity_type="webhook_delivery",
                related_entity_id=str(delivery.id),
                application=application,
            )
        except Exception:
            logger.exception("Failed to send webhook-exhausted escalation email to %s", to)


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
