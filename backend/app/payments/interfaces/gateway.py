"""
Payment gateway abstraction (spec sections 23, 74).

SubscriptionService/PaymentService only ever talk to this interface -
never to a concrete gateway - so adding a new gateway (Razorpay, Stripe,
...) is: implement this interface, register it, configure credentials.
No changes to core subscription logic required.

Refund methods are intentionally omitted from V1's interface surface per
spec section 44 (refunds disabled) - they can be added back when V1's
"no refunds" rule changes.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class GatewayPaymentResult:
    """Normalized result shape every gateway adapter returns, regardless of
    the gateway's own wire format - this is what internal events (spec
    section 29) are derived from."""
    gateway: str
    gateway_transaction_id: str | None
    status: str  # PaymentStatus value: INITIATED | PENDING | SUCCESS | FAILED | CANCELLED | UNKNOWN
    amount: float
    currency: str
    raw_response: dict[str, Any]
    failure_reason: str | None = None


class PaymentGateway(ABC):
    """Every concrete gateway adapter (mock, PayU, ...) implements this."""

    code: str  # e.g. "mock", "payu"

    @abstractmethod
    def create_payment(
        self, *, transaction_id: str, amount: float, currency: str, metadata: dict[str, Any]
    ) -> GatewayPaymentResult:
        """Initiate a payment. For redirect-based gateways this typically
        returns a PENDING result plus a redirect URL in raw_response."""
        raise NotImplementedError

    @abstractmethod
    def get_payment_status(self, *, gateway_transaction_id: str) -> GatewayPaymentResult:
        """Server-side status poll - used as a fallback / reconciliation
        path, never relied on as the sole source of truth (section 25)."""
        raise NotImplementedError

    @abstractmethod
    def verify_payment(self, *, gateway_transaction_id: str, raw_response: dict[str, Any]) -> GatewayPaymentResult:
        """Server-side verification of a callback/webhook payload
        (signature/hash check where applicable). This - not the browser
        redirect - is what PaymentService treats as authoritative
        (spec sections 25, 28)."""
        raise NotImplementedError

    def create_recurring_payment(self, **kwargs: Any) -> GatewayPaymentResult:
        raise NotImplementedError(f"{self.code} gateway does not support recurring payments")

    def cancel_recurring_payment(self, **kwargs: Any) -> None:
        raise NotImplementedError(f"{self.code} gateway does not support recurring payments")

    @abstractmethod
    def verify_webhook(self, *, headers: dict[str, str], raw_body: bytes) -> bool:
        """Return True iff the inbound webhook's signature/authenticity
        checks out (spec section 34). Callers must reject (401) on False."""
        raise NotImplementedError

    @abstractmethod
    def process_webhook(self, *, payload: dict[str, Any]) -> GatewayPaymentResult:
        """Translate a verified gateway webhook payload into a normalized
        GatewayPaymentResult."""
        raise NotImplementedError
