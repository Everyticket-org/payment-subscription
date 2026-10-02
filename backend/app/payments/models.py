"""
Payment transactions + gateway config (spec sections 23-28).

Idempotency (section 28) is enforced via:
  - unique(gateway, gateway_transaction_id) so the same gateway callback
    replayed twice maps to the same row
  - unique(idempotency_key) for client-initiated payment creation
Both are enforced at the DB level, not just in application code.
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin
from app.core.enums import PaymentStatus


class PaymentTransaction(Base, TimestampMixin):
    __tablename__ = "payment_transactions"
    __table_args__ = (
        UniqueConstraint("gateway", "gateway_transaction_id", name="uq_gateway_transaction"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_id: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False, index=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id"), nullable=False, index=True)
    # The plan this payment is FOR - equal to subscription.plan_id at
    # creation time for NEW/RENEWAL, but the *target* plan (different from
    # subscription.plan_id, which only changes on success) for
    # UPGRADE/DOWNGRADE. PaymentService uses this + payment_type to decide
    # what to do with the subscription once the payment succeeds.
    target_plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"), nullable=False, index=True)

    gateway: Mapped[str] = mapped_column(String(50), nullable=False)  # mock | payu | ...
    gateway_transaction_id: Mapped[str | None] = mapped_column(String(150), nullable=True, index=True)

    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)
    payment_type: Mapped[str] = mapped_column(String(20), nullable=False)  # PaymentType value

    status: Mapped[str] = mapped_column(
        String(20), default=PaymentStatus.INITIATED.value, nullable=False, index=True
    )

    request_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    response_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    raw_gateway_response: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    subscription: Mapped["Subscription"] = relationship(back_populates="payment_transactions")
    # Convenience read-only relationships for the admin API (spec section 51
    # 'Payments' module) - PaymentTransaction only ever needs to WRITE
    # customer_id/target_plan_id as plain FKs (see app.payments.service), so
    # these were not needed until admin list/detail views wanted to render
    # the customer_id/plan_code without an extra query per row.
    customer: Mapped["Customer"] = relationship()
    target_plan: Mapped["Plan"] = relationship()


class PaymentEvent(Base, TimestampMixin):
    """Append-only history of everything that happened to one payment:
    where it was started, the surl/furl PayU was told to use, every
    browser return / server webhook / reconciliation check that arrived,
    and what we did with each (app.payments.events). Never updated or
    deleted except by the retention purge
    (settings.PAYMENT_EVENT_RETENTION_DAYS).

    transaction_id is a plain string, not a foreign key, so callbacks for
    an unknown or missing txnid can be recorded too."""
    __tablename__ = "payment_events"
    # created_at: the retention purge and the reconciliation backoff both
    # filter on it.
    __table_args__ = (Index("ix_payment_events_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_id: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    # PaymentEventType value: INITIATED | BROWSER_RETURN | WEBHOOK | STATUS_CHECK | RECONCILE
    event_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    # Where the payment was started: subscribe | portal_upgrade | portal_downgrade | portal_renew
    channel: Mapped[str | None] = mapped_column(String(30), nullable=True)
    endpoint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Origin (or Referer) header of the request that started the payment.
    initiated_from: Mapped[str | None] = mapped_column(String(500), nullable=True)
    surl_sent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    furl_sent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    return_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    gateway_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    gateway_transaction_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    hash_verified: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # PaymentEventResult value - what we did with this event.
    result: Mapped[str] = mapped_column(String(40), nullable=False)
    # Sanitised gateway payload (allow-listed keys only, never the hash).
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class PaymentGatewayConfig(Base, TimestampMixin):
    """
    Per-application gateway configuration (spec section 74). `credentials`
    holds non-highly-sensitive overrides only; production merchant
    key/salt should come from environment variables (settings.PAYU_*), not
    this table, per spec section 81.
    """
    __tablename__ = "payment_gateway_configs"
    __table_args__ = (
        UniqueConstraint("application_id", "gateway_code", name="uq_application_gateway"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), nullable=False, index=True)
    gateway_code: Mapped[str] = mapped_column(String(50), nullable=False)  # mock | payu
    mode: Mapped[str] = mapped_column(String(20), default="test", nullable=False)  # test | live
    credentials: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    active: Mapped[bool] = mapped_column(Integer, default=1, nullable=False)
