"""
Admin Testing / Developer Tools module (spec sections 54, 55).

Covers each tool: TEST PAYMENT (SUCCESS + DUPLICATE_CALLBACK scenarios,
reusing the real MockPaymentGateway callback path), TEST SUBSCRIPTION
EVENTS (renew/cancel + the upgrade-needs-a-target-plan validation),
WEBHOOK FAILURE SIMULATOR (verifying the real retry-schedule bookkeeping
via an injected httpx.MockTransport - no real network), TEST EVERYTICKET
WEBHOOK (ad-hoc signed send - shape-only assertions since nothing is
actually listening on the fallback destination in this test environment),
TEST EMAIL (via a faked smtplib.SMTP, same pattern as test_email_service.py),
the OTP/MFA bypass status+toggle endpoints, and the TEST DATA GENERATOR +
cleanup round trip. Also covers the require_test_mode / require_permission
gates shared with every other TEST_MODE-only admin action.
"""
from app.core.config import get_settings
from app.customers import service as customer_service
from app.customers.models import Customer, CustomerRegistrationData
from app.notifications.email.providers.smtp import provider as smtp_provider

from tests.test_admin_api import _admin_headers, _new_active_subscription


def _create_bare_customer(db_session, *, email: str, mobile: str) -> str:
    """A Customer with no subscription at all - what TEST PAYMENT needs,
    since create_pending_subscription() refuses a customer who already
    has an active one."""
    customer = customer_service.create_customer(db_session, email=email, mobile=mobile)
    db_session.commit()
    return customer.customer_id


class _FakeSMTP:
    """Same fake used by tests/test_email_service.py - no real network,
    no dependency on anything actually listening on SMTP_PORT."""

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
        pass


def test_testing_endpoints_require_test_mode(client, seeded_db, monkeypatch):
    headers = _admin_headers(client)
    monkeypatch.setenv("TEST_MODE", "false")
    get_settings.cache_clear()
    try:
        resp = client.get("/api/v1/admin/testing/status", headers=headers)
        assert resp.status_code == 403
        assert resp.json()["error_code"] == "FORBIDDEN"
    finally:
        get_settings.cache_clear()


def test_testing_endpoints_require_permission(client, seeded_db, db_session):
    from app.auth import service as auth_service

    auth_service.create_admin_user(
        db_session, email="limited-testing@example.com", full_name="Limited Admin", password="LimitedPass123!", mfa_enabled=False
    )
    db_session.commit()
    login = client.post(
        "/api/v1/admin/auth/login", json={"email": "limited-testing@example.com", "password": "LimitedPass123!"}
    )
    limited_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = client.get("/api/v1/admin/testing/status", headers=limited_headers)
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "FORBIDDEN"


def test_test_payment_success(client, seeded_db, db_session):
    headers = _admin_headers(client)
    customer_id = _create_bare_customer(db_session, email="testpay-success@example.com", mobile="9811100001")

    resp = client.post(
        "/api/v1/admin/testing/payment",
        json={"customer_id": customer_id, "plan_code": "basic", "scenario": "SUCCESS"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["payment"]["status"] == "SUCCESS"
    assert body["subscription"]["status"] == "ACTIVE"
    assert body["invoice_id"]


def test_test_payment_duplicate_callback_is_a_safe_no_op(client, seeded_db, db_session):
    headers = _admin_headers(client)
    customer_id = _create_bare_customer(db_session, email="testpay-dup@example.com", mobile="9811100002")

    resp = client.post(
        "/api/v1/admin/testing/payment",
        json={"customer_id": customer_id, "plan_code": "basic", "scenario": "DUPLICATE_CALLBACK"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["subscription"]["status"] == "ACTIVE"
    assert "no-op" in body["note"].lower() or "duplicate" in body["note"].lower()


def test_test_payment_rejects_unknown_scenario(client, seeded_db, db_session):
    headers = _admin_headers(client)
    customer_id = _create_bare_customer(db_session, email="testpay-badscenario@example.com", mobile="9811100003")

    resp = client.post(
        "/api/v1/admin/testing/payment",
        json={"customer_id": customer_id, "plan_code": "basic", "scenario": "NOT_A_REAL_SCENARIO"},
        headers=headers,
    )
    assert resp.status_code == 422


def test_test_subscription_event_renew_then_cancel(client, seeded_db):
    headers = _admin_headers(client)
    subscription_id = _new_active_subscription(client, "basic", "testevent-renew@example.com", "9811100004")

    renew = client.post(
        "/api/v1/admin/testing/subscription-event",
        json={"subscription_id": subscription_id, "event": "RENEW"},
        headers=headers,
    )
    assert renew.status_code == 200, renew.text
    assert renew.json()["status"] == "ACTIVE"

    cancel = client.post(
        "/api/v1/admin/testing/subscription-event",
        json={"subscription_id": subscription_id, "event": "CANCEL"},
        headers=headers,
    )
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()["status"] == "CANCELLED"


def test_test_subscription_event_upgrade_requires_target_plan(client, seeded_db):
    headers = _admin_headers(client)
    subscription_id = _new_active_subscription(client, "basic", "testevent-upgrade@example.com", "9811100005")

    resp = client.post(
        "/api/v1/admin/testing/subscription-event",
        json={"subscription_id": subscription_id, "event": "UPGRADE"},
        headers=headers,
    )
    assert resp.status_code == 422


def test_test_subscription_event_upgrade_with_target_plan(client, seeded_db):
    headers = _admin_headers(client)
    subscription_id = _new_active_subscription(client, "basic", "testevent-upgrade2@example.com", "9811100006")

    resp = client.post(
        "/api/v1/admin/testing/subscription-event",
        json={"subscription_id": subscription_id, "event": "UPGRADE", "target_plan_code": "professional"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["plan_code"] == "PROFESSIONAL"


def test_webhook_failure_simulator_schedules_retry(client, seeded_db):
    headers = _admin_headers(client)
    resp = client.post("/api/v1/admin/testing/webhook/simulate-failure", json={"status_code": "500"}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "FAILED"
    assert body["attempt_count"] == 1
    assert body["http_status"] == 500
    assert body["next_retry_at"] is not None


def test_webhook_failure_simulator_timeout(client, seeded_db):
    headers = _admin_headers(client)
    resp = client.post("/api/v1/admin/testing/webhook/simulate-failure", json={"status_code": "timeout"}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "FAILED"
    assert body["http_status"] is None


def test_webhook_failure_simulator_rejects_unknown_status(client, seeded_db):
    headers = _admin_headers(client)
    resp = client.post("/api/v1/admin/testing/webhook/simulate-failure", json={"status_code": "999"}, headers=headers)
    assert resp.status_code == 422


def test_webhook_send_returns_request_response_shape(client, seeded_db):
    headers = _admin_headers(client)
    resp = client.post(
        "/api/v1/admin/testing/webhook/send",
        json={"payload": {"hello": "world"}, "headers": {"X-Test": "1"}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "sent" in body
    assert isinstance(body["sent"], bool)
    if not body["sent"]:
        assert "error" in body


def test_webhook_send_result_appears_in_webhook_logs(client, seeded_db):
    """Per Vishal's follow-up ("I want to have response into webhook
    logs"): a Test Everyticket Webhook send - success or failure - must
    show up on the admin Webhook Logs screen (GET /admin/webhooks/events
    and /deliveries), with the real response/error captured on the
    delivery row, not just in the live API response or Audit Logs."""
    headers = _admin_headers(client)
    resp = client.post(
        "/api/v1/admin/testing/webhook/send",
        json={"payload": {"marker": "webhook-logs-check"}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    live_result = resp.json()
    assert live_result["sent"] is False  # nothing listens at the fallback URL in this test env
    assert "error" in live_result

    events = client.get(
        "/api/v1/admin/webhooks/events", params={"event_type": "test.manual_send"}, headers=headers
    )
    assert events.status_code == 200, events.text
    matching = [e for e in events.json()["items"] if e["payload"] == {"marker": "webhook-logs-check"}]
    assert len(matching) == 1
    event = matching[0]
    assert len(event["deliveries"]) == 1
    delivery = event["deliveries"][0]
    assert delivery["status"] == "FAILED"
    assert delivery["response_body"] == live_result["error"]

    deliveries = client.get("/api/v1/admin/webhooks/deliveries", params={"status": "FAILED"}, headers=headers)
    assert deliveries.status_code == 200, deliveries.text
    assert any(d["response_body"] == live_result["error"] for d in deliveries.json()["items"])


def test_webhook_send_result_is_stored_in_audit_log_even_on_failure(client, seeded_db):
    """A test send that fails (nothing is listening at the fallback
    EVERYTICKET_WEBHOOK_URL in this test environment) must still be
    durably recorded - not just returned in the live HTTP response and
    then lost the moment the admin navigates away. TEST_WEBHOOK_SENT's
    audit entry now stores the full result dict, so the error/response
    detail is reviewable later from Audit Logs regardless of outcome."""
    headers = _admin_headers(client)
    resp = client.post(
        "/api/v1/admin/testing/webhook/send",
        json={"payload": {"hello": "world"}},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    live_result = resp.json()

    logs = client.get("/api/v1/admin/audit-logs", params={"action": "TEST_WEBHOOK_SENT"}, headers=headers)
    assert logs.status_code == 200, logs.text
    entries = logs.json()["items"]
    assert len(entries) >= 1
    stored = entries[0]["new_value"]

    # The exact same fields the live response carried (sent/http_status,
    # and - since nothing is listening at the configured fallback URL in
    # this test environment - error) must have been persisted, not just
    # a trimmed-down sent/http_status pair.
    assert stored["sent"] == live_result["sent"]
    assert stored["sent"] is False
    assert "error" in stored and stored["error"]
    assert stored["error"] == live_result["error"]


def test_test_email_sends_via_faked_smtp(client, seeded_db, monkeypatch):
    monkeypatch.setattr(smtp_provider.smtplib, "SMTP", _FakeSMTP)
    headers = _admin_headers(client)

    resp = client.post(
        "/api/v1/admin/testing/email",
        json={"template_code": "payment_success", "to": "test-email-recipient@example.com"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["sent"] is True
    assert body["status"] == "SENT"


def test_test_mode_status_and_bypass_toggle_round_trip(client, seeded_db):
    headers = _admin_headers(client)

    status = client.get("/api/v1/admin/testing/status", headers=headers)
    assert status.status_code == 200, status.text
    assert status.json()["test_mode"] is True
    original = status.json()

    try:
        toggled = client.post(
            "/api/v1/admin/testing/otp-mfa-bypass", json={"allow_otp_bypass": False}, headers=headers
        )
        assert toggled.status_code == 200, toggled.text
        assert toggled.json()["allow_otp_bypass"] is False
    finally:
        # Restore - ALLOW_OTP_BYPASS is a shared in-process setting and
        # other tests in this same pytest run rely on it staying on.
        client.post(
            "/api/v1/admin/testing/otp-mfa-bypass",
            json={"allow_otp_bypass": original["allow_otp_bypass"], "allow_admin_mfa_bypass": original["allow_admin_mfa_bypass"]},
            headers=headers,
        )


def test_test_data_generator_and_cleanup_round_trip(client, seeded_db):
    headers = _admin_headers(client)

    generated = client.post("/api/v1/admin/testing/data/generate", headers=headers)
    assert generated.status_code == 200, generated.text
    body = generated.json()
    assert body["customer_id"].startswith("CUS-")
    assert body["plan_code"].startswith("TEST-")
    assert body["subscription_id"].startswith("SUB-")
    assert body["invoice_id"]

    customer_lookup = client.get(
        "/api/v1/admin/customers", params={"q": body["customer_id"]}, headers=headers
    )
    assert customer_lookup.json()["total"] == 1

    # Registration-data sample values (2026-09: previously the generator
    # left this customer's registration data empty, so a generated
    # customer never demonstrated the customer-portal "Account" card's
    # registration-details section or the admin customer-detail page's
    # equivalent) - one row, keyed by whatever active form fields are
    # seeded (app/core/seed.py), non-empty values for every non-file field.
    # Captured as a plain int rather than kept as a live ORM object -
    # cleanup below deletes this row out from under the session via a
    # bulk delete(synchronize_session=False), which would leave a
    # still-attached db_customer object expired and raise
    # ObjectDeletedError on next attribute access.
    db_customer_id = seeded_db.query(Customer.id).filter(Customer.customer_id == body["customer_id"]).scalar()
    reg_rows = (
        seeded_db.query(CustomerRegistrationData)
        .filter(CustomerRegistrationData.customer_id == db_customer_id)
        .all()
    )
    assert len(reg_rows) == 1
    assert reg_rows[0].data  # non-empty
    assert all(v for v in reg_rows[0].data.values())

    cleanup = client.post("/api/v1/admin/testing/data/cleanup", headers=headers)
    assert cleanup.status_code == 200, cleanup.text
    cleanup_body = cleanup.json()
    assert cleanup_body["plans_deleted"] >= 1
    assert cleanup_body["customers_deleted"] >= 1
    assert cleanup_body["subscriptions_deleted"] >= 1

    after_cleanup = client.get(
        "/api/v1/admin/customers", params={"q": body["customer_id"]}, headers=headers
    )
    assert after_cleanup.json()["total"] == 0

    # The registration-data row for this now-deleted customer must not be
    # left behind as an orphan.
    assert (
        seeded_db.query(CustomerRegistrationData)
        .filter(CustomerRegistrationData.customer_id == db_customer_id)
        .count()
        == 0
    )
