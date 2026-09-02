"""
Subscription lifecycle (spec sections 19-22, 38-43).

The "one active subscription per customer per application" rule (section 22)
is enforced at the DB level with a partial unique index (Postgres only,
added in the Alembic migration: unique on (customer_id, application_id)
WHERE status = 'ACTIVE') AND re-checked in application logic inside a DB
transaction before activating - belt and suspenders against race conditions
(spec section 67).

Free trial follow-up: "one credentials can take only one trial lifetime" is
enforced the same way - a second partial unique index on
(customer_id, application_id) WHERE is_trial = true (no status filter, so a
CANCELLED/EXPIRED trial still counts), backed by an application-level
pre-check (assert_trial_not_already_used in app.subscriptions.service) AND
an IntegrityError catch around the flush in create_pending_subscription()
that translates a race-lost insert into a clean TrialAlreadyUsed (409)
rather than a raw DB error - explicitly requested belt-and-suspenders
against "multiple trial scripts fired... unnecessary dumping".
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, JSON, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin
from app.core.enums import ProvisioningStatus, SubscriptionStatus


class Subscription(Base, TimestampMixin):
    __tablename__ = "subscriptions"
    __table_args__ = (
        # Spec section 22: one active subscription per customer per application.
        # Postgres partial unique index - only rows with status='ACTIVE' are
        # constrained, so history (CANCELLED/EXPIRED rows) can accumulate freely.
        Index(
            "uq_one_active_subscription_per_customer_application",
            "customer_id",
            "application_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
        # Spec follow-up: one trial ever, for the customer's full lifetime -
        # deliberately NOT scoped to status, unlike the index above.
        Index(
            "uq_one_trial_subscription_per_customer_application",
            "customer_id",
            "application_id",
            unique=True,
            postgresql_where=text("is_trial = true"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subscription_id: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)

    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False, index=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), nullable=False, index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"), nullable=False, index=True)

    status: Mapped[str] = mapped_column(
        String(20), default=SubscriptionStatus.PENDING_PAYMENT.value, nullable=False, index=True
    )
    provisioning_status: Mapped[str] = mapped_column(
        String(20), default=ProvisioningStatus.NOT_STARTED.value, nullable=False
    )

    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Denormalized copy of plan.is_trial at creation time - needed because a
    # Postgres partial-unique-index predicate can only reference columns on
    # the index's own table, so the one-trial-per-lifetime index above can't
    # reference plans.is_trial directly.
    is_trial: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    customer: Mapped["Customer"] = relationship(back_populates="subscriptions")
    plan: Mapped["Plan"] = relationship()
    history: Mapped[list["SubscriptionHistory"]] = relationship(
        back_populates="subscription", cascade="all, delete-orphan", order_by="SubscriptionHistory.occurred_at"
    )
    payment_transactions: Mapped[list["PaymentTransaction"]] = relationship(back_populates="subscription")


class SubscriptionHistory(Base, TimestampMixin):
    """Append-only audit trail of every lifecycle transition (used to render
    'Subscription History' in customer/admin portals, spec sections 46, 53)."""
    __tablename__ = "subscription_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subscription_id: Mapped[int] = mapped_column(ForeignKey("subscriptions.id"), nullable=False, index=True)

    event_type: Mapped[str] = mapped_column(String(30), nullable=False)  # SubscriptionEventType value
    from_plan_id: Mapped[int | None] = mapped_column(ForeignKey("plans.id"), nullable=True)
    to_plan_id: Mapped[int | None] = mapped_column(ForeignKey("plans.id"), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    subscription: Mapped["Subscription"] = relationship(back_populates="history")
