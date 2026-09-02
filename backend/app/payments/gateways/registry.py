"""
Gateway registry (spec section 74): maps a gateway code to a live adapter
instance. Adding a gateway = implement PaymentGateway, register it here,
configure credentials - no changes to SubscriptionService/PaymentService.
"""
from sqlalchemy.orm import Session

from app.payments.gateways.mock.gateway import MockPaymentGateway
from app.payments.gateways.payu.gateway import PayUGateway
from app.payments.interfaces.gateway import PaymentGateway

_REGISTRY: dict[str, PaymentGateway] = {
    "mock": MockPaymentGateway(),
    # Instantiating PayUGateway() here does not require credentials to be
    # set - PAYU_MERCHANT_KEY/SALT (or the admin-configured DB overrides)
    # are only checked lazily, inside create_payment(), so a deployment
    # with no PayU creds configured can still boot fine as long as no
    # Application actually routes to "payu". This zero-arg instance falls
    # back to env vars only - callers that have a db session and want the
    # admin-configured, per-mode (test/live) credentials should call
    # get_gateway(code, db=..., mode=...) instead (see below).
    "payu": PayUGateway(),
}


def list_gateway_codes() -> list[str]:
    """For the admin Payment Gateway screen's dropdown (spec section 51,
    2026-09 restructure)."""
    return list(_REGISTRY.keys())


def get_gateway(code: str, *, db: Session | None = None, mode: str | None = None) -> PaymentGateway:
    """Without `db`, returns the module-level singleton (env-only
    credentials) - unchanged behavior for every existing call site/test.
    With `db` (and, for payu, `mode` - Application.gateway_mode, "test" or
    "live"), returns a freshly-resolved instance carrying the admin-
    configured credentials for that gateway+mode (app.payments.
    gateway_config), falling back to env vars if nothing is configured -
    same DB-row-overrides-env-fallback pattern as webhook_secret/sso_secret."""
    if code == "payu" and db is not None:
        from app.payments.gateway_config import resolve_payu_credentials

        creds = resolve_payu_credentials(db, mode=mode or "test")
        return PayUGateway(
            merchant_key=creds["merchant_key"], merchant_salt=creds["merchant_salt"], base_url=creds["base_url"]
        )
    try:
        return _REGISTRY[code]
    except KeyError:
        raise ValueError(f"Unknown payment gateway '{code}'")
