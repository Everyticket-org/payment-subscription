"""
PayU reconciliation sweep (app.payments.reconcile): the backstop for a
payment whose browser return and webhook were both lost. PayU's Verify
Payment API is faked at the HTTP layer (httpx.post), so the request hash
and the response parsing in PayUGateway.get_payment_status are exercised
too.
"""
import hashlib
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from tests.test_payu_webhook import KEY, SALT, _restore_mock, _subscribe, _transaction_status, _with_payu


class _FakeResponse:
    def __init__(self, body: dict):
        self._body = body

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._body


class _FakePayU:
    """Records each Verify Payment call and answers with a canned reply."""

    def __init__(self, monkeypatch, *, status: str | None, amount: str | None = None, raises: bool = False):
        self.calls: list[dict] = []
        self.status = status
        self.amount = amount
        self.raises = raises
        import app.payments.gateways.payu.gateway as gateway_module

        monkeypatch.setattr(gateway_module.httpx, "post", self._post)

    def _post(self, url, data, timeout):
        self.calls.append({"url": url, "data": data})
        if self.raises:
            raise httpx.ConnectError("PayU unreachable")
        txnid = data["var1"]
        if self.status is None:
            details = {"mihpayid": "Not Found", "status": "Not Found"}
            return _FakeResponse({"status": 0, "msg": "0 out of 1 Transactions Fetched Successfully",
                                  "transaction_details": {txnid: details}})
        details = {"mihpayid": "PAYUREC0001", "txnid": txnid, "status": self.status,
                   "unmappedstatus": "captured", "amt": self.amount, "error_Message": "NO ERROR", "mode": "UPI"}
        return _FakeResponse({"status": 1, "msg": "1 out of 1 Transactions Fetched Successfully",
                              "transaction_details": {txnid: details}})


@pytest.fixture()
def payu(client, monkeypatch):
    headers = _with_payu(client, monkeypatch)
    yield
    _restore_mock(client, headers)


def _age_payment(seeded_db, txnid: str, minutes: float) -> None:
    from app.payments.models import PaymentTransaction

    transaction = seeded_db.query(PaymentTransaction).filter(PaymentTransaction.transaction_id == txnid).one()
    transaction.created_at = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    seeded_db.commit()


def _reconcile(seeded_db, now: datetime | None = None) -> dict:
    from app.payments.reconcile import reconcile_pending

    seeded_db.expire_all()
    return reconcile_pending(seeded_db, now=now)


def _last_reconcile_result(seeded_db, txnid: str) -> str:
    from app.payments.models import PaymentEvent

    seeded_db.expire_all()
    event = (
        seeded_db.query(PaymentEvent)
        .filter(PaymentEvent.transaction_id == txnid, PaymentEvent.event_type == "RECONCILE")
        .order_by(PaymentEvent.id.desc())
        .first()
    )
    return event.result if event else None


def test_lost_success_is_applied_from_payu(client, seeded_db, monkeypatch, payu):
    txnid, amount = _subscribe(client, "recon-ok@example.com", "9822200401")
    _age_payment(seeded_db, txnid, minutes=20)
    fake = _FakePayU(monkeypatch, status="success", amount=amount)

    counts = _reconcile(seeded_db)

    assert counts == {"PROCESSED": 1}
    assert _transaction_status(seeded_db, txnid) == "SUCCESS"
    assert _last_reconcile_result(seeded_db, txnid) == "PROCESSED"
    [call] = fake.calls
    assert call["url"] == "https://test.payu.in/merchant/postservice.php?form=2"
    assert call["data"]["command"] == "verify_payment"
    assert call["data"]["var1"] == txnid
    expected_hash = hashlib.sha512(f"{KEY}|verify_payment|{txnid}|{SALT}".encode()).hexdigest()
    assert call["data"]["hash"] == expected_hash


def test_amount_mismatch_is_never_applied(client, seeded_db, monkeypatch, payu):
    txnid, _amount = _subscribe(client, "recon-amount@example.com", "9822200402")
    _age_payment(seeded_db, txnid, minutes=20)
    _FakePayU(monkeypatch, status="success", amount="1.00")

    _reconcile(seeded_db)

    assert _transaction_status(seeded_db, txnid) == "PENDING"
    assert _last_reconcile_result(seeded_db, txnid) == "AMOUNT_MISMATCH"


def test_failure_is_only_applied_once_the_payment_is_old_enough(client, seeded_db, monkeypatch, payu):
    txnid, amount = _subscribe(client, "recon-fail@example.com", "9822200403")
    _FakePayU(monkeypatch, status="failure", amount=amount)

    _age_payment(seeded_db, txnid, minutes=20)
    _reconcile(seeded_db)
    assert _transaction_status(seeded_db, txnid) == "PENDING"
    assert _last_reconcile_result(seeded_db, txnid) == "STILL_PENDING"

    _age_payment(seeded_db, txnid, minutes=90)
    _reconcile(seeded_db, now=datetime.now(timezone.utc) + timedelta(hours=1))  # past the backoff
    assert _transaction_status(seeded_db, txnid) == "FAILED"


def test_payment_payu_never_saw_expires_after_the_limit(client, seeded_db, monkeypatch, payu):
    txnid, _amount = _subscribe(client, "recon-expire@example.com", "9822200404")
    _FakePayU(monkeypatch, status=None)

    _age_payment(seeded_db, txnid, minutes=120)
    _reconcile(seeded_db)
    assert _transaction_status(seeded_db, txnid) == "PENDING"

    _age_payment(seeded_db, txnid, minutes=25 * 60)
    _reconcile(seeded_db, now=datetime.now(timezone.utc) + timedelta(hours=7))
    assert _transaction_status(seeded_db, txnid) == "FAILED"
    assert _last_reconcile_result(seeded_db, txnid) == "EXPIRED"


def test_recent_payments_are_left_alone_and_checks_back_off(client, seeded_db, monkeypatch, payu):
    txnid, amount = _subscribe(client, "recon-backoff@example.com", "9822200405")
    fake = _FakePayU(monkeypatch, status="pending", amount=amount)

    _age_payment(seeded_db, txnid, minutes=5)
    _reconcile(seeded_db)
    assert fake.calls == []  # younger than PAYU_RECONCILE_AFTER_MINUTES

    _age_payment(seeded_db, txnid, minutes=40)
    _reconcile(seeded_db)
    assert len(fake.calls) == 1
    counts = _reconcile(seeded_db)  # immediately again: not due yet
    assert counts == {"skipped": 1}
    assert len(fake.calls) == 1


def test_payu_outage_is_logged_and_retried_later(client, seeded_db, monkeypatch, payu):
    txnid, _amount = _subscribe(client, "recon-down@example.com", "9822200406")
    _age_payment(seeded_db, txnid, minutes=20)
    _FakePayU(monkeypatch, status=None, raises=True)

    counts = _reconcile(seeded_db)

    assert counts == {"ERROR": 1}
    assert _transaction_status(seeded_db, txnid) == "PENDING"
    assert _last_reconcile_result(seeded_db, txnid) == "ERROR"
