"""Pydantic schemas for notification templates + send log (spec sections
49-50, 51 'Email Logs' admin module)."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NotificationTemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    template_code: str
    channel: str
    subject: str
    body_html: str
    body_text: str | None = None
    active: bool


class NotificationTemplateUpdate(BaseModel):
    """Admin edit of an existing template (spec section 49-50). Templates
    are created only via app.core.seed - this pass does not add a create/
    delete admin endpoint since the template_code set the application
    actually sends is fixed in code (app.notifications.email.service call
    sites); admins can restyle/reword them, not invent new ones."""
    subject: str | None = Field(default=None, min_length=1, max_length=255)
    body_html: str | None = Field(default=None, min_length=1)
    body_text: str | None = None
    active: bool | None = None


class NotificationLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    template_code: str
    channel: str
    recipient: str
    status: str
    provider_response: str | None = None
    related_entity_type: str | None = None
    related_entity_id: str | None = None
    created_at: datetime
