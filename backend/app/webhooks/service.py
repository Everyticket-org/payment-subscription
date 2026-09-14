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
  - dispatch_pending() is the periodic delivery sweep: finds every
    delivery that's due (PENDING, or FAILED with next_retry_at in the
    past) and attempts each once over HTTP, updating retry bookkeeping
    per WEBHOOK_RETRY_SCHEDULE_MINUTES. app/webhooks/tasks.py's Celery
    beat task calls this periodically in a running deployment; a test
    can call it directly (optionally with a fake httpx client) with zero
    Celery involved. This is what actually retries a FAILED delivery -
    it depends on the Celery worker+beat processes actually running.
  - attempt_soon() (2026-09-11 follow-up) is the immediate path: called
    right after a real business event's enclosing transaction commits
    (e.g. PaymentService, after a payment succeeds), it makes ONE real
    delivery attempt in a background thread with its own DB session -
    never blocking its caller, never depending on Celery being up at
    all. Before this existed, a queued delivery's very first attempt
    depended entirely on dispatch_pending() eventually being invoked by
    Celery beat - if that background process wasn't running (the
    default for a plain `uvicorn` run per this repo's own README, unless
    Docker Compose or the worker+beat commands are also started), a
    real delivery sat at PENDING with no response forever, exactly what
    Vishal reported ("webhook called from payment success to
    everyticket does not show response and show pending only").

Every delivery is HMAC-SHA256 signed (X-Webhook-Signature: sha256=<hex>,
over the raw JSON body) using the destination application's own
webhook_secret if set, else EVERYTICKET_WEBHOOK_SECRET - the same
override/fallback pattern PayU's credentials use (env vars are the
production source of truth; the Application row is a per-application
override, per that model's own docstring).

PROVISIONING (spec sections 32, 37): a "subscription.activated" delivery
is special-cased. Everyticket's response body - not just the HTTP status -
still carries the real provisioning result ({success, instance_id}), so
_handle_activation_outcome() below parses it and:
  - on success: sets Subscription.provisioning_status=SUCCESS and
    upserts the CustomerApplicationMapping (permanent customer<->
    external-identity mapping, spec section 8) - never inserting a second
    mapping row for the same customer+application (spec section 32: no
    duplicate instances).

    2026-09-14 follow-up ("can we use subscription ID? as we are sending
    to everyticket" - Vishal, re: the SSO API access help text asking
    what value Everyticket has to send back as external_customer_id):
    the mapping's external_customer_id is now ALWAYS this app's own
    subscription.subscription_id, set unconditionally by this app itself
    at the moment provisioning succeeds - never whatever (if anything)
    Everyticket's response body says under an "external_customer_id" key,
    which is no longer read at all. This removes any dependency on
    Everyticket implementing that part of the response contract
    correctly (or at all): subscription_id is already a FIXED field on
    every subscription.activated payload (app.webhooks.payloads), so
    Everyticket's backend doesn't need to invent or manage its own
    identifier - it only has to remember the subscription_id it was
    given and echo that same value back to POST /api/v1/integration/
    sso/generate-link later. instance_id is unaffected - still whatever
    Everyticket's response says, still optional, still just their own
    reference metadata never used for lookup.

    This still self-heals correctly across a repurchase-after-expiry
    (spec section 41: a fresh subscription.activated event, with a brand
    new subscription_id since create_pending_subscription() always
    mints one - see app.subscriptions.service): _upsert_external_mapping
    finds the SAME mapping row (keyed by customer_id+application_id, not
    by the old external_customer_id) and overwrites external_customer_id
    with the new subscription_id, so Everyticket's SSO calls immediately
    start using whichever subscription_id was most recently issued. An
    upgrade/downgrade never fires subscription.activated at all (it
    mutates the existing Subscription row in place, same subscription_id
    throughout - app.subscriptions.service.apply_plan_change), so the
    mapping is untouched by those and stays correct in between.
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
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.orm import Session

from app.applications.models import Application, CustomerApplicationMapping
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.enums import ProvisioningStatus, WebhookDeliveryStatus
from app.core.ids import new_event_id
from app.subscriptions.models import Subscription
from app.webhooks.models import WebhookDelivery, WebhookEvent

logger = logging.getLogger("subscription")

_ACTIVATION_EVENT_TYPE = "subscription.activated"

# Bounds how long any single delivery attempt can hold its DB connection
# and block its caller (2026-09-11 follow-up: Vishal reported "attempt
# call is also taking time including payu success and return time as
# well.. all API get freesed in admin panel" - traced to the flat
# httpx.Client(timeout=10.0) this module used to construct everywhere,
# which applies 10s independently to EACH phase (connect/read/write/pool)
# rather than one combined 10s budget, so a single stuck destination
# could hold a request - and the DB connection its session was still
# holding - open for well over 10s. A real, unreachable, or slow-to-
# respond Everyticket destination should fail fast and predictably
# instead. Every httpx.Client this module constructs for a webhook
# attempt now uses this same bounded timeout.
_WEBHOOK_HTTP_TIMEOUT = httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=3.0)


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


def _attempt_soon_worker(event_id: str) -> None:
    """Runs in its own background thread with its own DB session/
    connection - never the caller's - so it can never hold the caller's
    request or its DB connection open, and never needs the caller's own
    transaction to still be in scope. Opens fresh, attempts, closes,
    exactly like app/webhooks/tasks.py's Celery task does; the only
    difference is what triggers it (a real event just being queued,
    right here, instead of a periodic beat tick)."""
    db = SessionLocal()
    try:
        event = db.query(WebhookEvent).filter(WebhookEvent.event_id == event_id).first()
        if event is None:
            logger.warning("attempt_soon: webhook event %s not found - nothing to attempt", event_id)
            return
        for delivery in event.deliveries:
            if delivery.status != WebhookDeliveryStatus.PENDING.value:
                continue
            try:
                _attempt_one(db, delivery)
            except Exception:
                logger.exception("attempt_soon: delivery %s for event %s failed unexpectedly", delivery.id, event_id)
    except Exception:
        logger.exception("attempt_soon: failed to process webhook event %s", event_id)
    finally:
        db.close()


def attempt_soon(event_id: str | None) -> None:
    """Kicks off one real, immediate delivery attempt for a just-queued
    webhook event in the background - added per Vishal: "why its not
    being called properly on payment success" (2026-09-11 follow-up).

    queue_event() above is deliberately a pure DB write with no network
    call, so a real business event (a payment succeeding, a renewal, a
    cancellation...) used to depend ENTIRELY on the Celery beat schedule
    (app/core/celery_app.py, every 60s) ever attempting it at all - if
    that background process wasn't running, the delivery sat at PENDING
    forever, exactly what Vishal reported ("show pending only"). This
    function is called right after the enclosing transaction commits
    (never before - see queue_event()'s own docstring and spec section
    58, which this still respects: no external HTTP call is ever made
    INSIDE that commit) and spawns a short-lived background thread that
    makes the real attempt on its own schedule, own session, own
    connection - the caller (e.g. the payment-success API request) is
    never blocked waiting for it and never holds its own DB connection
    open any longer because of it. Celery beat is still what retries a
    FAILED delivery later (this only ever makes ONE immediate attempt);
    nothing about the retry schedule, EXHAUSTED handling, or the admin
    Attempt/Retry actions changes.

    A no-op (logged, swallowed) if event_id is None - the normal
    "no destination configured" case queue_event() already handles by
    returning None and queueing nothing at all."""
    if event_id is None:
        return
    threading.Thread(target=_attempt_soon_worker, args=(event_id,), daemon=True).start()


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
    delivery.request_headers = headers

    # Vishal: "Log webhook call time and response completion time" - the
    # wall-clock start is recorded for display/audit, the monotonic clock
    # is what actually measures elapsed time (never skewed by a wall-clock
    # adjustment mid-attempt, unlike subtracting two datetime.now() calls).
    delivery.attempt_started_at = datetime.now(timezone.utc)
    _perf_start = time.monotonic()

    owns_client = http_client is None
    client = http_client or httpx.Client(timeout=_WEBHOOK_HTTP_TIMEOUT)
    try:
        response = client.post(delivery.destination_url, content=body, headers=headers)
        delivery.http_status = response.status_code
        delivery.response_body = response.text[:4000]
        delivery.response_headers = dict(response.headers)
        succeeded = 200 <= response.status_code < 300
    except httpx.HTTPError as exc:
        delivery.http_status = None
        delivery.response_body = str(exc)[:4000]
        delivery.response_headers = None
        succeeded = False
    finally:
        if owns_client:
            client.close()

    delivery.duration_ms = round((time.monotonic() - _perf_start) * 1000)

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

    logger.info(
        "Webhook delivery %s (%s) to %s: started %s, completed %s, took %dms, HTTP %s, %s",
        delivery.id,
        event.event_type,
        delivery.destination_url,
        delivery.attempt_started_at.isoformat(),
        delivery.last_attempt_at.isoformat(),
        delivery.duration_ms,
        delivery.http_status,
        delivery.status,
    )

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

    2026-09-14 follow-up: the response body's own "external_customer_id"
    (if Everyticket sends one at all) is deliberately never read anymore -
    see this module's own docstring above for why subscription_id is used
    instead, unconditionally, on every success. "instance_id" is still
    read from the response as before (Everyticket's own optional
    reference, never used for lookup).
    """
    provisioning_ok = http_succeeded
    external_instance_id: str | None = None

    if http_succeeded and response_body:
        try:
            parsed = json.loads(response_body)
        except (TypeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            if parsed.get("success") is False:
                provisioning_ok = False
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
        if application is not None:
            _upsert_external_mapping(
                db,
                customer_id=subscription.customer_id,
                application_id=application.id,
                # This app's own subscription_id, not anything parsed from
                # Everyticket's response - see the module docstring's
                # 2026-09-14 follow-up.
                external_customer_id=subscription.subscription_id,
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
    though it re-sends a fresh subscription.activated event: the caller
    (_handle_activation_outcome) passes the subscription's own, freshly
    generated subscription_id each time, and this just overwrites the
    same row's external_customer_id with it - no new row, no unique-
    constraint conflict."""
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
    *, application: Application, payload: dict, extra_headers: dict[str, str] | None = None, timeout: float = 8.0
) -> dict:
    """A one-off signed POST of a given JSON payload to the application's
    configured webhook destination - the actual HTTP send shared by the
    admin Testing module's TEST EVERYTICKET WEBHOOK tool (spec section
    54, arbitrary admin-edited payload/headers, TEST_MODE-only) and the
    Webhook Logs screen's "Verify connectivity" action (a fixed ping
    payload, no TEST_MODE gate - see verify_connectivity() below). This
    function itself never writes a WebhookEvent/WebhookDelivery row -
    callers that want the attempt recorded (both of the above do) use
    record_ad_hoc_delivery() with the result this returns.

    Returns a dict of exactly what the UI shows: the request that was
    sent (url/headers/body), the response (or error) that came back, the
    HTTP status, response headers, and elapsed time - never raises,
    since a failed send (including "no destination configured", a
    connection error, or a timeout) is itself a valid, informative
    result rather than a 500."""
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

    # Vishal: "Log webhook call time and response completion time" -
    # started_at is the wall-clock moment this call began (returned so
    # callers/record_ad_hoc_delivery() can persist it); elapsed_ms below
    # was already measured with a monotonic clock (unaffected by this
    # addition).
    started_at = datetime.now(timezone.utc)
    started = _time.monotonic()
    try:
        # Same connect/read split as _WEBHOOK_HTTP_TIMEOUT above, scaled to
        # this function's own (admin-overridable) timeout parameter rather
        # than hardcoding it, so an explicit caller-provided timeout is
        # still honored end to end.
        with httpx.Client(timeout=httpx.Timeout(connect=min(timeout, 3.0), read=timeout, write=timeout, pool=3.0)) as client:
            response = client.post(url, content=body, headers=headers)
        elapsed_ms = round((_time.monotonic() - started) * 1000, 1)
        logger.info(
            "Ad-hoc webhook send to %s: started %s, took %sms, HTTP %s",
            url,
            started_at.isoformat(),
            elapsed_ms,
            response.status_code,
        )
        return {
            "sent": True,
            "request": {"url": url, "headers": headers, "body": payload},
            "http_status": response.status_code,
            "response_body": response.text[:4000],
            "response_headers": dict(response.headers),
            "elapsed_ms": elapsed_ms,
            "started_at": started_at.isoformat(),
        }
    except httpx.HTTPError as exc:
        elapsed_ms = round((_time.monotonic() - started) * 1000, 1)
        logger.info(
            "Ad-hoc webhook send to %s: started %s, took %sms, failed: %s",
            url,
            started_at.isoformat(),
            elapsed_ms,
            exc,
        )
        return {
            "sent": False,
            "request": {"url": url, "headers": headers, "body": payload},
            "http_status": None,
            "response_headers": None,
            "error": str(exc),
            "elapsed_ms": elapsed_ms,
            "started_at": started_at.isoformat(),
        }


def record_ad_hoc_delivery(
    db: Session, *, application: Application, event_type: str, entity_id: str, payload: dict, result: dict
) -> WebhookDelivery | None:
    """Records the result of an send_ad_hoc_webhook() attempt as a real
    WebhookEvent + WebhookDelivery row, so it's visible on the admin
    Webhook Logs screen exactly like a genuine delivery - response_body,
    http_status, request/response headers included, success or failure.
    Shared by both the Testing module's ad-hoc send and
    verify_connectivity() below.

    Returns None (and records nothing) when send_ad_hoc_webhook() never
    actually attempted anything (its "no destination configured" early
    return, identifiable by the absence of a "request" key) - a
    WebhookDelivery represents an attempt, and none was made.

    next_retry_at is deliberately left None: this is a one-off record for
    visibility, not a queued delivery. dispatch_pending()'s retry sweep
    only ever picks up rows with next_retry_at set, so this can never be
    silently auto-resent through the standard {event_type, payload}
    envelope - a different body than whatever was actually sent here
    (the ad-hoc tool sends its payload raw, unwrapped)."""
    if "request" not in result:
        return None

    event = WebhookEvent(
        event_id=new_event_id(),
        event_type=event_type,
        entity_type="test",
        entity_id=entity_id,
        payload=payload,
    )
    db.add(event)
    db.flush()

    _completed_at = datetime.now(timezone.utc)
    _started_at_raw = result.get("started_at")
    delivery = WebhookDelivery(
        webhook_event_id=event.id,
        destination_application_id=application.id,
        destination_url=result["request"]["url"],
        status=WebhookDeliveryStatus.SUCCESS.value if result.get("sent") else WebhookDeliveryStatus.FAILED.value,
        http_status=result.get("http_status"),
        response_body=(result.get("response_body") or result.get("error") or "")[:4000],
        request_headers=result["request"].get("headers"),
        response_headers=result.get("response_headers"),
        attempt_count=1,
        attempt_started_at=(datetime.fromisoformat(_started_at_raw) if _started_at_raw else None),
        duration_ms=(round(result["elapsed_ms"]) if result.get("elapsed_ms") is not None else None),
        last_attempt_at=_completed_at,
        next_retry_at=None,
    )
    db.add(delivery)
    db.flush()
    return delivery


_CONNECTIVITY_CHECK_PAYLOAD = {"ping": True, "source": "admin_webhook_logs_verify"}


def verify_connectivity(db: Session, *, application: Application) -> dict:
    """Webhook Logs screen's "Verify connectivity" button (per Vishal:
    "please give button as well near log to click and verify that its
    calling properly or not"). Sends a small, fixed, harmless ping
    payload to the application's currently-configured destination -
    signed exactly like a real delivery - and always records the
    attempt via record_ad_hoc_delivery() (event_type
    "webhook.connectivity_check") so the result is immediately visible
    in the log, not just in this call's own return value.

    Deliberately NOT gated by require_test_mode() (unlike the Testing
    module's arbitrary-payload send) - an admin needs to be able to
    check "is my real, live webhook destination reachable right now" in
    production too, the same way retrying a delivery already is."""
    result = send_ad_hoc_webhook(application=application, payload=_CONNECTIVITY_CHECK_PAYLOAD)
    record_ad_hoc_delivery(
        db,
        application=application,
        event_type="webhook.connectivity_check",
        entity_id=f"VERIFY-{uuid.uuid4().hex[:10].upper()}",
        payload=_CONNECTIVITY_CHECK_PAYLOAD,
        result=result,
    )
    return result


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
