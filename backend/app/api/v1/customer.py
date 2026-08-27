"""Customer portal API (spec sections 46, 48, 61: /api/v1/customer/). Not
yet implemented - OTP-based direct access, SSO-based access, and the
portal's own subscription/payment/invoice views land in a follow-up (see
docs/implementation-status.md)."""
from fastapi import APIRouter

router = APIRouter(prefix="/customer", tags=["customer"])
