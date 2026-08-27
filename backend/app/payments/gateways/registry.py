"""
Gateway registry (spec section 74): maps a gateway code to a live adapter
instance. Adding a gateway = implement PaymentGateway, register it here,
configure credentials - no changes to SubscriptionService/PaymentService.
"""
from app.payments.gateways.mock.gateway import MockPaymentGateway
from app.payments.interfaces.gateway import PaymentGateway

_REGISTRY: dict[str, PaymentGateway] = {
    "mock": MockPaymentGateway(),
    # "payu": PayUGateway(...),  # registered once PayU adapter is implemented
}


def get_gateway(code: str) -> PaymentGateway:
    try:
        return _REGISTRY[code]
    except KeyError:
        raise ValueError(f"Unknown payment gateway '{code}'")
