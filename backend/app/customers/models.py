"""Customer identity (spec section 7) + dynamic registration data (section 18)."""
from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin
from app.core.enums import CustomerStatus


class Customer(Base, TimestampMixin):
    """
    customer_id (CUS-xxxx) is the PERMANENT primary identity (spec section 7).
    Email/mobile are identity ATTRIBUTES used for duplicate detection
    (section 9/10), never the permanent identifier.
    """
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)

    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    mobile: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mobile_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=CustomerStatus.ACTIVE.value, nullable=False)

    application_mappings: Mapped[list["CustomerApplicationMapping"]] = relationship(
        back_populates="customer"
    )
    subscriptions: Mapped[list["Subscription"]] = relationship(back_populates="customer")


class CustomerRegistrationData(Base, TimestampMixin):
    """
    Dynamic registration form submission (spec section 18). Keyed by the
    admin-configured RegistrationFormField.field_key -> submitted value.
    Kept as its own row per submission (not overwritten) so history of what
    was submitted at signup time is preserved even if the customer later
    edits profile data elsewhere.
    """
    __tablename__ = "customer_registration_data"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False, index=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), nullable=False, index=True)
    subscription_id: Mapped[int | None] = mapped_column(
        ForeignKey("subscriptions.id"), nullable=True, index=True
    )
    data: Mapped[dict] = mapped_column(JSON, nullable=False)  # {"museum_name": "CSMVS", ...}
