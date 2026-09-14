"""
Outbound webhook events + delivery tracking (spec sections 34-37).

WebhookEvent = the internal domain event (subscription.activated, etc.),
unique on event_id so it is never processed/sent twice (section 36).
WebhookDelivery = one delivery attempt record per destination, with retry
bookkeeping (section 35).
"""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin
from app.core.enums import WebhookDeliveryStatus


class WebhookEvent(Base, TimestampMixin):
    __tablename__ = "webhook_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # subscription.activated, ...
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)  # subscription | payment
    entity_id: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    # Human-readable "why was this webhook called" reference, e.g. the
    # customer_id it concerns (Vishal: "Keep reference of why that webhook
    # called and show in logs - like for which customer it has been
    # called"). Set explicitly by each queue_event() caller from the
    # subscription/customer already in scope there, rather than derived
    # from payload at read time - several event types (renewed, expiry,
    # cancelled, archive) only guarantee subscription_id in their payload,
    # not customer_id, so parsing payload would be unreliable. Nullable:
    # synthetic/test events (the admin webhook failure simulator) have no
    # real customer to reference.
    customer_reference: Mapped[str | None] = mapped_column(String(60), nullable=True)

    deliveries: Mapped[list["WebhookDelivery"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )


class WebhookDelivery(Base, TimestampMixin):
    __tablename__ = "webhook_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    webhook_event_id: Mapped[int] = mapped_column(ForeignKey("webhook_events.id"), nullable=False, index=True)
    destination_application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id"), nullable=False, index=True
    )
    destination_url: Mapped[str] = mapped_column(String(500), nullable=False)

    status: Mapped[str] = mapped_column(
        String(20), default=WebhookDeliveryStatus.PENDING.value, nullable=False, index=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    # Added per Vishal's follow-up ("not logging headers, statuscode, etc..
    # from API"): the exact headers this app sent (Content-Type,
    # X-Webhook-Signature, any admin-supplied extras) and the destination's
    # response headers, captured on every attempt - real dispatch, the
    # admin ad-hoc test send, and the connectivity-check verify action -
    # so a delivery row is a complete record of the actual HTTP exchange,
    # not just its body/status. Both nullable (never set on an attempt
    # that raised before a response came back, e.g. a connection error).
    request_headers: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    response_headers: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # The exact request body sent on this attempt (Vishal: "Show request
    # data as well where currently showing response data only"). Persisted
    # genuinely rather than reconstructed from event.payload at read time,
    # because real dispatched deliveries wrap payload in an
    # {event_type, payload} envelope (build_wire_body) while ad-hoc/test
    # sends transmit the raw payload unwrapped - reconstruction from
    # event.payload alone would be wrong for ad-hoc entries. Nullable:
    # never set on an attempt that raised before a request body was built.
    request_body: Mapped[str | None] = mapped_column(String(4000), nullable=True)

    # Added per Vishal ("Log webhook call time and response completion
    # time"): attempt_started_at is when this attempt's outbound HTTP
    # call actually began (set the moment the attempt starts, before
    # anything can go wrong); last_attempt_at below already doubles as
    # the response completion time (it was already set right after the
    # call finishes, success or failure); duration_ms is simply the
    # elapsed time between the two, measured with a monotonic clock so
    # it's never skewed by wall-clock adjustments. All three nullable -
    # never set on a delivery that's still only PENDING and has never
    # actually been attempted yet.
    attempt_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    event: Mapped["WebhookEvent"] = relationship(back_populates="deliveries")

    # Convenience read-only proxies onto the parent event, so the admin
    # logs UI can show "why this webhook was called" (event type, entity,
    # customer) directly on each delivery row without the API layer having
    # to hand-join/flatten WebhookEvent fields itself. Picked up
    # automatically by Pydantic's `from_attributes=True` schemas as long as
    # a same-named field is declared there.
    @property
    def event_type(self) -> str:
        return self.event.event_type

    @property
    def entity_type(self) -> str:
        return self.event.entity_type

    @property
    def entity_id(self) -> str:
        return self.event.entity_id

    @property
    def customer_reference(self) -> str | None:
        return self.event.customer_reference
