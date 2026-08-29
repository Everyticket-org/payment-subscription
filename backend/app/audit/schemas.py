"""Pydantic schema for the audit trail (spec section 56, 51 'Audit Logs'
admin module)."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    actor: str
    action: str
    entity_type: str
    entity_id: str
    old_value: dict | None = None
    new_value: dict | None = None
    ip_address: str | None = None
    created_at: datetime
