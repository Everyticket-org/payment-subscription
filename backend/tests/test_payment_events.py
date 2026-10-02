"""
Payment event log (app.payments.events / PaymentEvent): every payment
records where it started and which URLs PayU was given, and every PayU
browser return / webhook is recorded with what we did with it - without
logging ever being able to break a payment.
"""
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from tests.test_admin_api import _admin_headers
from tests.test_payu_webhook import _restore_mock, _signed_payload, _subscribe, _transaction_status, _with_payu

ORIGIN = "https://subscribe.everyticket.example"


def _events(seeded_db, txnid: str):
    from app.payments.models import PaymentEvent

    seeded_db.expire_all()
    return (
        seeded_db.query(PaymentEvent)
        .filter(PaymentEvent.transaction_id == txnid)
        .order_by(PaymentEvent.id.asc())
        .all()
    )


def _subscribe_from_origin(client, email: str, mobile: str) -> tuple[str, str]:
    resp = client.post(
        "/api/v1/public/plans/BASIC/subscribe",
        json={"email": email, "mobile": mobile, "registration_data": {}},
        headers={"Origin": ORIGIN, "User-Agent": "pytest-browser/1.0"},
    )
    assert resp.status_code == 200, resp.text
    payment = resp.json()["payment"]
    return payment["transaction_id"], f"{payment['amount']:.2f}"


def test_initiated_event_records_origin_and_the_urls_sent_to_payu(client, seeded_db, monkeypatch):
    headers = _with_payu(client, monkeypatch)
    try:
        txnid, _amount = _subscribe_from_origin(client, "events-init@example.com", "9822200201")

        [event] = _events(seeded_db, txnid)
        assert event.event_type == "INITIATED"
        assert event.result == "CREATED"
        assert event.channel == "subscribe"
        assert event.initiated_from == ORIGIN
        assert event.user_agent == "pytest-browser/1.0"
        assert event.endpoint == "/api/v1/public/plans/BASIC/subscribe"
        assert event.surl_sent.endswith("/api/v1/payment/payu/callback/success")
        assert event.furl_sent.endswith("/api/v1/payment/payu/callback/failure")
        assert event.return_url.endswith("/payment/return")
        assert event.gateway_status == "PENDING"
    finally:
        _restore_mock(client, headers)


def test_browser_return_then_webhook_are_both_recorded(client, seeded_db, monkeypatch):
    headers = _with_payu(client, monkeypatch)
    try:
        email = "events-return@example.com"
        txnid, amount = _subscribe_from_origin(client, email, "9822200202")

        client.post("/api/v1/payment/payu/callback/success", data=_signed_payload(txnid, amount, email), follow_redirects=False)
        client.post("/api/v1/payment/payu/webhook", data=_signed_payload(txnid, amount, email))

        events = _events(seeded_db, txnid)
        assert [(e.event_type, e.result) for e in events] == [
            ("INITIATED", "CREATED"),
            ("BROWSER_RETURN", "PROCESSED"),
            ("WEBHOOK", "DUPLICATE_IGNORED"),
        ]
        browser_return = events[1]
        assert browser_return.endpoint == "/api/v1/payment/payu/callback/success"
        assert browser_return.hash_verified is True
        assert browser_return.gateway_status == "success"
        assert browser_return.gateway_transaction_id == "PAYUWH0001"
        # Sanitised: allow-listed fields only - never the hash or the customer's email.
        assert browser_return.payload["mihpayid"] == "PAYUWH0001"
        assert "hash" not in browser_return.payload
        assert "email" not in browser_return.payload
        assert events[2].endpoint == "/api/v1/payment/payu/webhook"
    finally:
        _restore_mock(client, headers)


def test_forged_callback_is_recorded_as_hash_failed(client, seeded_db, monkeypatch):
    headers = _with_payu(client, monkeypatch)
    try:
        email = "events-forged@example.com"
        txnid, amount = _subscribe(client, email, "9822200203")
        forged = {**_signed_payload(txnid, amount, email), "hash": "0" * 128}

        resp = client.post("/api/v1/payment/payu/callback/success", data=forged, follow_redirects=False)

        # No status token for an unauthenticated POST.
        assert "token" not in parse_qs(urlparse(resp.headers["location"]).query)
        last = _events(seeded_db, txnid)[-1]
        assert (last.event_type, last.result, last.hash_verified) == ("BROWSER_RETURN", "HASH_FAILED", False)
    finally:
        _restore_mock(client, headers)


def test_callback_for_unknown_transaction_is_recorded(client, seeded_db, monkeypatch):
    headers = _with_payu(client, monkeypatch)
    try:
        client.post(
            "/api/v1/payment/payu/callback/success",
            data=_signed_payload("TXN-DOESNOTEXIST", "10.00", "nobody@example.com"),
            follow_redirects=False,
        )
        [event] = _events(seeded_db, "TXN-DOESNOTEXIST")
        assert (event.event_type, event.result) == ("BROWSER_RETURN", "UNKNOWN_TXN")
    finally:
        _restore_mock(client, headers)


def test_success_after_failure_is_flagged_as_late_success(client, seeded_db, monkeypatch):
    headers = _with_payu(client, monkeypatch)
    try:
        email = "events-late@example.com"
        txnid, amount = _subscribe(client, email, "9822200204")
        client.post(
            "/api/v1/payment/payu/callback/failure",
            data=_signed_payload(txnid, amount, email, status="failure"),
            follow_redirects=False,
        )
        assert _transaction_status(seeded_db, txnid) == "FAILED"

        client.post("/api/v1/payment/payu/webhook", data=_signed_payload(txnid, amount, email))

        assert _transaction_status(seeded_db, txnid) == "FAILED"  # still not re-applied automatically
        assert _events(seeded_db, txnid)[-1].result == "LATE_SUCCESS_IGNORED"
    finally:
        _restore_mock(client, headers)


def test_checkout_form_is_kept_after_payu_responds(client, seeded_db, monkeypatch):
    """Before: the PayU response overwrote raw_gateway_response, losing the
    surl/furl we had sent."""
    from app.payments.models import PaymentTransaction

    headers = _with_payu(client, monkeypatch)
    try:
        email = "events-keep@example.com"
        txnid, amount = _subscribe(client, email, "9822200205")
        client.post("/api/v1/payment/payu/callback/success", data=_signed_payload(txnid, amount, email), follow_redirects=False)

        seeded_db.expire_all()
        raw = seeded_db.query(PaymentTransaction).filter(PaymentTransaction.transaction_id == txnid).one().raw_gateway_response
        assert raw["checkout"]["fields"]["surl"].endswith("/api/v1/payment/payu/callback/success")
        assert raw["checkout"]["mode"] == "test"
        assert raw["gateway_response"]["mihpayid"] == "PAYUWH0001"
    finally:
        _restore_mock(client, headers)


def test_event_logging_failure_never_blocks_a_payment(client, seeded_db, monkeypatch):
    import app.payments.events as events_module

    headers = _with_payu(client, monkeypatch)
    try:
        email = "events-broken@example.com"
        txnid, amount = _subscribe(client, email, "9822200206")

        def _broken(**_kwargs):
            raise RuntimeError("payment_events table missing")

        monkeypatch.setattr(events_module, "PaymentEvent", _broken)
        resp = client.post(
            "/api/v1/payment/payu/callback/success", data=_signed_payload(txnid, amount, email), follow_redirects=False
        )

        assert resp.status_code == 303
        assert "status=success" in resp.headers["location"]
        assert _transaction_status(seeded_db, txnid) == "SUCCESS"
    finally:
        _restore_mock(client, headers)


def test_admin_can_read_a_payments_event_history(client, seeded_db, monkeypatch):
    headers = _with_payu(client, monkeypatch)
    try:
        email = "events-admin@example.com"
        txnid, amount = _subscribe_from_origin(client, email, "9822200207")
        client.post("/api/v1/payment/payu/callback/success", data=_signed_payload(txnid, amount, email), follow_redirects=False)

        resp = client.get(f"/api/v1/admin/payments/{txnid}/events", headers=_admin_headers(client))

        assert resp.status_code == 200, resp.text
        rows = resp.json()
        assert [r["event_type"] for r in rows] == ["INITIATED", "BROWSER_RETURN"]
        assert rows[0]["initiated_from"] == ORIGIN

        missing = client.get("/api/v1/admin/payments/TXN-NOPE/events", headers=_admin_headers(client))
        assert missing.status_code == 404
        assert client.get(f"/api/v1/admin/payments/{txnid}/events").status_code in (401, 403)
    finally:
        _restore_mock(client, headers)


def test_purge_removes_only_events_past_retention(seeded_db):
    from app.payments.events import purge_old_events
    from app.payments.models import PaymentEvent

    now = datetime.now(timezone.utc)
    seeded_db.add_all([
        PaymentEvent(transaction_id="TXN-OLD", event_type="WEBHOOK", result="PROCESSED", created_at=now - timedelta(days=181)),
        PaymentEvent(transaction_id="TXN-NEW", event_type="WEBHOOK", result="PROCESSED", created_at=now - timedelta(days=10)),
    ])
    seeded_db.commit()

    assert purge_old_events(seeded_db, now=now) == 1
    remaining = [e.transaction_id for e in seeded_db.query(PaymentEvent).all()]
    assert remaining == ["TXN-NEW"]
