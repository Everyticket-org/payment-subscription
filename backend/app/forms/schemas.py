"""Pydantic schemas for dynamic registration-form fields (spec section 18,
51 'Registration Form' admin module)."""
from pydantic import BaseModel, ConfigDict, Field


class RegistrationFormFieldOut(BaseModel):
    """Public shape (spec section 8's dynamic form renderer) - active
    fields only, no internal id."""
    model_config = ConfigDict(from_attributes=True)
    field_key: str
    label: str
    field_type: str
    required: bool
    validation_rules: dict | None = None
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
    placeholder: str | None = Field(default=None, max_length=255)
    help_text: str | None = Field(default=None, max_length=500)
    options: list | None = None
    display_order: int = 0


class RegistrationFormFieldUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=255)
    required: bool | None = None
    validation_rules: dict | None = None
    placeholder: str | None = Field(default=None, max_length=255)
    help_text: str | None = Field(default=None, max_length=500)
    options: list | None = None
    display_order: int | None = None
    active: bool | None = None
