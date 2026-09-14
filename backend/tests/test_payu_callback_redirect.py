"""
Integration test for the real PayU Hosted Checkout redirect endpoint
(app/api/v1/payment.py's /payu/callback/success|failure), covering the
`payment_type` query param it now passes through to the frontend's
/payment/return landing page (2026-09-13 follow-up: "show message '...you
will get your credentials in sometime' for first time subscription...
This message also should be configurable") - PaymentReturnPage.tsx gates
that message on this being exactly "NEW", so a real subscribe -> PayU
checkout -> signed callback round trip needs to actually carry it, not
just the transaction_id/subscription_id it already did.

Uses the same reverse-hash formula as test_payu_gateway.py's adapter-only
unit tests, but drives it through the real FastAPI route rather than
calling PayUGateway.process_webhook() directly - that file deliberately
never calls a real network endpoint or an admin-configured-credentials
subscribe flow; this one does, since that's the only way to see the
redirect's actual query string.
"""
import hashlib
from urllib.parse import parse_qs, urlparse

from tests.test_admin_api import _admin_headers


def _switch_to_payu_with_test_credentials(client, headers, monkeypatch):
    from app.core.config import get_settings

    # No env creds - forces the callback's reverse-hash verification to
    # use the DB-stored (admin-configured) credentials below, same as
    # test_admin_config.py's payment-gateway-switch test.
    monkeypatch.setenv("PAYU_MERCHANT_KEY", "")
    monkeypatch.setenv("PAYU_MERCHANT_SALT", "")
    get_settings.cache_clear()
    resp = client.put(
        "/api/v1/admin/config/application/payment-gateway",
        json={"default_gateway": "payu", "payu_test": {"merchant_key": "cbkey", "merchant_salt": "cbsalt"}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


def test_payu_success_redirect_carries_payment_type_new_for_a_first_time_subscription(client, seeded_db, monkeypatch):
    from app.core.config import get_settings

    headers = _admin_headers(client)
    _switch_to_payu_with_test_credentials(client, headers, monkeypatch)
    try:
        subscribe = client.post(
            "/api/v1/public/plans/BASIC/subscribe",
            json={"email": "payureturn-new@example.com", "mobile": "9822200001", "registration_data": {}},
        )
        assert subscribe.status_code == 200, subscribe.text
        assert subscribe.json()["payment"]["payment_type"] == "NEW"
        txnid = subscribe.json()["payment"]["transaction_id"]
        amount = f"{subscribe.json()['payment']['amount']:.2f}"

        key, salt, status = "cbkey", "cbsalt", "success"
        productinfo, firstname, email = "Basic", "Test", "payureturn-new@example.com"
        reverse_string = f"{salt}|{status}|||||||||||{email}|{firstname}|{productinfo}|{amount}|{txnid}|{key}"
        valid_hash = hashlib.sha512(reverse_string.encode("utf-8")).hexdigest()

        callback = client.post(
            "/api/v1/payment/payu/callback/success",
            data={
                "key": key,
                "txnid": txnid,
                "amount": amount,
                "productinfo": productinfo,
                "firstname": firstname,
                "email": email,
                "status": status,
                "mihpayid": "PAYUCB0001",
                "hash": valid_hash,
            },
            follow_redirects=False,
        )
        assert callback.status_code == 303
        params = parse_qs(urlparse(callback.headers["location"]).query)
        assert params["status"] == ["success"]
        assert params["transaction_id"] == [txnid]
        assert params["payment_type"] == ["NEW"]
    finally:
        client.put("/api/v1/admin/config/application/payment-gateway", json={"default_gateway": "mock"}, headers=headers)
        get_settings.cache_clear()


def test_payu_success_redirect_carries_payment_type_upgrade_for_an_existing_customer(client, seeded_db, monkeypatch):
    """The other half of the "first-time vs change-plan" distinction:
    an existing customer upgrading must come back with payment_type
    UPGRADE, not NEW - PaymentReturnPage.tsx must never show the
    credentials message here, since this customer already has an
    account."""
    from app.core.config import get_settings

    headers = _admin_headers(client)

    subscribe = client.post(
        "/api/v1/public/plans/BASIC/subscribe",
        json={"email": "payureturn-upgrade@example.com", "mobile": "9822200002", "registration_data": {}},
    )
    assert subscribe.status_code == 200, subscribe.text
    client.post(
        "/api/v1/payment/mock/callback",
        json={"transaction_id": subscribe.json()["payment"]["transaction_id"], "scenario": "SUCCESS"},
    )
    ident = client.post("/api/v1/public/identify", json={"email": "payureturn-upgrade@example.com", "mobile": "9822200002"})
    verify = client.post(
        "/api/v1/public/otp/verify", json={"otp_session_id": ident.json()["otp_session_id"], "code": "BYPASS"}
    )
    customer_headers = {"Authorization": f"Bearer {verify.json()['access_token']}"}

    _switch_to_payu_with_test_credentials(client, headers, monkeypatch)
    try:
        upgrade = client.post(
            "/api/v1/public/plans/PROFESSIONAL/subscribe",
            json={"registration_data": {}},
            headers=customer_headers,
        )
        assert upgrade.status_code == 200, upgrade.text
        assert upgrade.json()["payment"]["payment_type"] == "UPGRADE"
        txnid = upgrade.json()["payment"]["transaction_id"]
        amount = f"{upgrade.json()['payment']['amount']:.2f}"

        key, salt, status = "cbkey", "cbsalt", "success"
        productinfo, firstname, email = "Professional", "Test", "payureturn-upgrade@example.com"
        reverse_string = f"{salt}|{status}|||||||||||{email}|{firstname}|{productinfo}|{amount}|{txnid}|{key}"
        valid_hash = hashlib.sha512(reverse_string.encode("utf-8")).hexdigest()

        callback = client.post(
            "/api/v1/payment/payu/callback/success",
            data={
                "key": key,
                "txnid": txnid,
                "amount": amount,
                "productinfo": productinfo,
                "firstname": firstname,
                "email": email,
                "status": status,
                "mihpayid": "PAYUCB0002",
                "hash": valid_hash,
            },
            follow_redirects=False,
        )
        assert callback.status_code == 303
        params = parse_qs(urlparse(callback.headers["location"]).query)
        assert params["payment_type"] == ["UPGRADE"]
    finally:
        client.put("/api/v1/admin/config/application/payment-gateway", json={"default_gateway": "mock"}, headers=headers)
        get_settings.cache_clear()
