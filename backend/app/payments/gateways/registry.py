"""
Gateway registry (spec section 74): maps a gateway code to a live adapter
instance. Adding a gateway = implement PaymentGateway, register it here,
configure credentials - no changes to SubscriptionService/PaymentService.
"""
from app.payments.gateways.mock.gateway import MockPaymentGateway
from app.payments.gateways.payu.gateway import PayUGateway
from app.payments.interfaces.gateway import PaymentGateway

_REGISTRY: dict[str, PaymentGateway] = {
    "mock": MockPaymentGateway(),
    # Instantiating PayUGateway() here does not require credentials to be
    # set - PAYU_MERCHANT_KEY/SALT are only checked lazily, inside
    # create_payment(), so a deployment with no PayU creds configured can
    # still boot fine as long as no Application actually routes to "payu".
    "payu": PayUGateway(),
}


def get_gateway(code: str) -> PaymentGateway:
    try:
        return _REGISTRY[code]
    except KeyError:
        raise ValueError(f"Unknown payment gateway '{code}'")
