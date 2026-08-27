"""Pydantic schemas for customers, dynamic registration data, and
duplicate-detection/OTP (spec sections 7, 9-11, 18)."""
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class SubscribeRequest(BaseModel):
    """
    Public subscription request body (spec section 19). `registration_data`
    holds the dynamic form submission, keyed by RegistrationFormField.field_key.

    Two ways to identify the customer:
      - email + mobile in the body (brand-new customer path - only valid
        when POST /public/identify already reported "none", i.e. no
        existing customer).
      - an `Authorization: Bearer <customer token>` header, issued by
        POST /public/otp/verify after OTP verification (identified /
        returning customer path - e.g. repurchase after expiry).
    The API layer enforces that exactly one of these is actually used.
    """
    email: EmailStr | None = None
    mobile: str | None = Field(default=None, min_length=6, max_length=20)
    registration_data: dict = Field(default_factory=dict)


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    customer_id: str
    email: str
    mobile: str
    email_verified: bool
    mobile_verified: bool
    status: str


class IdentifyRequest(BaseModel):
    """Spec section 9: checked before a customer is allowed to register,
    so an existing customer visiting a public plan URL doesn't
    accidentally create a duplicate subscription."""
    email: EmailStr
    mobile: str = Field(min_length=6, max_length=20)


class IdentifyResponse(BaseModel):
    match_status: str  # "exact" | "conflict" | "none"
    otp_session_id: str | None = None
    # Only populated when TEST_MODE is true (no real SMS/email channel
    # exists yet - see app.auth.otp_service module docstring). Never
    # populated in production.
    debug_otp_code: str | None = None
    message: str


class OtpVerifyRequest(BaseModel):
    otp_session_id: str
    code: str


class OtpVerifyResponse(BaseModel):
    customer: CustomerOut
    access_token: str
    token_type: str = "bearer"
