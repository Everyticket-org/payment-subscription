"""FastAPI dependencies for authenticated admin/customer routes."""
from fastapi import Depends, Header
from jose import JWTError
from sqlalchemy.orm import Session

from app.auth.models import AdminUser
from app.core.database import get_db
from app.core.exceptions import Unauthorized
from app.core.security import decode_token


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("Missing or malformed Authorization header")
    return authorization.split(" ", 1)[1].strip()


def get_current_admin(
    authorization: str | None = Header(default=None), db: Session = Depends(get_db)
) -> AdminUser:
    token = _extract_bearer_token(authorization)
    try:
        payload = decode_token(token)
    except JWTError:
        raise Unauthorized("Invalid or expired token")

    if payload.get("type") != "access" or payload.get("token_kind") != "admin":
        raise Unauthorized("Invalid token")

    user = db.query(AdminUser).filter(AdminUser.email == payload.get("sub")).first()
    if user is None or not user.is_active:
        raise Unauthorized("Invalid or inactive admin user")
    return user


def get_current_customer_id(
    authorization: str | None = Header(default=None),
) -> str:
    """
    Resolves the caller's customer_id from a customer-scoped access token
    issued after OTP verification (see app.customers.service.issue_customer_token).
    Returns the public customer_id string (not the row) - callers look up
    the Customer row themselves, keeping this dependency DB-independent.
    """
    token = _extract_bearer_token(authorization)
    try:
        payload = decode_token(token)
    except JWTError:
        raise Unauthorized("Invalid or expired token")

    if payload.get("type") != "access" or payload.get("token_kind") != "customer":
        raise Unauthorized("Invalid token")

    customer_id = payload.get("sub")
    if not customer_id:
        raise Unauthorized("Invalid token")
    return customer_id


def get_current_customer_id_optional(
    authorization: str | None = Header(default=None),
) -> str | None:
    """Same as get_current_customer_id, but returns None when no
    Authorization header was sent at all (vs. raising) - used by endpoints
    like /public/plans/{code}/subscribe that accept either an identified
    (OTP-verified) customer or a brand-new-customer request body."""
    if not authorization:
        return None
    return get_current_customer_id(authorization=authorization)
