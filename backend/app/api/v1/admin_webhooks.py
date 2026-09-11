"""
Admin Webhook Logs (spec sections 34-37, 51).

The retry endpoint only ever resets a delivery back to PENDING with
next_retry_at=now - it never makes the outbound HTTP call itself (that
stays exclusively app.webhooks.service.dispatch_pending's job, run by the
Celery beat schedule every 60s per app.core.celery_app). Same
queue-then-dispatch split used everywhere else in this codebase: an admin
API request should return fast, not block on an external POST.

verify_connectivity (added per Vishal: "Webhook API is not getting
reached or logging headers, statuscode, etc.. from API... please give
button as well near log to click and verify that its calling properly
or not") is the one exception - it DOES make a real, synchronous HTTP
call, because its entire job is to answer "can we reach the destination
right now" immediately. Unlike the Testing module's TEST EVERYTICKET
WEBHOOK tool, it is NOT gated by require_test_mode() - an admin needs to
check real, live webhook connectivity in production too, not only in a
test-mode sandbox.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_application, get_db
from app.api.v1.admin_common import DEFAULT_LIMIT, MAX_LIMIT, PageOut, paginate
from app.applications.models import Application
from app.audit import service as audit_service
from app.auth.deps import require_permission
from app.auth.models import AdminUser
from app.core.enums import WebhookDeliveryStatus
from app.core.exceptions import AppError, WebhookAlreadyDelivered
from app.webhooks import service as webhook_service
from app.webhooks.models import WebhookDelivery, WebhookEvent
from app.webhooks.schemas import WebhookDeliveryOut, WebhookEventOut


router = APIRouter(prefix="/webhooks", tags=["admin-webhooks"])


class WebhookEventNotFoundError(AppError):
    http_status = 404
    error_code = "WEBHOOK_EVENT_NOT_FOUND"


class WebhookDeliveryNotFoundError(AppError):
    http_status = 404
    error_code = "WEBHOOK_DELIVERY_NOT_FOUND"


def _to_event_out(event: WebhookEvent) -> WebhookEventOut:
    return WebhookEventOut(
        event_id=event.event_id,
        event_type=event.event_type,
        entity_type=event.entity_type,
        entity_id=event.entity_id,
        payload=event.payload,
        created_at=event.created_at,
        deliveries=[WebhookDeliveryOut.model_validate(d) for d in event.deliveries],
    )


@router.get("/events", response_model=PageOut[WebhookEventOut])
def list_events(
    event_type: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(require_permission("WEBHOOKS_VIEW")),
):
    query = db.query(WebhookEvent).options(joinedload(WebhookEvent.deliveries))
    if event_type:
        query = query.filter(WebhookEvent.event_type == event_type)
    query = query.order_by(WebhookEvent.created_at.desc())

    items, total = paginate(query, limit=limit, offset=offset)
    return PageOut(items=[_to_event_out(e) for e in items], total=total, limit=limit, offset=offset)


@router.get("/events/{event_id}", response_model=WebhookEventOut)
def get_event(
    event_id: str,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(require_permission("WEBHOOKS_VIEW")),
):
    event = db.query(WebhookEvent).filter(WebhookEvent.event_id == event_id).first()
    if event is None:
        raise WebhookEventNotFoundError(f"Unknown webhook event {event_id}")
    return _to_event_out(event)


@router.get("/deliveries", response_model=PageOut[WebhookDeliveryOut])
def list_deliveries(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(require_permission("WEBHOOKS_VIEW")),
):
    query = db.query(WebhookDelivery)
    if status_filter:
        query = query.filter(WebhookDelivery.status == status_filter.upper())
    query = query.order_by(WebhookDelivery.created_at.desc())

    items, total = paginate(query, limit=limit, offset=offset)
    return PageOut(items=[WebhookDeliveryOut.model_validate(d) for d in items], total=total, limit=limit, offset=offset)


@router.post("/verify")
def verify_connectivity(
    application: Application = Depends(get_application),
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_permission("WEBHOOKS_MANAGE")),
):
    """Sends a small, fixed, harmless ping payload to the application's
    currently-configured webhook destination, signed exactly like a real
    delivery, and records a real WebhookEvent/WebhookDelivery row (event_
    type "webhook.connectivity_check") so the result - reached or not,
    HTTP status, headers, response body/error - is immediately visible
    on this same screen after a reload. Returns the live result too, so
    the frontend can show an instant "Reached (HTTP 200)" / "Failed:
    <error>" toast without waiting on a second round trip."""
    result = webhook_service.verify_connectivity(db, application=application)
    audit_service.record(
        db,
        actor=admin.email,
        action="WEBHOOK_CONNECTIVITY_VERIFIED",
        entity_type="application",
        entity_id=application.code,
        new_value=result,
    )
    db.commit()
    return result


@router.post("/deliveries/{delivery_id}/retry", response_model=WebhookDeliveryOut)
def retry_delivery(
    delivery_id: int,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_permission("WEBHOOKS_MANAGE")),
):
    delivery = db.query(WebhookDelivery).filter(WebhookDelivery.id == delivery_id).first()
    if delivery is None:
        raise WebhookDeliveryNotFoundError(f"Unknown webhook delivery {delivery_id}")
    if delivery.status == WebhookDeliveryStatus.SUCCESS.value:
        raise WebhookAlreadyDelivered(
            f"Webhook delivery {delivery_id} already succeeded - retrying it risks a duplicate downstream instance"
        )

    old_status = delivery.status
    delivery.status = WebhookDeliveryStatus.PENDING.value
    delivery.next_retry_at = datetime.now(timezone.utc)
    db.add(delivery)

    audit_service.record(
        db,
        actor=admin.email,
        action="WEBHOOK_DELIVERY_RETRY_REQUESTED",
        entity_type="webhook_delivery",
        entity_id=str(delivery.id),
        old_value={"status": old_status},
        new_value={"status": delivery.status},
    )
    db.commit()
    db.refresh(delivery)
    return WebhookDeliveryOut.model_validate(delivery)
