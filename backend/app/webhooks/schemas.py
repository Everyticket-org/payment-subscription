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
    # Added per Vishal's follow-up ("not logging headers, statuscode,
    # etc.. from API") - the exact headers sent and received on this
    # attempt, so a delivery row is a complete record of the HTTP
    # exchange, not just its body/status.
    request_headers: dict | None = None
    response_headers: dict | None = None
    # Vishal: "Show request data as well where currently showing response
    # data only" - the exact request body sent on this attempt.
    request_body: str | None = None
    # Vishal: "Log webhook call time and response completion time" -
    # attempt_started_at is when this attempt's outbound call began;
    # last_attempt_at (below) doubles as when it completed;
    # duration_ms is the elapsed time between the two.
    attempt_started_at: datetime | None = None
    duration_ms: int | None = None
    last_attempt_at: datetime | None = None
    next_retry_at: datetime | None = None
    # Vishal: "Keep reference of why that webhook called and show in logs -
    # like for which customer it has been called" - proxied from the
    # parent WebhookEvent via a model @property, so this flat delivery row
    # already carries its own event context without a manual join.
    event_type: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    customer_reference: str | None = None


class WebhookEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=False)
    event_id: str
    event_type: str
    entity_type: str
    entity_id: str
    payload: dict
    created_at: datetime
    deliveries: list[WebhookDeliveryOut] = []
    customer_reference: str | None = None
