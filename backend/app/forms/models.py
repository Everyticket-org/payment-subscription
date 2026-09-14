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
    validation_rules: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # legacy, unused - see validation_pattern/validation_message below
    # Regex a submitted value must fully match (re.fullmatch semantics,
    # same as the HTML5 `pattern` attribute) + the message shown when it
    # doesn't - see app.forms.validation.validate_registration_data().
    validation_pattern: Mapped[str | None] = mapped_column(String(500), nullable=True)
    validation_message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Per Vishal's follow-up ("add one more checkbox to validate
    # duplication... if any record have similar value then it will not
    # allow user to enter same name"): when set, a submitted value for
    # this field must not already exist on ANY OTHER customer's
    # registration data for this application (case-insensitive,
    # whitespace-trimmed comparison) - see
    # app.forms.validation.check_duplicate_registration_data().
    # duplicate_message is the error shown on a match, falling back to a
    # generic "<label> already exists" when unset - same pattern as
    # validation_message above.
    check_duplicate: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    duplicate_message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    placeholder: Mapped[str | None] = mapped_column(String(255), nullable=True)
    help_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    options: Mapped[list | None] = mapped_column(JSON, nullable=True)  # for dropdown/radio/checkbox
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    application: Mapped["Application"] = relationship(back_populates="form_fields")
