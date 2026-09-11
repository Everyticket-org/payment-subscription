"""Server-side validation of a customer's registration_data submission
against this application's currently-active RegistrationFormField
definitions (spec section 18).

Added per Vishal's follow-up: "For forms - give one more option for
validation by Regex and validation message fields to be set." This
enforces ONLY the new validation_pattern/validation_message pair -
deliberately not "required" as well, even though that flag is *also*
never enforced server-side today (only via the public form's HTML5
`required` attribute, which a direct API call bypasses). Turning on
"required" enforcement here would be a much larger, separate behavior
change - the seeded application already has two required fields
(museum_name, contact_person) that dozens of existing tests subscribe
without providing, and real integrations that built against the current,
lenient behavior would start getting 422s with no warning. That's worth
raising with Vishal as its own explicit decision, not bundling in here.
"""
import re

from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.forms.models import RegistrationFormField


class RegistrationDataInvalid(AppError):
    http_status = 422
    error_code = "REGISTRATION_DATA_INVALID"


def _is_blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def validate_registration_data(db: Session, *, application_id: int, registration_data: dict) -> None:
    """Raises RegistrationDataInvalid (422) on the first pattern
    violation found, checking active fields in display_order so the
    error matches the order a customer would fill the form in. Only
    ACTIVE fields with a configured validation_pattern are checked, and
    only when a value was actually submitted - an unfilled field (required
    or not) is left to whatever enforcement already exists for it today
    (the public form's HTML5 `required` attribute); this function does
    not newly enforce `required` itself - see the module docstring."""
    fields = (
        db.query(RegistrationFormField)
        .filter(
            RegistrationFormField.application_id == application_id,
            RegistrationFormField.active.is_(True),
            RegistrationFormField.validation_pattern.isnot(None),
        )
        .order_by(RegistrationFormField.display_order)
        .all()
    )
    for field in fields:
        value = registration_data.get(field.field_key)
        if _is_blank(value):
            continue  # nothing submitted for this field - nothing to pattern-check
        try:
            matched = re.fullmatch(field.validation_pattern, str(value)) is not None
        except re.error:
            # A pattern that somehow got stored invalid (e.g. edited
            # directly in the DB, bypassing the schema's own
            # regex-compile check) must never 500 a real customer's
            # subscribe call - skip enforcing it rather than crash.
            continue
        if not matched:
            raise RegistrationDataInvalid(field.validation_message or f"{field.label} is not valid")
