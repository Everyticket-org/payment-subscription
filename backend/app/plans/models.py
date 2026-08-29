"""Plans, plan features, plan transitions (spec sections 14, 15, 16)."""
from sqlalchemy import Boolean, ForeignKey, Integer, JSON, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin
from app.core.enums import PlanTransitionType


class Plan(Base, TimestampMixin):
    __tablename__ = "plans"
    __table_args__ = (
        UniqueConstraint("application_id", "plan_code", name="uq_application_plan_code"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), nullable=False, index=True)

    plan_code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # BASIC, PROFESSIONAL, ...
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="INR", nullable=False)
    billing_interval: Mapped[str] = mapped_column(String(20), default="month", nullable=False)  # month | year
    billing_frequency: Mapped[int] = mapped_column(Integer, default=1, nullable=False)  # every N intervals
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    application: Mapped["Application"] = relationship(back_populates="plans")
    features: Mapped[list["PlanFeature"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", order_by="PlanFeature.display_order"
    )

    @property
    def public_url_slug(self) -> str:
        """Public plan URL is /subscribe/{slug} (spec section 17)."""
        return self.plan_code.lower()


class PlanFeature(Base, TimestampMixin):
    __tablename__ = "plan_features"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"), nullable=False, index=True)
    feature_key: Mapped[str] = mapped_column(String(100), nullable=False)
    feature_label: Mapped[str] = mapped_column(String(255), nullable=False)
    feature_value: Mapped[str | None] = mapped_column(String(500), nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    plan: Mapped["Plan"] = relationship(back_populates="features")


class PlanTransition(Base, TimestampMixin):
    """
    Explicit allow-list of upgrade/downgrade paths (spec section 16).
    Absence of a row = transition not allowed.
    """
    __tablename__ = "plan_transitions"
    __table_args__ = (
        UniqueConstraint("from_plan_id", "to_plan_id", name="uq_plan_transition_pair"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), nullable=False, index=True)
    from_plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"), nullable=False, index=True)
    to_plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"), nullable=False, index=True)
    transition_type: Mapped[str] = mapped_column(String(20), nullable=False)  # UPGRADE | DOWNGRADE

    from_plan: Mapped["Plan"] = relationship(foreign_keys=[from_plan_id])
    to_plan: Mapped["Plan"] = relationship(foreign_keys=[to_plan_id])
