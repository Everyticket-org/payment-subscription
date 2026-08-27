"""Audit log writer (spec section 56). Callers pass the same DB session
they're already using for the business change, so the audit row commits
atomically with it - never call db.commit() here, the caller owns that."""
from typing import Any

from sqlalchemy.orm import Session

from app.audit.models import AuditLog


def record(
    db: Session,
    *,
    actor: str,
    action: str,
    entity_type: str,
    entity_id: str,
    old_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        old_value=old_value,
        new_value=new_value,
        ip_address=ip_address,
    )
    db.add(entry)
    db.flush()
    return entry
