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

check_duplicate_registration_data() (added per Vishal's later follow-up:
"Add one more checkbox to validate duplication (it means any record have
similar value then it will not allow user to enter same name) &
Validation message for that duplication also should be configured") is a
separate function, deliberately not folded into validate_registration_data()
above: the regex check needs nothing but the submitted data and runs
before a customer identity is even resolved (app.api.v1.public.subscribe),
while the duplicate check needs to know WHICH customer is submitting, so
it can exclude that customer's own prior rows - a repurchase/renewal
re-submitting the same data it already has on file must never be flagged
as a duplicate of itself.

Plan-specific fields (RegistrationFormField.plan_codes, 2026-10 Custom
plan follow-up) are the one exception to "required is never enforced
here": they're new, admin-opted-in questions such as a Custom plan's
expected monthly tickets / average ticket price, with no existing callers
that could start breaking, and the whole point of them is to collect the
answers needed to serve that plan - so a missing required plan-specific
answer is rejected with 422. General fields keep the lenient behaviour.
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


def _normalize(value: object) -> str:
    return str(value).strip().lower()


def is_plan_specific(field: RegistrationFormField) -> bool:
    """True for a "Show only for plans" question (non-empty plan_codes)."""
    return bool(field.plan_codes)


def field_applies_to_plan(field: RegistrationFormField, plan_code: str | None) -> bool:
    """A general field applies to every plan; a plan-specific one only to
    the plan_codes it lists (case-insensitive). With no plan_code at all,
    only general fields apply."""
    if not is_plan_specific(field):
        return True
    if not plan_code:
        return False
    return plan_code.upper() in {str(code).upper() for code in field.plan_codes}


def fields_for_plan(
    db: Session, *, application_id: int, plan_code: str | None, plan_specific_only: bool = False
) -> list[RegistrationFormField]:
    """Active fields that apply to plan_code, in display_order. Filtered in
    Python rather than with a JSON-column query so it behaves identically on
    SQLite (tests) and MySQL (production) - same reasoning as
    _duplicate_exists() below; a registration form is a handful of rows."""
    fields = (
        db.query(RegistrationFormField)
        .filter(
            RegistrationFormField.application_id == application_id,
            RegistrationFormField.active.is_(True),
        )
        .order_by(RegistrationFormField.display_order)
        .all()
    )
    return [
        field
        for field in fields
        if field_applies_to_plan(field, plan_code) and (is_plan_specific(field) or not plan_specific_only)
    ]


def filter_registration_data_for_plan(
    db: Session, *, application_id: int, plan_code: str | None, registration_data: dict
) -> dict:
    """Drops answers to plan-specific questions that belong to a DIFFERENT
    plan (e.g. a customer filled the Custom questions, then switched to
    Starter before submitting), so they're never stored against or sent in
    the webhook for the wrong plan. Every other key - general fields and
    any key with no matching field - passes through unchanged, preserving
    the existing lenient behaviour."""
    if not registration_data:
        return {}
    foreign_keys = {
        field.field_key
        for field in db.query(RegistrationFormField)
        .filter(RegistrationFormField.application_id == application_id)
        .all()
        if is_plan_specific(field) and not field_applies_to_plan(field, plan_code)
    }
    return {key: value for key, value in registration_data.items() if key not in foreign_keys}


def plan_specific_answers(
    db: Session, *, application_id: int, plan_code: str | None, registration_data: dict
) -> dict:
    """Only the answers to plan_code's plan-specific questions - what gets
    stored for a plan change on an EXISTING subscription, where the
    general (first-signup) registration data is already on file."""
    keys = {
        field.field_key
        for field in fields_for_plan(db, application_id=application_id, plan_code=plan_code, plan_specific_only=True)
    }
    return {key: value for key, value in (registration_data or {}).items() if key in keys}


def validate_registration_data(
    db: Session, *, application_id: int, registration_data: dict, plan_code: str | None = None
) -> None:
    """Raises RegistrationDataInvalid (422) on the first violation found,
    checking the active fields that apply to plan_code in display_order so
    the error matches the order a customer would fill the form in:
    - a required PLAN-SPECIFIC field with no value (see module docstring);
    - a submitted value that doesn't match the field's validation_pattern.
    An unfilled GENERAL field (required or not) is left to whatever
    enforcement already exists for it today (the public form's HTML5
    `required` attribute) - see the module docstring."""
    for field in fields_for_plan(db, application_id=application_id, plan_code=plan_code):
        value = registration_data.get(field.field_key)
        if _is_blank(value):
            if field.required and is_plan_specific(field):
                raise RegistrationDataInvalid(f"{field.label} is required")
            continue  # nothing submitted for this field - nothing to pattern-check
        if not field.validation_pattern:
            continue
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


def _duplicate_exists(
    db: Session, *, application_id: int, field_key: str, value: object, exclude_customer_id: int | None
) -> bool:
    """Looks for another customer's registration data with a
    case-insensitive, whitespace-trimmed match on this field_key's value.
    Compared in Python rather than as a JSON-column query so the check
    behaves identically on SQLite (tests) and Postgres (production) - see
    tests/conftest.py's module docstring on why this app avoids
    dialect-specific SQL in its test-covered code paths. This app's scale
    (a subscription platform, not a mass-signup product) makes scanning
    every existing submission for the application an acceptable cost;
    revisit with a real query (e.g. a generated column + index) if that
    ever stops being true."""
    from app.customers.models import CustomerRegistrationData  # local import - avoids a customers<->forms import cycle

    normalized = _normalize(value)
    if not normalized:
        return False
    query = db.query(CustomerRegistrationData).filter(
        CustomerRegistrationData.application_id == application_id,
    )
    if exclude_customer_id is not None:
        query = query.filter(CustomerRegistrationData.customer_id != exclude_customer_id)
    for row in query.all():
        existing = row.data.get(field_key) if isinstance(row.data, dict) else None
        if not _is_blank(existing) and _normalize(existing) == normalized:
            return True
    return False


def check_duplicate_registration_data(
    db: Session,
    *,
    application_id: int,
    registration_data: dict,
    exclude_customer_id: int | None = None,
    plan_code: str | None = None,
) -> None:
    """Raises RegistrationDataInvalid (422) on the first field whose
    submitted value already exists on another customer's registration
    data for this application. Only ACTIVE fields with check_duplicate=True
    are checked, and only when a non-blank value was actually submitted.
    exclude_customer_id should be the submitting customer's own id (once
    known) so a repurchase/renewal re-submitting data it already has on
    file is never flagged as a duplicate of itself - see the module
    docstring for why this is a separate function from
    validate_registration_data() above. Only fields that apply to plan_code
    are checked (see fields_for_plan)."""
    fields = [
        field
        for field in fields_for_plan(db, application_id=application_id, plan_code=plan_code)
        if field.check_duplicate
    ]
    for field in fields:
        value = registration_data.get(field.field_key)
        if _is_blank(value):
            continue  # nothing submitted for this field - nothing to check
        if _duplicate_exists(
            db,
            application_id=application_id,
            field_key=field.field_key,
            value=value,
            exclude_customer_id=exclude_customer_id,
        ):
            raise RegistrationDataInvalid(
                field.duplicate_message or f"{field.label} already exists. Please use a different value."
            )
