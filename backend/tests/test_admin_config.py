"""
Admin configuration screens, restructured 2026-09 into 4 sections:
Application (name/currency/Live-Test-Mode only), Payment Gateway (gateway
dropdown + per-mode PayU credentials), Everyticket Integration (secret
key/webhook URL/extra POST params/retry limit/escalation email), and
Notifications (SMTP transport + sender overrides). "Subscription rules"
and "Security" configuration are unchanged - their own tests continue
below, verifying REAL effect not just storage, same as before this pass.
"""
from app.notifications.email.providers.smtp import provider as smtp_provider

from tests.test_admin_api import _admin_headers


class _FakeSMTP:
    def __init__(self, host, port, timeout=10):
        self.__class__.connected_to.append((host, port))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        self.__class__.logins.append((user, password))

    def sendmail(self, from_addr, to_addrs, message):
        self.__class__.sent.append(message)


_FakeSMTP.sent = []
_FakeSMTP.connected_to = []
_FakeSMTP.logins = []


def test_get_application_config_masks_secrets(client, seeded_db):
    headers = _admin_headers(client)
    resp = client.get("/api/v1/admin/config/application", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["general"]["code"] == "EVERYTICKET"
    assert body["general"]["gateway_mode"] == "test"
    assert "webhook_secret" not in body["integration"]
    assert "sso_secret" not in body["integration"]
    assert body["integration"]["secret_key_is_set"] is False
    assert body["payment_gateway"]["default_gateway"] == "mock"
    assert set(body["payment_gateway"]["available_gateways"]) == {"mock", "payu"}
    assert body["payment_gateway"]["payu_test"]["merchant_key_is_set"] is False
    assert "smtp_password" not in body["notification"]
    assert body["notification"]["smtp_password_is_set"] is False


def test_config_endpoints_require_permission(client, seeded_db, db_session):
    from app.auth import service as auth_service

    auth_service.create_admin_user(
        db_session, email="noconfigperm@example.com", full_name="No Perm", password="LimitedPass123!", mfa_enabled=False
    )
    db_session.commit()
    login = client.post("/api/v1/admin/auth/login", json={"email": "noconfigperm@example.com", "password": "LimitedPass123!"})
    limited_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    assert client.get("/api/v1/admin/config/application", headers=limited_headers).status_code == 403
    assert client.put(
        "/api/v1/admin/config/application/general", json={"name": "x", "currency": "INR", "gateway_mode": "test"},
        headers=limited_headers,
    ).status_code == 403
    assert client.get("/api/v1/admin/config/security", headers=limited_headers).status_code == 403


def test_update_general_config_round_trips(client, seeded_db):
    headers = _admin_headers(client)
    resp = client.put(
        "/api/v1/admin/config/application/general",
        json={"name": "Everyticket Subscriptions (Staging)", "currency": "USD", "gateway_mode": "live"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Everyticket Subscriptions (Staging)"
    assert resp.json()["currency"] == "USD"
    assert resp.json()["gateway_mode"] == "live"

    refetched = client.get("/api/v1/admin/config/application", headers=headers)
    assert refetched.json()["general"]["name"] == "Everyticket Subscriptions (Staging)"

    # Restore defaults so later tests (e.g. the payment-gateway test below,
    # which relies on gateway_mode="test") aren't affected by this one.
    client.put(
        "/api/v1/admin/config/application/general",
        json={"name": "Everyticket Subscriptions", "currency": "INR", "gateway_mode": "test"},
        headers=headers,
    )


def test_update_integration_config_secret_never_echoed_back_and_extra_params_stored(client, seeded_db):
    headers = _admin_headers(client)
    resp = client.put(
        "/api/v1/admin/config/application/integration",
        json={
            "webhook_url": "https://everyticket.example.com/hooks",
            "secret_key": "s3cr3t",
            "extra_params": {"merchant_id": "MERCH-1"},
            "retry_limit": 3,
            "escalation_emails": "ops@example.com, billing@example.com",
            "escalation_email_subject": "Webhook down",
            "escalation_email_body": '<p onclick="x()">Please check <strong>Everyticket</strong>.</p>',
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "secret_key" not in body
    assert body["secret_key_is_set"] is True
    assert body["extra_params"] == {"merchant_id": "MERCH-1"}
    assert body["retry_limit"] == 3
    assert body["escalation_emails"] == "ops@example.com, billing@example.com"
    # sanitized the same way Plan.description is - onclick/attributes stripped.
    assert "onclick" not in body["escalation_email_body"]
    assert "<strong>Everyticket</strong>" in body["escalation_email_body"]


def test_update_payment_gateway_config_changes_gateway_for_new_payments_and_stores_credentials(client, seeded_db, monkeypatch):
    from app.core.config import get_settings

    # No env creds at all - forces the payment to actually use the
    # DB-stored (admin-configured) credentials below, not an env fallback.
    monkeypatch.setenv("PAYU_MERCHANT_KEY", "")
    monkeypatch.setenv("PAYU_MERCHANT_SALT", "")
    get_settings.cache_clear()

    headers = _admin_headers(client)
    try:
        resp = client.put(
            "/api/v1/admin/config/application/payment-gateway",
            json={
                "default_gateway": "payu",
                "payu_test": {"merchant_key": "dbkey123", "merchant_salt": "dbsalt456"},
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["default_gateway"] == "payu"
        assert resp.json()["payu_test"]["merchant_key_is_set"] is True

        subscribe = client.post(
            "/api/v1/public/plans/basic/subscribe",
            json={"email": "gatewayswitch@example.com", "mobile": "9833300001", "registration_data": {}},
        )
        assert subscribe.status_code == 200, subscribe.text
        assert subscribe.json()["payment"]["gateway"] == "payu"
        checkout = subscribe.json()["payment"]["checkout"]
        assert checkout is not None  # PayU is redirect-based - mock never sets this
        assert checkout["fields"]["key"] == "dbkey123"  # proves the DB-stored credential was actually used
    finally:
        client.put(
            "/api/v1/admin/config/application/payment-gateway", json={"default_gateway": "mock"}, headers=headers
        )
        get_settings.cache_clear()


def test_update_notification_config_changes_outbound_sender_and_smtp_host(client, seeded_db, monkeypatch):
    _FakeSMTP.sent.clear()
    _FakeSMTP.connected_to.clear()
    monkeypatch.setattr(smtp_provider.smtplib, "SMTP", _FakeSMTP)
    headers = _admin_headers(client)

    resp = client.put(
        "/api/v1/admin/config/application/notification",
        json={
            "email_provider": "smtp",
            "smtp_host": "smtp.everyticket-billing.example.com",
            "smtp_port": 2525,
            "email_sender_name": "Everyticket Billing",
            "email_sender_address": "billing@everyticket.example.com",
            "email_reply_to": "support@everyticket.example.com",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["smtp_host"] == "smtp.everyticket-billing.example.com"

    client.post(
        "/api/v1/public/plans/basic/subscribe",
        json={"email": "sender-override@example.com", "mobile": "9833300002", "registration_data": {}},
    )
    client.post("/api/v1/public/identify", json={"email": "sender-override@example.com", "mobile": "9833300002"})

    assert any("Everyticket Billing <billing@everyticket.example.com>" in m for m in _FakeSMTP.sent)
    assert ("smtp.everyticket-billing.example.com", 2525) in _FakeSMTP.connected_to

    # Restore defaults so later tests' emails use the app-wide sender/SMTP again.
    client.put(
        "/api/v1/admin/config/application/notification",
        json={
            "email_provider": "smtp", "smtp_host": None, "smtp_port": None,
            "email_sender_name": None, "email_sender_address": None, "email_reply_to": None,
        },
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
