"""
Unit tests for the PayU gateway adapter (spec sections 23-28, 74).

These test the hash math and request/response shape directly against
PayU's own documented formulas (see app/payments/gateways/payu/gateway.py's
module docstring for the doc links) - no network call to PayU itself,
since that's exactly what create_payment()/process_webhook() are designed
to avoid (PayU is a redirect-based flow; the network call happens in the
customer's browser, not this process).
"""
import hashlib

import pytest

from app.core.config import get_settings
from app.payments.gateways.payu.gateway import PayUConfigurationError, PayUGateway


@pytest.fixture()
def payu_settings(monkeypatch):
    monkeypatch.setenv("PAYU_MERCHANT_KEY", "testkey123")
    monkeypatch.setenv("PAYU_MERCHANT_SALT", "testsalt456")
    monkeypatch.setenv("PAYU_BASE_URL", "https://test.payu.in")
    monkeypatch.setenv("PAYU_SUCCESS_URL", "http://localhost:8000/api/v1/payment/payu/callback/success")
    monkeypatch.setenv("PAYU_FAILURE_URL", "http://localhost:8000/api/v1/payment/payu/callback/failure")
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


def test_create_payment_raises_clear_error_without_credentials(monkeypatch):
    monkeypatch.setenv("PAYU_MERCHANT_KEY", "")
    monkeypatch.setenv("PAYU_MERCHANT_SALT", "")
    get_settings.cache_clear()
    gateway = PayUGateway()
    with pytest.raises(PayUConfigurationError):
        gateway.create_payment(
            transaction_id="TXN-TEST1", amount=100.0, currency="INR", metadata={}
        )
    get_settings.cache_clear()


def test_create_payment_builds_hash_matching_payu_documented_formula(payu_settings):
    gateway = PayUGateway()
    result = gateway.create_payment(
        transaction_id="TXN-ABC123",
        amount=5000.0,
        currency="INR",
        metadata={"productinfo": "Professional", "firstname": "Test", "email": "test@example.com", "phone": "9999999999"},
    )

    assert result.status == "PENDING"
    assert result.gateway == "payu"
    fields = result.raw_response["fields"]
    assert result.raw_response["action_url"] == "https://test.payu.in/_payment"
    assert result.raw_response["method"] == "POST"
    assert fields["key"] == "testkey123"
    assert fields["txnid"] == "TXN-ABC123"
    assert fields["amount"] == "5000.00"

    # Recompute the hash independently, straight from PayU's documented
    # formula (docs.payu.in/docs/generate-hash-payu-hosted), and confirm
    # our adapter's hash matches byte for byte.
    expected_string = "testkey123|TXN-ABC123|5000.00|Professional|Test|test@example.com|||||||||||testsalt456"
    expected_hash = hashlib.sha512(expected_string.encode("utf-8")).hexdigest()
    assert fields["hash"] == expected_hash


def test_process_webhook_accepts_correctly_hashed_success_response(payu_settings):
    gateway = PayUGateway()
    key, salt = "testkey123", "testsalt456"
    txnid, amount, productinfo, firstname, email, status = (
        "TXN-XYZ999", "2000.00", "Basic", "Jane", "jane@example.com", "success",
    )
    reverse_string = f"{salt}|{status}|||||||||||{email}|{firstname}|{productinfo}|{amount}|{txnid}|{key}"
    valid_hash = hashlib.sha512(reverse_string.encode("utf-8")).hexdigest()

    result = gateway.process_webhook(
        payload={
            "key": key, "txnid": txnid, "amount": amount, "productinfo": productinfo,
            "firstname": firstname, "email": email, "status": status,
            "mihpayid": "PAYUID999", "hash": valid_hash,
        }
    )
    assert result.status == "SUCCESS"
    assert result.gateway_transaction_id == "PAYUID999"
    assert result.amount == 2000.0
    assert result.failure_reason is None


def test_process_webhook_rejects_tampered_hash_as_failed(payu_settings):
    gateway = PayUGateway()
    result = gateway.process_webhook(
        payload={
            "key": "testkey123", "txnid": "TXN-TAMPERED", "amount": "999999.00",
            "productinfo": "Basic", "firstname": "Jane", "email": "jane@example.com",
            "status": "success", "mihpayid": "PAYUID000", "hash": "0" * 128,
        }
    )
    assert result.status == "FAILED"
    assert "Hash verification failed" in result.failure_reason


def test_process_webhook_maps_payu_failure_status(payu_settings):
    gateway = PayUGateway()
    key, salt = "testkey123", "testsalt456"
    txnid, amount, productinfo, firstname, email, status = (
        "TXN-FAIL1", "3000.00", "Enterprise", "Sam", "sam@example.com", "failure",
    )
    reverse_string = f"{salt}|{status}|||||||||||{email}|{firstname}|{productinfo}|{amount}|{txnid}|{key}"
    valid_hash = hashlib.sha512(reverse_string.encode("utf-8")).hexdigest()

    result = gateway.process_webhook(
        payload={
            "key": key, "txnid": txnid, "amount": amount, "productinfo": productinfo,
            "firstname": firstname, "email": email, "status": status,
            "mihpayid": "PAYUID111", "hash": valid_hash, "error_Message": "Insufficient funds",
        }
    )
    assert result.status == "FAILED"
    assert result.failure_reason == "Insufficient funds"
