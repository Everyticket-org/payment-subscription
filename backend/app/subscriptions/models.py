"""
Subscription lifecycle (spec sections 19-22, 38-43).

The "one active subscription per customer per application" rule (section 22)
is enforced at the DB level AND re-checked in application logic inside a DB
transaction before activating - belt and suspenders against race conditions
(spec section 67).

Free trial follow-up: "one credentials can take only one trial lifetime" is
enforced the same way - a second constraint that also covers
CANCELLED/EXPIRED trials (no status filter, unlike the one above), backed by
an application-level pre-check (assert_trial_not_already_used in
app.subscriptions.service) AND an IntegrityError catch around the flush in
create_pending_subscription() that translates a race-lost insert into a
clean TrialAlreadyUsed (409) rather than a raw DB error - explicitly
requested belt-and-suspenders against "multiple trial scripts fired...
unnecessary dumping".

2026-09-13 follow-up ("change database to mysql"): both constraints used to
be Postgres-only partial unique indexes (unique on (customer_id,
application_id) WHERE status = 'ACTIVE' / WHERE is_trial = true) - Postgres-
dialect-specific DDL that MySQL has no equivalent for at all (no partial/
filtered unique index support, in any version). Replaced with a portable
generated-column trick instead: `active_slot`/`trial_slot` are computed
columns that are 1 when the row matches the condition and NULL otherwise: a
plain unique index over (customer_id, application_id, that column) then
enforces the same rule, because every SQL dialect here (MySQL, Postgres,
SQLite) treats NULL as distinct from every other NULL in a unique index -
only rows where the generated column is actually 1 ever collide. This is
also why history (CANCELLED/EXPIRED) rows still accumulate freely: their
active_slot is NULL, so they never collide with each other or with the one
ACTIVE row.
"""
from datetime import datetime

from sqlalchemy import Boolean, Computed, DateTime, ForeignKey, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin
from app.core.enums import ProvisioningStatus, SubscriptionStatus


class Subscription(Base, TimestampMixin):
    __tablename__ = "subscriptions"
    __table_args__ = (
        # Spec section 22: one active subscription per customer per
        # application - see the module docstring for how active_slot makes
        # this a full (non-partial) unique index work like a partial one.
        Index(
            "uq_one_active_subscription_per_customer_application",
            "customer_id",
            "application_id",
            "active_slot",
            unique=True,
        ),
        # Spec follow-up: one trial ever, for the customer's full lifetime -
        # deliberately NOT scoped to status, unlike the index above (see
        # trial_slot's own CASE expression below).
        Index(
            "uq_one_trial_subscription_per_customer_application",
            "customer_id",
            "application_id",
            "trial_slot",
            unique=True,
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
    # unique-index predicate/generated column can only reference columns on
    # the index's own table, so the one-trial-per-lifetime index above can't
    # reference plans.is_trial directly.
    is_trial: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Generated columns backing the two unique indexes above - see the
    # module docstring. NULL unless the row matches the condition, so only
    # matching rows are ever constrained against each other.
    active_slot: Mapped[int | None] = mapped_column(
        Integer, Computed("CASE WHEN status = 'ACTIVE' THEN 1 ELSE NULL END", persisted=True), nullable=True
    )
    trial_slot: Mapped[int | None] = mapped_column(
        Integer, Computed("CASE WHEN is_trial = 1 THEN 1 ELSE NULL END", persisted=True), nullable=True
    )

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
