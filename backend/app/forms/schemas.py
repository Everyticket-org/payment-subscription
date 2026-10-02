"""Pydantic schemas for dynamic registration-form fields (spec section 18,
51 'Registration Form' admin module).

validation_pattern/validation_message (added per Vishal's follow-up:
"give one more option for validation by Regex and validation message
fields to be set") are validated here at the API boundary - an invalid
regex is rejected with a clear 422 the moment an admin tries to save it,
rather than only failing later, silently, the first time a customer's
submission is checked against it (app.forms.validation).

check_duplicate/duplicate_message (added per Vishal's follow-up: "Add
one more checkbox to validate duplication... & Validation message for
that duplication also should be configured") need no schema-level
validation of their own - check_duplicate is a plain boolean and
duplicate_message a plain string - the actual duplicate lookup happens
at submit time in app.forms.validation.check_duplicate_registration_data()."""
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _check_regex(pattern: str | None) -> str | None:
    if pattern is not None:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"'{pattern}' is not a valid regular expression: {exc}") from exc
    return pattern


def _normalize_plan_codes(plan_codes: list[str] | None) -> list[str] | None:
    """"Show only for plans" - upper-cased, trimmed, de-duplicated (order
    kept). An empty list means "every plan" and is stored as None, the same
    as never setting it. Whether each code is a real plan of this
    application is checked in app.api.v1.admin_forms (needs the DB)."""
    if plan_codes is None:
        return None
    normalized: list[str] = []
    for code in plan_codes:
        code = str(code).strip().upper()
        if code and code not in normalized:
            normalized.append(code)
    return normalized or None


class RegistrationFormFieldOut(BaseModel):
    """Public shape (spec section 8's dynamic form renderer) - active
    fields only, no internal id. validation_pattern/validation_message
    are included so the public form can also validate client-side (a
    convenience for the customer, not the source of truth - the backend
    always re-checks on submit). check_duplicate/duplicate_message are
    included too for the same reason, though the frontend has no way to
    pre-check duplication itself (that requires querying other
    customers' data) - the backend's check_duplicate_registration_data()
    is the actual source of truth for this one."""
    model_config = ConfigDict(from_attributes=True)
    field_key: str
    label: str
    field_type: str
    required: bool
    validation_rules: dict | None = None
    validation_pattern: str | None = None
    validation_message: str | None = None
    check_duplicate: bool = False
    duplicate_message: str | None = None
    placeholder: str | None = None
    help_text: str | None = None
    options: list | None = None
    # None = general field (every plan, asked once at first signup); a list
    # of plan_codes = asked only for those plans - see
    # app.forms.models.RegistrationFormField.plan_codes.
    plan_codes: list[str] | None = None
    display_order: int


class RegistrationFormFieldAdminOut(RegistrationFormFieldOut):
    id: int
    active: bool


class RegistrationFormFieldCreate(BaseModel):
    field_key: str = Field(min_length=1, max_length=100, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=255)
    field_type: str = Field(
        pattern="^(text|email|phone|number|dropdown|radio|checkbox|textarea|date|url|file)$"
    )
    required: bool = False
    validation_rules: dict | None = None
    validation_pattern: str | None = Field(default=None, max_length=500)
    validation_message: str | None = Field(default=None, max_length=255)
    check_duplicate: bool = False
    duplicate_message: str | None = Field(default=None, max_length=255)
    placeholder: str | None = Field(default=None, max_length=255)
    help_text: str | None = Field(default=None, max_length=500)
    options: list | None = None
    plan_codes: list[str] | None = None
    display_order: int = 0

    _check_validation_pattern = field_validator("validation_pattern")(_check_regex)
    _normalize_plan_codes = field_validator("plan_codes")(_normalize_plan_codes)


class RegistrationFormFieldUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=255)
    required: bool | None = None
    validation_rules: dict | None = None
    validation_pattern: str | None = Field(default=None, max_length=500)
    validation_message: str | None = Field(default=None, max_length=255)
    check_duplicate: bool | None = None
    duplicate_message: str | None = Field(default=None, max_length=255)
    placeholder: str | None = Field(default=None, max_length=255)
    help_text: str | None = Field(default=None, max_length=500)
    options: list | None = None
    # Send [] to turn a plan-specific question back into a general one.
    plan_codes: list[str] | None = None
    display_order: int | None = None
    active: bool | None = None

    _check_validation_pattern = field_validator("validation_pattern")(_check_regex)
    _normalize_plan_codes = field_validator("plan_codes")(_normalize_plan_codes)
