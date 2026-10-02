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
import hmac
from typing import Any

import httpx

from app.core.config import get_settings
from app.payments.interfaces.gateway import GatewayPaymentResult, PaymentGateway


def _sha512_hex(raw: str) -> str:
    return hashlib.sha512(raw.encode("utf-8")).hexdigest()


class PayUConfigurationError(RuntimeError):
    """Raised when PAYU_MERCHANT_KEY/PAYU_MERCHANT_SALT aren't set - a
    clearer error than a confusing downstream PayU rejection."""


class PayUGateway(PaymentGateway):
    """merchant_key/merchant_salt/base_url, if given at construction time,
    override the PAYU_MERCHANT_KEY/PAYU_MERCHANT_SALT/PAYU_BASE_URL env
    vars for this instance only - used by the registry to hand out a
    gateway instance resolved against the admin-configured, per-mode
    (test/live) credentials (app.payments.gateway_config), while the
    zero-arg PayUGateway() the module-level registry/tests still
    construct keeps falling back to env vars exactly as before (backward
    compatible with every existing PayU unit test)."""

    code = "payu"

    def __init__(
        self,
        *,
        merchant_key: str | None = None,
        merchant_salt: str | None = None,
        base_url: str | None = None,
        success_url: str | None = None,
        failure_url: str | None = None,
        verify_url: str | None = None,
    ) -> None:
        self._merchant_key = merchant_key
        self._merchant_salt = merchant_salt
        self._base_url = base_url
        # PayU Verify Payment API endpoint (get_payment_status) - test or
        # production host per mode, resolved by the registry; falls back to
        # settings.PAYU_VERIFY_URL (test).
        self._verify_url = verify_url
        # success_url/failure_url override settings.PAYU_SUCCESS_URL/
        # PAYU_FAILURE_URL for this instance only - same override/fallback
        # pattern as merchant_key/salt/base_url above. Set by the registry
        # from Application.payu_webhook_base_url (2026-09 follow-up: "PayU
        # redirect back to localhost:4200 which is wrong. instead allow to
        # configure return URL and PayU webhook URL") when an admin has
        # configured one; otherwise falls back to the env vars exactly as
        # before.
        self._success_url = success_url
        self._failure_url = failure_url

    def _resolve(self) -> tuple[str, str, str, str, str]:
        settings = get_settings()
        key = self._merchant_key or settings.PAYU_MERCHANT_KEY
        salt = self._merchant_salt or settings.PAYU_MERCHANT_SALT
        base_url = self._base_url or settings.PAYU_BASE_URL
        success_url = self._success_url or settings.PAYU_SUCCESS_URL
        failure_url = self._failure_url or settings.PAYU_FAILURE_URL
        return key, salt, base_url, success_url, failure_url

    def create_payment(
        self, *, transaction_id: str, amount: float, currency: str, metadata: dict[str, Any]
    ) -> GatewayPaymentResult:
        key, salt, base_url, success_url, failure_url = self._resolve()
        if not key or not salt:
            raise PayUConfigurationError(
                "PAYU_MERCHANT_KEY / PAYU_MERCHANT_SALT are not set - add your PayU test "
                "credentials to backend/.env (see .env.example), or configure them in the "
                "admin Configuration > Payment Gateway screen, before using the payu gateway."
            )
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
            "surl": success_url,
            "furl": failure_url,
            "hash": request_hash,
        }

        return GatewayPaymentResult(
            gateway=self.code,
            gateway_transaction_id=None,  # unknown until PayU redirects back with mihpayid
            status="PENDING",
            amount=amount,
            currency=currency,
            raw_response={
                "action_url": f"{base_url}/_payment",
                "method": "POST",
                "fields": checkout_fields,
            },
        )

    def get_payment_status(self, *, gateway_transaction_id: str) -> GatewayPaymentResult:
        """Asks PayU's Verify Payment API what happened to one payment
        (docs.payu.in/reference/verify_payment_api). Used only by the
        reconciliation sweep (app.payments.reconcile) as a backstop - the
        surl/furl return and the webhook stay the primary paths.

        PayU looks payments up by OUR txnid (TXN-...), so that is what
        `gateway_transaction_id` must be here, not PayU's mihpayid.

        The request is authenticated with sha512(key|command|var1|salt)
        and sent server-to-server over HTTPS; PayU's JSON reply is not
        separately signed. Returns status UNKNOWN when PayU has no record
        of the txnid ("Not Found"). Raises httpx.HTTPError on network or
        HTTP errors so the caller can retry on the next sweep."""
        key, salt, _base_url, _success_url, _failure_url = self._resolve()
        if not key or not salt:
            raise PayUConfigurationError("PayU merchant key/salt are not configured - cannot verify payments")
        settings = get_settings()
        verify_url = self._verify_url or settings.PAYU_VERIFY_URL
        txnid = gateway_transaction_id
        command = "verify_payment"
        request_hash = _sha512_hex(f"{key}|{command}|{txnid}|{salt}")

        response = httpx.post(
            verify_url,
            data={"key": key, "command": command, "var1": txnid, "hash": request_hash},
            timeout=settings.PAYU_VERIFY_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body = response.json()

        details = (body.get("transaction_details") or {}).get(txnid) if isinstance(body, dict) else None
        if not isinstance(details, dict):
            details = {}
        payu_status = str(details.get("status") or "").strip().lower()
        status_map = {
            "success": "SUCCESS",
            "failure": "FAILED",
            "failed": "FAILED",
            "pending": "PENDING",
        }
        mapped_status = status_map.get(payu_status, "UNKNOWN")  # incl. "not found"
        try:
            amount = float(details.get("amt") or details.get("amount") or 0)
        except (TypeError, ValueError):
            amount = 0.0
        mihpayid = details.get("mihpayid")
        if not mihpayid or str(mihpayid).lower() == "not found":
            mihpayid = None
        failure_reason = None
        if mapped_status == "FAILED":
            message = details.get("error_Message") or details.get("field9")
            failure_reason = message if message and message != "NO ERROR" else "Payment failed at PayU"

        return GatewayPaymentResult(
            gateway=self.code,
            gateway_transaction_id=mihpayid,
            status=mapped_status,
            amount=amount,
            currency="INR",
            raw_response={"verify_payment": details, "msg": body.get("msg") if isinstance(body, dict) else None},
            failure_reason=failure_reason,
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
        _key, salt, _base_url, _success_url, _failure_url = self._resolve()
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
        # Constant-time comparison (avoids leaking hash prefixes via timing),
        # and the response must be for OUR merchant key.
        hash_ok = bool(salt and received_hash) and key == _key and hmac.compare_digest(
            expected_hash, received_hash
        )

        try:
            amount_float = float(amount)
        except (TypeError, ValueError):
            amount_float = 0.0

        if not hash_ok:
            return GatewayPaymentResult(
                gateway=self.code,
                gateway_transaction_id=payload.get("mihpayid"),
                status="FAILED",
                amount=amount_float,
                currency="INR",
                raw_response=payload,
                failure_reason="Hash verification failed - response may have been tampered with",
                hash_verified=False,
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
