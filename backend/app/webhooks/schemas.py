"""Pydantic schemas for outbound webhook events/deliveries (spec sections
34-37, 51 'Webhook Logs' admin module)."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class WebhookDeliveryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    destination_url: str
    status: str
    attempt_count: int
    http_status: int | None = None
    response_body: str | None = None
    last_attempt_at: datetime | None = None
    next_retry_at: datetime | None = None


class WebhookEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=False)
    event_id: str
    event_type: str
    entity_type: str
    entity_id: str
    payload: dict
    created_at: datetime
    deliveries: list[WebhookDeliveryOut] = []
