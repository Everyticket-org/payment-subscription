"""Pydantic schemas for payments (spec sections 23-28)."""
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
