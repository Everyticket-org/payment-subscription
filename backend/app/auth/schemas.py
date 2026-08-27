"""Pydantic schemas for admin auth (spec section 12)."""
from pydantic import BaseModel, EmailStr


class AdminLoginRequest(BaseModel):
    email: EmailStr
    password: str


class AdminLoginResponse(BaseModel):
    mfa_required: bool
    pre_mfa_token: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str = "bearer"


class AdminMfaVerifyRequest(BaseModel):
    pre_mfa_token: str
    code: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class AdminUserOut(BaseModel):
    email: str
    full_name: str
    is_active: bool
    mfa_enabled: bool
    roles: list[str] = []
