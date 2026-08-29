"""
PayU gateway adapter (spec sections 23-28, 74) - PayU India Hosted
Checkout (redirect) integration.

Unlike the mock gateway, PayU is a redirect-based flow: create_payment()
does not itself contact PayU over the network - it builds and hashes the
exact form fields the customer's BROWSER must POST to PayU's hosted
checkout page (https://test.payu.in/_payment in test mode,
https://secure.payu.in/_payment in production, both per settings.PAYU_BASE_URL).
The customer completes the payment on PayU's own page; PayU then redirects
the browser back to our surl/furl with the outcome, which is verified
server-side in app/api/v1/payment.py's payu_callback route via the
reverse-hash formula below - never trusted from the redirect alone
(spec section 28's tamper-detection requirement).

Hash formulas and field names below are taken directly from PayU's own
documentation (docs.payu.in/docs/generate-hash-payu-hosted and
docs.payu.in/docs/working-with-response-after-a-customer-checkout),
not guessed - see docs/implementation-status.md for the increment note
this landed in.
"""
import hashlib
from typing import Any

from app.core.config import get_settings
from app.payments.interfaces.gateway import GatewayPaymentResult, PaymentGateway


def _sha512_hex(raw: str) -> str:
    return hashlib.sha512(raw.encode("utf-8")).hexdigest()


class PayUConfigurationError(RuntimeError):
    """Raised when PAYU_MERCHANT_KEY/PAYU_MERCHANT_SALT aren't set - a
    clearer error than a confusing downstream PayU rejection."""


class PayUGateway(PaymentGateway):
    code = "payu"

    def create_payment(
        self, *, transaction_id: str, amount: float, currency: str, metadata: dict[str, Any]
    ) -> GatewayPaymentResult:
        settings = get_settings()
        if not settings.PAYU_MERCHANT_KEY or not settings.PAYU_MERCHANT_SALT:
            raise PayUConfigurationError(
                "PAYU_MERCHANT_KEY / PAYU_MERCHANT_SALT are not set - add your PayU test "
                "credentials to backend/.env (see .env.example) before using the payu gateway."
            )

        key = settings.PAYU_MERCHANT_KEY
        salt = settings.PAYU_MERCHANT_SALT
        txnid = transaction_id
        # PayU expects amount as a plain decimal string, not a currency-formatted one.
        amount_str = f"{amount:.2f}"
        productinfo = str(metadata.get("productinfo") or "Subscription")[:100]
        firstname = str(metadata.get("firstname") or "Customer")[:60]
        email = str(metadata.get("email") or "customer@example.com")
        phone = str(metadata.get("phone") or "9999999999")

        # udf1-udf5 are unused in this integration but MUST still be
        # represented as empty-string pipe positions in the hash - PayU's
        # formula is positional, not a plain concatenation of used fields.
        udf1 = udf2 = udf3 = udf4 = udf5 = ""
        hash_string = (
            f"{key}|{txnid}|{amount_str}|{productinfo}|{firstname}|{email}|"
            f"{udf1}|{udf2}|{udf3}|{udf4}|{udf5}||||||{salt}"
        )
        request_hash = _sha512_hex(hash_string)

        checkout_fields = {
            "key": key,
            "txnid": txnid,
            "amount": amount_str,
            "productinfo": productinfo,
            "firstname": firstname,
            "email": email,
            "phone": phone,
            "surl": settings.PAYU_SUCCESS_URL,
            "furl": settings.PAYU_FAILURE_URL,
            "hash": request_hash,
        }

        return GatewayPaymentResult(
            gateway=self.code,
            gateway_transaction_id=None,  # unknown until PayU redirects back with mihpayid
            status="PENDING",
            amount=amount,
            currency=currency,
            raw_response={
                "action_url": f"{settings.PAYU_BASE_URL}/_payment",
                "method": "POST",
                "fields": checkout_fields,
            },
        )

    def get_payment_status(self, *, gateway_transaction_id: str) -> GatewayPaymentResult:
        # V1 relies solely on the surl/furl redirect callback as the
        # authoritative outcome (spec section 25) - no server-to-server
        # status-check API call is implemented in this pass; see
        # docs/implementation-status.md.
        raise NotImplementedError(
            "PayU status polling is not implemented in this pass - the surl/furl "
            "callback (process_webhook) is the authoritative outcome for V1."
        )

    def verify_payment(self, *, gateway_transaction_id: str, raw_response: dict[str, Any]) -> GatewayPaymentResult:
        return self.process_webhook(payload=raw_response)

    def verify_webhook(self, *, headers: dict[str, str], raw_body: bytes) -> bool:
        # PayU's Hosted Checkout flow authenticates via the reverse-hash on
        # the surl/furl POST body itself (see process_webhook) rather than
        # a signed header, so there's nothing separate to check here. Kept
        # for PaymentGateway interface compatibility.
        return True

    def process_webhook(self, *, payload: dict[str, Any]) -> GatewayPaymentResult:
        settings = get_settings()
        salt = settings.PAYU_MERCHANT_SALT
        key = str(payload.get("key", ""))
        txnid = str(payload.get("txnid", ""))
        amount = payload.get("amount", "")
        productinfo = str(payload.get("productinfo", ""))
        firstname = str(payload.get("firstname", ""))
        email = str(payload.get("email", ""))
        status = str(payload.get("status", ""))
        udf1 = str(payload.get("udf1", "") or "")
        udf2 = str(payload.get("udf2", "") or "")
        udf3 = str(payload.get("udf3", "") or "")
        udf4 = str(payload.get("udf4", "") or "")
        udf5 = str(payload.get("udf5", "") or "")
        received_hash = str(payload.get("hash", "")).lower()

        reverse_string = (
            f"{salt}|{status}||||||{udf5}|{udf4}|{udf3}|{udf2}|{udf1}|"
            f"{email}|{firstname}|{productinfo}|{amount}|{txnid}|{key}"
        )
        expected_hash = _sha512_hex(reverse_string)

        try:
            amount_float = float(amount)
        except (TypeError, ValueError):
            amount_float = 0.0

        if expected_hash != received_hash:
            return GatewayPaymentResult(
                gateway=self.code,
                gateway_transaction_id=payload.get("mihpayid"),
                status="FAILED",
                amount=amount_float,
                currency="INR",
                raw_response=payload,
                failure_reason="Hash verification failed - response may have been tampered with",
            )

        status_map = {
            "success": "SUCCESS",
            "failure": "FAILED",
            "failed": "FAILED",
            "pending": "PENDING",
            "cancel": "CANCELLED",
            "cancelled": "CANCELLED",
        }
        mapped_status = status_map.get(status.lower(), "UNKNOWN")
        failure_reason = None
        if mapped_status == "FAILED":
            failure_reason = payload.get("error_Message") or payload.get("error") or "Payment failed at PayU"

        return GatewayPaymentResult(
            gateway=self.code,
            gateway_transaction_id=payload.get("mihpayid"),
            status=mapped_status,
            amount=amount_float,
            currency="INR",
            raw_response=payload,
            failure_reason=failure_reason,
        )
