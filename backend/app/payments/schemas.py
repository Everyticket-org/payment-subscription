"""Pydantic schemas for payments (spec sections 23-28)."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PaymentTransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    transaction_id: str
    gateway: str
    amount: float
    currency: str
    status: str
    failure_reason: str | None = None
    # Populated only for redirect-based gateways (PayU) whose payment is
    # PENDING and needs the browser to POST to a hosted checkout page -
    # not an ORM attribute, so callers set this explicitly after
    # constructing the base object from the PaymentTransaction row (see
    # app/api/v1/public.py and customer.py). None for the mock gateway.
    checkout: dict | None = None


class MockCallbackRequest(BaseModel):
    """
    Simulated gateway callback (spec sections 24, 54 "TEST PAYMENT").
    `transaction_id` is our internal TXN-xxxx id; `scenario` drives what
    the mock gateway reports back through the same code path a real PayU
    callback would use.
    """
    transaction_id: str
    scenario: str  # SUCCESS | FAILED | PENDING | TIMEOUT


class PaymentAdminOut(BaseModel):
    """Admin list/detail row (spec section 51 'Payments' module, 53
    'do not allow unsafe editing of financial transaction history' - this
    is intentionally read-only, no corresponding Update schema exists)."""
    model_config = ConfigDict(from_attributes=False)
    transaction_id: str
    customer_id: str
    subscription_id: str
    plan_code: str
    gateway: str
    gateway_transaction_id: str | None = None
    amount: float
    currency: str
    payment_type: str
    status: str
    failure_reason: str | None = None
    created_at: datetime
    updated_at: datetime
    raw_gateway_response: dict | None = None
