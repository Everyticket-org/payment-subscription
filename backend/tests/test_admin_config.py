"""
Admin configuration screens (spec sections 13, 51, 81): Payment Gateway /
Everyticket Integration / Notification / Security / System Configuration.
All but Integration's `api_credentials`/webhook signing verification (no
real Everyticket instance in this test env) are checked for REAL effect,
not just storage - default_gateway actually changes which gateway a new
payment uses, notification sender overrides actually change the sent
email's From header, subscription-rule toggles actually 403 the
corresponding customer action, and security config's otp_length actually
changes the generated code's length.
"""
from app.notifications.email.providers.smtp import provider as smtp_provider

from tests.test_admin_api import _admin_headers


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
        self.__class__.sent.append(message)


_FakeSMTP.sent = []


def test_get_application_config_masks_secrets(client, seeded_db):
    headers = _admin_headers(client)
    resp = client.get("/api/v1/admin/config/application", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["general"]["code"] == "EVERYTICKET"
    assert "webhook_secret" not in body["integration"]
    assert "sso_secret" not in body["integration"]
    assert "api_credentials" not in body["integration"]
    assert body["integration"]["webhook_secret_is_set"] is False
    assert body["payment"]["default_gateway"] == "mock"


def test_config_endpoints_require_permission(client, seeded_db, db_session):
    from app.auth import service as auth_service

    auth_service.create_admin_user(
        db_session, email="noconfigperm@example.com", full_name="No Perm", password="LimitedPass123!", mfa_enabled=False
    )
    db_session.commit()
    login = client.post("/api/v1/admin/auth/login", json={"email": "noconfigperm@example.com", "password": "LimitedPass123!"})
    limited_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    assert client.get("/api/v1/admin/config/application", headers=limited_headers).status_code == 403
    assert client.put("/api/v1/admin/config/application/general", json={"name": "x", "application_url": "http://x"}, headers=limited_headers).status_code == 403
    assert client.get("/api/v1/admin/config/security", headers=limited_headers).status_code == 403


def test_update_general_config_round_trips(client, seeded_db):
    headers = _admin_headers(client)
    resp = client.put(
        "/api/v1/admin/config/application/general",
        json={
            "name": "Everyticket Subscriptions (Staging)",
            "application_url": "https://staging.example.com",
            "support_email": "help@example.com",
            "timezone": "Asia/Kolkata",
            "currency": "INR",
            "active": True,
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Everyticket Subscriptions (Staging)"

    refetched = client.get("/api/v1/admin/config/application", headers=headers)
    assert refetched.json()["general"]["name"] == "Everyticket Subscriptions (Staging)"


def test_update_integration_config_secrets_never_echoed_back(client, seeded_db):
    headers = _admin_headers(client)
    resp = client.put(
        "/api/v1/admin/config/application/integration",
        json={"webhook_url": "https://everyticket.example.com/hooks", "webhook_secret": "s3cr3t", "sso_secret": "s5so"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert "webhook_secret" not in resp.json()
    assert resp.json()["webhook_secret_is_set"] is True
    assert resp.json()["sso_secret_is_set"] is True


def test_update_payment_config_changes_gateway_for_new_payments(client, seeded_db, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("PAYU_MERCHANT_KEY", "testkey123")
    monkeypatch.setenv("PAYU_MERCHANT_SALT", "testsalt456")
    get_settings.cache_clear()

    headers = _admin_headers(client)
    try:
        resp = client.put(
            "/api/v1/admin/config/application/payment",
            json={"default_gateway": "payu", "gateway_mode": "test"},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["default_gateway"] == "payu"

        subscribe = client.post(
            "/api/v1/public/plans/basic/subscribe",
            json={"email": "gatewayswitch@example.com", "mobile": "9833300001", "registration_data": {}},
        )
        assert subscribe.status_code == 200, subscribe.text
        assert subscribe.json()["payment"]["gateway"] == "payu"
        assert subscribe.json()["payment"]["checkout"] is not None  # PayU is redirect-based - mock never sets this
    finally:
        # Restore mock for any other test relying on the seeded default.
        client.put("/api/v1/admin/config/application/payment", json={"default_gateway": "mock", "gateway_mode": "test"}, headers=headers)
        get_settings.cache_clear()


def test_update_notification_config_changes_outbound_sender(client, seeded_db, monkeypatch):
    _FakeSMTP.sent.clear()
    monkeypatch.setattr(smtp_provider.smtplib, "SMTP", _FakeSMTP)
    headers = _admin_headers(client)

    resp = client.put(
        "/api/v1/admin/config/application/notification",
        json={
            "email_provider": "smtp",
            "email_sender_name": "Everyticket Billing",
            "email_sender_address": "billing@everyticket.example.com",
            "email_reply_to": "support@everyticket.example.com",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text

    client.post(
        "/api/v1/public/plans/basic/subscribe",
        json={"email": "sender-override@example.com", "mobile": "9833300002", "registration_data": {}},
    )
    client.post("/api/v1/public/identify", json={"email": "sender-override@example.com", "mobile": "9833300002"})

    assert any("Everyticket Billing <billing@everyticket.example.com>" in m for m in _FakeSMTP.sent)

    # Restore defaults so later tests' emails use the app-wide sender again.
    client.put(
        "/api/v1/admin/config/application/notification",
        json={"email_provider": "smtp", "email_sender_name": None, "email_sender_address": None, "email_reply_to": None},
        headers=headers,
    )


def test_subscription_rules_disable_actually_blocks_the_action(client, seeded_db):
    headers = _admin_headers(client)

    subscribe = client.post(
        "/api/v1/public/plans/basic/subscribe",
        json={"email": "ruletest@example.com", "mobile": "9833300003", "registration_data": {}},
    )
    transaction_id = subscribe.json()["payment"]["transaction_id"]
    client.post("/api/v1/payment/mock/callback", json={"transaction_id": transaction_id, "scenario": "SUCCESS"})

    identify = client.post("/api/v1/public/identify", json={"email": "ruletest@example.com", "mobile": "9833300003"})
    verify = client.post(
        "/api/v1/public/otp/verify", json={"otp_session_id": identify.json()["otp_session_id"], "code": identify.json()["debug_otp_code"]}
    )
    customer_headers = {"Authorization": f"Bearer {verify.json()['access_token']}"}
    subscription_id = subscribe.json()["subscription"]["subscription_id"]

    try:
        client.put(
            "/api/v1/admin/config/application/subscription-rules",
            json={
                "allow_upgrade": False, "allow_downgrade": True, "allow_cancellation": False,
                "cancellation_behavior": "IMMEDIATE", "renewal_enabled": False, "repurchase_enabled": True,
            },
            headers=headers,
        )

        upgrade = client.post(
            f"/api/v1/customer/subscriptions/{subscription_id}/upgrade",
            json={"target_plan_code": "professional"},
            headers=customer_headers,
        )
        assert upgrade.status_code == 403
        assert upgrade.json()["error_code"] == "ACTION_NOT_ALLOWED"

        renew = client.post(f"/api/v1/customer/subscriptions/{subscription_id}/renew", headers=customer_headers)
        assert renew.status_code == 403
        assert renew.json()["error_code"] == "ACTION_NOT_ALLOWED"

        cancel = client.post(
            f"/api/v1/customer/subscriptions/{subscription_id}/cancel", json={"reason": "test"}, headers=customer_headers
        )
        assert cancel.status_code == 403
        assert cancel.json()["error_code"] == "ACTION_NOT_ALLOWED"
    finally:
        client.put(
            "/api/v1/admin/config/application/subscription-rules",
            json={
                "allow_upgrade": True, "allow_downgrade": True, "allow_cancellation": True,
                "cancellation_behavior": "IMMEDIATE", "renewal_enabled": True, "repurchase_enabled": True,
            },
            headers=headers,
        )


def test_security_config_get_defaults_and_round_trips(client, seeded_db):
    headers = _admin_headers(client)
    default = client.get("/api/v1/admin/config/security", headers=headers)
    assert default.status_code == 200, default.text
    assert default.json()["otp_length"] == 6
    assert default.json()["test_mode"] is True  # visible read-only, matches conftest's TEST_MODE=true

    try:
        updated = client.put(
            "/api/v1/admin/config/security",
            json={"otp_length": 4, "otp_expiry_seconds": 300, "otp_max_attempts": 5, "otp_resend_cooldown_seconds": 60},
            headers=headers,
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["otp_length"] == 4

        identify = client.post(
            "/api/v1/public/plans/basic/subscribe",
            json={"email": "otplength@example.com", "mobile": "9833300004", "registration_data": {}},
        )
        assert identify.status_code == 200, identify.text
        resp = client.post("/api/v1/public/identify", json={"email": "otplength@example.com", "mobile": "9833300004"})
        assert len(resp.json()["debug_otp_code"]) == 4
    finally:
        client.put(
            "/api/v1/admin/config/security",
            json={"otp_length": 6, "otp_expiry_seconds": 300, "otp_max_attempts": 5, "otp_resend_cooldown_seconds": 60},
            headers=headers,
        )
