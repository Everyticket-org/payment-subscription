"""
PayU server-to-server webhook (/api/v1/payment/payu/webhook) and the
forged-callback fix on /payu/callback/{success,failure}.

One PayU merchant account is shared by three backends (EveryTicket existing
site, EveryTicket SaaS, and this subscription service), each with its own
webhook URL on the PayU dashboard - so this endpoint must process only its
own TXN- transactions, ignore everything else, and never let an
unauthenticated POST move a transaction into a terminal state.
"""
import hashlib

from tests.test_admin_api import _admin_headers
from tests.test_payu_callback_redirect import _switch_to_payu_with_test_credentials

KEY, SALT = "cbkey", "cbsalt"
PRODUCTINFO, FIRSTNAME = "Basic", "Test"


def _signed_payload(txnid: str, amount: str, email: str, status: str = "success") -> dict:
    reverse_string = f"{SALT}|{status}|||||||||||{email}|{FIRSTNAME}|{PRODUCTINFO}|{amount}|{txnid}|{KEY}"
    return {
        "key": KEY,
        "txnid": txnid,
        "amount": amount,
        "productinfo": PRODUCTINFO,
        "firstname": FIRSTNAME,
        "email": email,
        "status": status,
        "mihpayid": "PAYUWH0001",
        "hash": hashlib.sha512(reverse_string.encode("utf-8")).hexdigest(),
    }


def _subscribe(client, email: str, mobile: str) -> tuple[str, str]:
    resp = client.post(
        "/api/v1/public/plans/BASIC/subscribe",
        json={"email": email, "mobile": mobile, "registration_data": {}},
    )
    assert resp.status_code == 200, resp.text
    payment = resp.json()["payment"]
    return payment["transaction_id"], f"{payment['amount']:.2f}"


def _transaction_status(seeded_db, txnid: str) -> str:
    from app.payments.models import PaymentTransaction

    seeded_db.expire_all()
    return seeded_db.query(PaymentTransaction).filter(PaymentTransaction.transaction_id == txnid).one().status


def _with_payu(client, monkeypatch):
    headers = _admin_headers(client)
    _switch_to_payu_with_test_credentials(client, headers, monkeypatch)
    return headers


def _restore_mock(client, headers):
    from app.core.config import get_settings

    client.put("/api/v1/admin/config/application/payment-gateway", json={"default_gateway": "mock"}, headers=headers)
    get_settings.cache_clear()


def test_webhook_completes_payment_when_browser_never_returns(client, seeded_db, monkeypatch):
    headers = _with_payu(client, monkeypatch)
    try:
        email = "payuwebhook-ok@example.com"
        txnid, amount = _subscribe(client, email, "9822200101")

        resp = client.post("/api/v1/payment/payu/webhook", data=_signed_payload(txnid, amount, email))

        assert resp.status_code == 200
        assert resp.json() == {"status": "processed"}
        assert _transaction_status(seeded_db, txnid) == "SUCCESS"

        # The late browser return is then a harmless duplicate (idempotent).
        callback = client.post(
            "/api/v1/payment/payu/callback/success",
            data=_signed_payload(txnid, amount, email),
            follow_redirects=False,
        )
        assert callback.status_code == 303
        assert _transaction_status(seeded_db, txnid) == "SUCCESS"
    finally:
        _restore_mock(client, headers)


def test_webhook_with_forged_hash_leaves_transaction_untouched(client, seeded_db, monkeypatch):
    headers = _with_payu(client, monkeypatch)
    try:
        email = "payuwebhook-forged@example.com"
        txnid, amount = _subscribe(client, email, "9822200102")
        forged = {**_signed_payload(txnid, amount, email), "hash": "0" * 128}

        resp = client.post("/api/v1/payment/payu/webhook", data=forged)

        assert resp.status_code == 200
        assert resp.json() == {"status": "ignored"}
        assert _transaction_status(seeded_db, txnid) not in {"SUCCESS", "FAILED", "CANCELLED"}
    finally:
        _restore_mock(client, headers)


def test_forged_callback_does_not_block_the_genuine_one(client, seeded_db, monkeypatch):
    """Before the fix, a bad-hash POST marked the transaction FAILED
    (terminal), so the customer's real success callback was then ignored."""
    headers = _with_payu(client, monkeypatch)
    try:
        email = "payucallback-forged@example.com"
        txnid, amount = _subscribe(client, email, "9822200103")
        forged = {**_signed_payload(txnid, amount, email, status="failure"), "hash": "0" * 128}

        forged_resp = client.post("/api/v1/payment/payu/callback/failure", data=forged, follow_redirects=False)
        assert forged_resp.status_code == 303
        assert "status=error" in forged_resp.headers["location"]
        assert _transaction_status(seeded_db, txnid) not in {"SUCCESS", "FAILED", "CANCELLED"}

        genuine = client.post(
            "/api/v1/payment/payu/callback/success",
            data=_signed_payload(txnid, amount, email),
            follow_redirects=False,
        )
        assert "status=success" in genuine.headers["location"]
        assert _transaction_status(seeded_db, txnid) == "SUCCESS"
    finally:
        _restore_mock(client, headers)


def test_webhook_ignores_other_apps_payments(client, seeded_db, monkeypatch):
    headers = _with_payu(client, monkeypatch)
    try:
        # EveryTicket existing site (numeric txnid) and SaaS (SAAS prefix).
        for foreign_txnid in ("1234567", "SAAS1A2B3C4D5E6F"):
            resp = client.post(
                "/api/v1/payment/payu/webhook",
                data=_signed_payload(foreign_txnid, "500.00", "someone@example.com"),
            )
            assert resp.status_code == 200
            assert resp.json() == {"status": "ignored"}

        # Payment-link style JSON webhook - never used by this service.
        resp = client.post("/api/v1/payment/payu/webhook", json={"status": "PAID", "udf": {"udf1": "12345678"}})
        assert resp.status_code == 200
        assert resp.json() == {"status": "ignored"}
    finally:
        _restore_mock(client, headers)
