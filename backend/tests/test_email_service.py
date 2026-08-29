"""
Unit tests for email orchestration (spec sections 49-50) - template
rendering, NotificationLog writes, and the real trigger points (OTP,
payment success/failure, cancellation, renewal reminders). SMTP itself is
faked via monkeypatch (no real network, no dependency on anything
actually listening on SMTP_PORT).
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.core.enums import NotificationStatus
from app.notifications.email import service as email_service
from app.notifications.email.providers.smtp import provider as smtp_provider
from app.notifications.models import NotificationLog, NotificationTemplate
from app.subscriptions import service as subscription_service
from app.subscriptions.models import Subscription


@pytest.fixture()
def fake_smtp_success(monkeypatch):
    sent = []

    class _FakeSMTP:
        def __init__(self, host, port, timeout=10):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            pass

        def login(self, user, password):
            pass

        def sendmail(self, from_addr, to_addrs, message):
            sent.append((from_addr, to_addrs, message))

    monkeypatch.setattr(smtp_provider.smtplib, "SMTP", _FakeSMTP)
    return sent


@pytest.fixture()
def fake_smtp_failure(monkeypatch):
    import smtplib

    class _FakeSMTP:
        def __init__(self, host, port, timeout=10):
            raise smtplib.SMTPConnectError(111, "Connection refused")

    monkeypatch.setattr(smtp_provider.smtplib, "SMTP", _FakeSMTP)


def test_send_templated_email_with_no_template_logs_failed(db_session):
    result = email_service.send_templated_email(
        db_session, template_code="does_not_exist", to="x@example.com", context={}
    )
    assert result is False
    log = db_session.query(NotificationLog).one()
    assert log.status == NotificationStatus.FAILED.value
    assert "No active" in log.provider_response


def test_send_templated_email_renders_and_sends(db_session, fake_smtp_success):
    db_session.add(
        NotificationTemplate(
            template_code="greet", channel="email", subject="Hi {{ name }}",
            body_html="<p>Hello {{ name }}</p>", body_text="Hello {{ name }}", active=True,
        )
    )
    db_session.commit()

    result = email_service.send_templated_email(
        db_session, template_code="greet", to="jane@example.com", context={"name": "Jane"},
        related_entity_type="customer", related_entity_id="CUS-XYZ",
    )
    assert result is True
    assert len(fake_smtp_success) == 1
    _from, to_addrs, message = fake_smtp_success[0]
    assert to_addrs == ["jane@example.com"]
    assert "Hello Jane" in message

    log = db_session.query(NotificationLog).one()
    assert log.status == NotificationStatus.SENT.value
    assert log.recipient == "jane@example.com"
    assert log.related_entity_id == "CUS-XYZ"


def test_send_templated_email_smtp_failure_logs_failed_not_raise(db_session, fake_smtp_failure):
    db_session.add(
        NotificationTemplate(
            template_code="greet2", channel="email", subject="Hi", body_html="<p>Hi</p>", active=True,
        )
    )
    db_session.commit()

    result = email_service.send_templated_email(db_session, template_code="greet2", to="x@example.com", context={})
    assert result is False
    log = db_session.query(NotificationLog).one()
    assert log.status == NotificationStatus.FAILED.value


def test_send_templated_email_with_no_recipient_is_a_noop(db_session):
    result = email_service.send_templated_email(db_session, template_code="anything", to=None, context={})
    assert result is False
    assert db_session.query(NotificationLog).count() == 0


def test_identify_sends_real_otp_email(client, seeded_db, fake_smtp_success):
    client.post(
        "/api/v1/public/plans/basic/subscribe",
        json={"email": "existing@museum.example", "mobile": "9800011122", "registration_data": {}},
    )
    resp = client.post(
        "/api/v1/public/identify", json={"email": "existing@museum.example", "mobile": "9800011122"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["match_status"] == "exact"

    log = (
        seeded_db.query(NotificationLog)
        .filter(NotificationLog.template_code == "otp_verification")
        .order_by(NotificationLog.id.desc())
        .first()
    )
    assert log is not None
    assert log.status == NotificationStatus.SENT.value
    assert log.recipient == "existing@museum.example"


def test_payment_success_sends_confirmation_email(client, seeded_db, fake_smtp_success):
    resp = client.post(
        "/api/v1/public/plans/basic/subscribe",
        json={"email": "payer@museum.example", "mobile": "9800022233", "registration_data": {}},
    )
    transaction_id = resp.json()["payment"]["transaction_id"]
    client.post("/api/v1/payment/mock/callback", json={"transaction_id": transaction_id, "scenario": "SUCCESS"})

    log = seeded_db.query(NotificationLog).filter(NotificationLog.template_code == "payment_success").one()
    assert log.status == NotificationStatus.SENT.value
    assert log.recipient == "payer@museum.example"


def test_payment_failure_sends_failure_email(client, seeded_db, fake_smtp_success):
    resp = client.post(
        "/api/v1/public/plans/basic/subscribe",
        json={"email": "failpayer@museum.example", "mobile": "9800033344", "registration_data": {}},
    )
    transaction_id = resp.json()["payment"]["transaction_id"]
    client.post("/api/v1/payment/mock/callback", json={"transaction_id": transaction_id, "scenario": "FAILED"})

    log = seeded_db.query(NotificationLog).filter(NotificationLog.template_code == "payment_failed").one()
    assert log.status == NotificationStatus.SENT.value


def test_renewal_reminder_sent_once_per_cycle(seeded_db, fake_smtp_success):
    from app.applications.models import Application
    from app.customers import service as customer_service
    from app.plans.models import Plan

    application = seeded_db.query(Application).filter(Application.code == "EVERYTICKET").first()
    plan = seeded_db.query(Plan).filter(Plan.plan_code == "BASIC", Plan.application_id == application.id).one()
    customer = customer_service.create_customer(seeded_db, email="reminder@museum.example", mobile="9800044455")
    subscription = subscription_service.create_pending_subscription(
        seeded_db, customer=customer, application=application, plan=plan
    )
    subscription_service.activate_subscription(seeded_db, subscription=subscription)
    subscription.expires_at = datetime.now(timezone.utc) + timedelta(days=1)
    seeded_db.commit()

    sent_first = subscription_service.send_renewal_reminders(seeded_db)
    assert sent_first == 1
    assert len(fake_smtp_success) == 1

    # Running the sweep again immediately must NOT send a second reminder
    # for the same expiry cycle.
    sent_second = subscription_service.send_renewal_reminders(seeded_db)
    assert sent_second == 0
    assert len(fake_smtp_success) == 1
