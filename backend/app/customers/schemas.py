"""Pydantic schemas for customers + dynamic registration data (spec sections 7, 18)."""
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class SubscribeRequest(BaseModel):
    """
    Public subscription request body (spec section 19). `registration_data`
    holds the dynamic form submission, keyed by RegistrationFormField.field_key.

    NOTE: this endpoint currently implements the NO_EXISTING_CUSTOMER path
    only (always creates a new customer). Duplicate customer detection +
    OTP verification (spec sections 9-11) is not yet wired in - see
    docs/implementation-status.md for what's tracked as a follow-up.
    """
    email: EmailStr
    mobile: str = Field(min_length=6, max_length=20)
    registration_data: dict = Field(default_factory=dict)


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    customer_id: str
    email: str
    mobile: str
    email_verified: bool
    mobile_verified: bool
    status: str
