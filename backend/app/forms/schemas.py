"""Pydantic schemas for dynamic registration-form fields (spec section 18,
51 'Registration Form' admin module).

validation_pattern/validation_message (added per Vishal's follow-up:
"give one more option for validation by Regex and validation message
fields to be set") are validated here at the API boundary - an invalid
regex is rejected with a clear 422 the moment an admin tries to save it,
rather than only failing later, silently, the first time a customer's
submission is checked against it (app.forms.validation)."""
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _check_regex(pattern: str | None) -> str | None:
    if pattern is not None:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"'{pattern}' is not a valid regular expression: {exc}") from exc
    return pattern


class RegistrationFormFieldOut(BaseModel):
    """Public shape (spec section 8's dynamic form renderer) - active
    fields only, no internal id. validation_pattern/validation_message
    are included so the public form can also validate client-side (a
    convenience for the customer, not the source of truth - the backend
    always re-checks on submit)."""
    model_config = ConfigDict(from_attributes=True)
    field_key: str
    label: str
    field_type: str
    required: bool
    validation_rules: dict | None = None
    validation_pattern: str | None = None
    validation_message: str | None = None
    placeholder: str | None = None
    help_text: str | None = None
    options: list | None = None
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
    placeholder: str | None = Field(default=None, max_length=255)
    help_text: str | None = Field(default=None, max_length=500)
    options: list | None = None
    display_order: int = 0

    _check_validation_pattern = field_validator("validation_pattern")(_check_regex)


class RegistrationFormFieldUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=255)
    required: bool | None = None
    validation_rules: dict | None = None
    validation_pattern: str | None = Field(default=None, max_length=500)
    validation_message: str | None = Field(default=None, max_length=255)
    placeholder: str | None = Field(default=None, max_length=255)
    help_text: str | None = Field(default=None, max_length=500)
    options: list | None = None
    display_order: int | None = None
    active: bool | None = None

    _check_validation_pattern = field_validator("validation_pattern")(_check_regex)
