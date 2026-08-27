"""
Mock payment gateway (spec section 24).

Lets the whole subscription application be exercised end-to-end - manually
via the admin Testing module (section 54) or via pytest - without any real
PayU credentials. It implements the exact same PaymentGateway interface
PayU does, so PaymentService never knows the difference.
"""
from typing import Any

from app.payments.interfaces.gateway import GatewayPaymentResult, PaymentGateway

_SCENARIOS = {"SUCCESS", "FAILED", "PENDING", "TIMEOUT"}


class MockPaymentGateway(PaymentGateway):
    code = "mock"

    def create_payment(
        self, *, transaction_id: str, amount: float, currency: str, metadata: dict[str, Any]
    ) -> GatewayPaymentResult:
        # Mock "initiation" always succeeds in reaching the gateway; the
        # actual outcome is decided later by the simulated callback
        # (mirrors a real gateway: initiation != settlement).
        return GatewayPaymentResult(
            gateway=self.code,
            gateway_transaction_id=f"MOCK-{transaction_id}",
            status="INITIATED",
            amount=amount,
            currency=currency,
            raw_response={"mock": True, "transaction_id": transaction_id},
        )

    def get_payment_status(self, *, gateway_transaction_id: str) -> GatewayPaymentResult:
        # The mock gateway has no independent state store - status is only
        # ever driven by an explicit simulated callback (see process_webhook).
        return GatewayPaymentResult(
            gateway=self.code,
            gateway_transaction_id=gateway_transaction_id,
            status="UNKNOWN",
            amount=0,
            currency="INR",
            raw_response={"mock": True},
        )

    def verify_payment(self, *, gateway_transaction_id: str, raw_response: dict[str, Any]) -> GatewayPaymentResult:
        # Trust the raw_response we were handed (it came from our own
        # simulated callback, not an external network call).
        return self.process_webhook(payload=raw_response)

    def verify_webhook(self, *, headers: dict[str, str], raw_body: bytes) -> bool:
        # No signature scheme for the mock gateway - it's local-only and
        # never reachable from outside this process.
        return True

    def process_webhook(self, *, payload: dict[str, Any]) -> GatewayPaymentResult:
        scenario = payload.get("scenario", "SUCCESS")
        if scenario not in _SCENARIOS:
            scenario = "FAILED"

        status_map = {
            "SUCCESS": "SUCCESS",
            "FAILED": "FAILED",
            "PENDING": "PENDING",
            "TIMEOUT": "UNKNOWN",  # spec section 27: unknown states must never activate a subscription
        }
        failure_reason = None
        if scenario == "FAILED":
            failure_reason = "Simulated payment failure"
        elif scenario == "TIMEOUT":
            failure_reason = "Simulated gateway timeout - no definitive status received"

        return GatewayPaymentResult(
            gateway=self.code,
            gateway_transaction_id=payload.get("gateway_transaction_id"),
            status=status_map[scenario],
            amount=payload.get("amount", 0),
            currency=payload.get("currency", "INR"),
            raw_response=payload,
            failure_reason=failure_reason,
        )
