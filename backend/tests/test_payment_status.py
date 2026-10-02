"""
GET /api/v1/payment/{transaction_id}/status - what the customer's
/payment/return page shows. Read from our database and only with the
short-lived token the PayU return redirect carried, so the URL's own
status=... can't fake a result and a transaction ID alone reveals nothing.
"""
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from tests.test_payu_webhook import _restore_mock, _signed_payload, _subscribe, _with_payu


def _pay_and_get_token(client, email: str, mobile: str, status: str = "success") -> tuple[str, str]:
    txnid, amount = _subscribe(client, email, mobile)
    route = "success" if status == "success" else "failure"
    resp = client.post(
        f"/api/v1/payment/payu/callback/{route}",
        # mihpayid is unique per gateway payment (and not part of the hash).
        data={**_signed_payload(txnid, amount, email, status=status), "mihpayid": f"PAYU-{txnid}"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    query = parse_qs(urlparse(resp.headers["location"]).query)
    return txnid, query["token"][0]


def test_status_with_token_reports_what_the_database_says(client, seeded_db, monkeypatch):
    headers = _with_payu(client, monkeypatch)
    try:
        txnid, token = _pay_and_get_token(client, "status-ok@example.com", "9822200301")

        resp = client.get(f"/api/v1/payment/{txnid}/status", params={"token": token})

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["transaction_id"] == txnid
        assert body["status"] == "SUCCESS"
        assert body["payment_type"] == "NEW"
        assert body["plan_code"] == "BASIC"
        assert body["plan_name"]
        assert body["subscription_status"] == "ACTIVE"
        assert body["invoice_id"]
    finally:
        _restore_mock(client, headers)


def test_failed_payment_status_includes_reason(client, seeded_db, monkeypatch):
    headers = _with_payu(client, monkeypatch)
    try:
        txnid, token = _pay_and_get_token(client, "status-failed@example.com", "9822200302", status="failure")

        body = client.get(f"/api/v1/payment/{txnid}/status", params={"token": token}).json()

        assert body["status"] == "FAILED"
        assert body["failure_reason"]
        assert body["invoice_id"] is None
    finally:
        _restore_mock(client, headers)


def test_status_is_refused_without_a_matching_token(client, seeded_db, monkeypatch):
    from app.payments.models import PaymentEvent

    headers = _with_payu(client, monkeypatch)
    try:
        txnid, token = _pay_and_get_token(client, "status-a@example.com", "9822200303")
        other_txnid, _ = _pay_and_get_token(client, "status-b@example.com", "9822200304")

        no_token = client.get(f"/api/v1/payment/{txnid}/status")
        tampered = client.get(f"/api/v1/payment/{txnid}/status", params={"token": token[:-2] + "xx"})
        wrong_txn = client.get(f"/api/v1/payment/{other_txnid}/status", params={"token": token})
        unknown = client.get("/api/v1/payment/TXN-NOPE/status", params={"token": token})

        for resp in (no_token, tampered, wrong_txn, unknown):
            assert resp.status_code == 403
            assert resp.json()["error_code"] == "PAYMENT_STATUS_TOKEN_INVALID"

        seeded_db.expire_all()
        rejected = seeded_db.query(PaymentEvent).filter(PaymentEvent.result == "TOKEN_REJECTED").count()
        assert rejected == 4
    finally:
        _restore_mock(client, headers)


def test_expired_token_is_refused():
    from app.payments.status_token import create_status_token, token_matches

    issued_long_ago = datetime.now(timezone.utc) - timedelta(hours=2)
    assert token_matches(create_status_token("TXN-ABC", now=issued_long_ago), "TXN-ABC") is False
    assert token_matches(create_status_token("TXN-ABC"), "TXN-ABC") is True


def test_status_token_is_not_a_valid_customer_access_token(client, seeded_db):
    """Signed with a purpose-derived key, so it can't be replayed against
    the customer portal."""
    from app.payments.status_token import create_status_token

    token = create_status_token("TXN-ABC")
    resp = client.get("/api/v1/customer/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401
