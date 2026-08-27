"""Upgrade / downgrade / renew / cancel (spec sections 16, 38, 42-43)."""


def _new_active_subscription(client, plan_code, email, mobile):
    resp = client.post(
        f"/api/v1/public/plans/{plan_code}/subscribe",
        json={"email": email, "mobile": mobile, "registration_data": {}},
    )
    transaction_id = resp.json()["payment"]["transaction_id"]
    subscription_id = resp.json()["subscription"]["subscription_id"]
    client.post("/api/v1/payment/mock/callback", json={"transaction_id": transaction_id, "scenario": "SUCCESS"})
    return subscription_id


def _customer_token(client, email, mobile):
    identify = client.post("/api/v1/public/identify", json={"email": email, "mobile": mobile})
    otp_session_id = identify.json()["otp_session_id"]
    verify = client.post("/api/v1/public/otp/verify", json={"otp_session_id": otp_session_id, "code": "BYPASS"})
    return verify.json()["access_token"]


def test_upgrade_basic_to_professional(client, seeded_db):
    subscription_id = _new_active_subscription(client, "basic", "upgrade@example.com", "9700000001")
    token = _customer_token(client, "upgrade@example.com", "9700000001")
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        f"/api/v1/customer/subscriptions/{subscription_id}/upgrade",
        json={"target_plan_code": "professional"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    txn = resp.json()["payment"]["transaction_id"]
    assert resp.json()["payment"]["amount"] == 5000.0

    callback = client.post("/api/v1/payment/mock/callback", json={"transaction_id": txn, "scenario": "SUCCESS"})
    assert callback.json()["subscription"]["status"] == "ACTIVE"

    portal = client.get("/api/v1/customer/me", headers=headers)
    assert portal.status_code == 200
    assert portal.json()["active_subscription"]["plan_code"] == "PROFESSIONAL"


def test_downgrade_enterprise_to_basic(client, seeded_db):
    subscription_id = _new_active_subscription(client, "enterprise", "downgrade@example.com", "9700000002")
    token = _customer_token(client, "downgrade@example.com", "9700000002")
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        f"/api/v1/customer/subscriptions/{subscription_id}/downgrade",
        json={"target_plan_code": "basic"},
        headers=headers,
    )
    assert resp.status_code == 200
    txn = resp.json()["payment"]["transaction_id"]
    client.post("/api/v1/payment/mock/callback", json={"transaction_id": txn, "scenario": "SUCCESS"})

    portal = client.get("/api/v1/customer/me", headers=headers)
    assert portal.json()["active_subscription"]["plan_code"] == "BASIC"


def test_failed_upgrade_payment_keeps_current_plan_active(client, seeded_db):
    subscription_id = _new_active_subscription(client, "basic", "failupgrade@example.com", "9700000003")
    token = _customer_token(client, "failupgrade@example.com", "9700000003")
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        f"/api/v1/customer/subscriptions/{subscription_id}/upgrade",
        json={"target_plan_code": "professional"},
        headers=headers,
    )
    txn = resp.json()["payment"]["transaction_id"]
    callback = client.post("/api/v1/payment/mock/callback", json={"transaction_id": txn, "scenario": "FAILED"})
    # Spec section 42: if the upgrade payment fails, the existing plan
    # remains active - it must NOT flip to PAYMENT_FAILED (that's only for
    # a still-pending NEW subscription).
    assert callback.json()["subscription"]["status"] == "ACTIVE"

    portal = client.get("/api/v1/customer/me", headers=headers)
    assert portal.json()["active_subscription"]["plan_code"] == "BASIC"


def test_invalid_transition_rejected(client, seeded_db):
    subscription_id = _new_active_subscription(client, "basic", "invalidtrans@example.com", "9700000004")
    token = _customer_token(client, "invalidtrans@example.com", "9700000004")
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        f"/api/v1/customer/subscriptions/{subscription_id}/upgrade",
        json={"target_plan_code": "basic"},  # same plan - not a real transition
        headers=headers,
    )
    assert resp.status_code == 409
    assert resp.json()["error_code"] == "INVALID_PLAN_TRANSITION"


def test_renew_extends_expiry(client, seeded_db):
    subscription_id = _new_active_subscription(client, "basic", "renew@example.com", "9700000005")
    token = _customer_token(client, "renew@example.com", "9700000005")
    headers = {"Authorization": f"Bearer {token}"}

    before = client.get("/api/v1/customer/me", headers=headers).json()["active_subscription"]["expires_at"]

    resp = client.post(f"/api/v1/customer/subscriptions/{subscription_id}/renew", headers=headers)
    txn = resp.json()["payment"]["transaction_id"]
    client.post("/api/v1/payment/mock/callback", json={"transaction_id": txn, "scenario": "SUCCESS"})

    after = client.get("/api/v1/customer/me", headers=headers).json()["active_subscription"]["expires_at"]
    assert after > before


def test_cancel_is_immediate_and_owned_only(client, seeded_db):
    subscription_id = _new_active_subscription(client, "basic", "cancelme@example.com", "9700000006")
    token = _customer_token(client, "cancelme@example.com", "9700000006")
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        f"/api/v1/customer/subscriptions/{subscription_id}/cancel",
        json={"reason": "Testing cancellation"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "CANCELLED"

    # Someone else's token cannot see/act on this subscription.
    _new_active_subscription(client, "basic", "someoneelse@example.com", "9700000099")
    other_token = _customer_token(client, "someoneelse@example.com", "9700000099")
    forbidden = client.post(
        f"/api/v1/customer/subscriptions/{subscription_id}/cancel", json={}, headers={"Authorization": f"Bearer {other_token}"}
    )
    assert forbidden.status_code == 404


def test_customer_endpoints_require_auth(client, seeded_db):
    assert client.get("/api/v1/customer/me").status_code == 401
