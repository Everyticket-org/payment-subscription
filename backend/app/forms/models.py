"""Dynamic registration form field definitions (spec section 18)."""
from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, TimestampMixin


class RegistrationFormField(Base, TimestampMixin):
    __tablename__ = "registration_form_fields"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), nullable=False, index=True)

    field_key: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g. museum_name
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    field_type: Mapped[str] = mapped_column(String(20), nullable=False)  # FormFieldType value
    required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    validation_rules: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # e.g. {"pattern": "..."}
    placeholder: Mapped[str | None] = mapped_column(String(255), nullable=True)
    help_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    options: Mapped[list | None] = mapped_column(JSON, nullable=True)  # for dropdown/radio/checkbox
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    application: Mapped["Application"] = relationship(back_populates="form_fields")
