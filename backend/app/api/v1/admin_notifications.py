"""Admin Notification Templates + Email Logs (spec sections 49-50, 51)."""
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.v1.admin_common import DEFAULT_LIMIT, MAX_LIMIT, PageOut, paginate
from app.audit import service as audit_service
from app.auth.deps import require_permission
from app.auth.models import AdminUser
from app.core.exceptions import AppError
from app.notifications.models import NotificationLog, NotificationTemplate
from app.notifications.schemas import NotificationLogOut, NotificationTemplateOut, NotificationTemplateUpdate

router = APIRouter(prefix="/notifications", tags=["admin-notifications"])


class NotificationTemplateNotFoundError(AppError):
    http_status = 404
    error_code = "NOTIFICATION_TEMPLATE_NOT_FOUND"


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/templates", response_model=list[NotificationTemplateOut])
def list_templates(
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(require_permission("NOTIFICATIONS_VIEW")),
):
    templates = db.query(NotificationTemplate).order_by(NotificationTemplate.template_code).all()
    return [NotificationTemplateOut.model_validate(t) for t in templates]


@router.put("/templates/{template_code}", response_model=NotificationTemplateOut)
def update_template(
    template_code: str,
    body: NotificationTemplateUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_permission("NOTIFICATIONS_MANAGE")),
):
    template = db.query(NotificationTemplate).filter(NotificationTemplate.template_code == template_code).first()
    if template is None:
        raise NotificationTemplateNotFoundError(f"Unknown template '{template_code}'")

    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(template, field, value)
    db.add(template)
    db.flush()

    audit_service.record(
        db,
        actor=admin.email,
        action="NOTIFICATION_TEMPLATE_UPDATED",
        entity_type="notification_template",
        entity_id=template_code,
        new_value={k: v for k, v in updates.items() if k != "body_html"},  # HTML body omitted from the audit diff - bulky, not the interesting part
        ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(template)
    return NotificationTemplateOut.model_validate(template)


@router.get("/logs", response_model=PageOut[NotificationLogOut])
def list_logs(
    status_filter: str | None = Query(default=None, alias="status"),
    template_code: str | None = Query(default=None),
    recipient: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(require_permission("NOTIFICATIONS_VIEW")),
):
    query = db.query(NotificationLog)
    if status_filter:
        query = query.filter(NotificationLog.status == status_filter.upper())
    if template_code:
        query = query.filter(NotificationLog.template_code == template_code)
    if recipient:
        query = query.filter(NotificationLog.recipient == recipient)
    query = query.order_by(NotificationLog.created_at.desc())

    items, total = paginate(query, limit=limit, offset=offset)
    return PageOut(items=[NotificationLogOut.model_validate(n) for n in items], total=total, limit=limit, offset=offset)
