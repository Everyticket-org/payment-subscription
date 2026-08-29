"""Admin Audit Logs (spec section 56, 51) - read-only, append-only trail
already written by app.audit.service.record from every mutating admin
action in this file set (plan changes, customer suspend/activate, webhook
retries, template edits, and MFA bypass in app.auth.service)."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.v1.admin_common import DEFAULT_LIMIT, MAX_LIMIT, PageOut, paginate
from app.audit.models import AuditLog
from app.audit.schemas import AuditLogOut
from app.auth.deps import require_permission
from app.auth.models import AdminUser

router = APIRouter(prefix="/audit-logs", tags=["admin-audit"])


@router.get("", response_model=PageOut[AuditLogOut])
def list_audit_logs(
    entity_type: str | None = Query(default=None),
    entity_id: str | None = Query(default=None),
    actor: str | None = Query(default=None),
    action: str | None = Query(default=None),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(require_permission("AUDIT_VIEW")),
):
    query = db.query(AuditLog)
    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    if entity_id:
        query = query.filter(AuditLog.entity_id == entity_id)
    if actor:
        query = query.filter(AuditLog.actor == actor)
    if action:
        query = query.filter(AuditLog.action == action)
    query = query.order_by(AuditLog.created_at.desc())

    items, total = paginate(query, limit=limit, offset=offset)
    return PageOut(items=[AuditLogOut.model_validate(a) for a in items], total=total, limit=limit, offset=offset)
