"""
Admin CRUD API (spec sections 12, 51-56).

Covers: permission-gated access (no token / wrong permission -> 401/403),
Plans full CRUD (plan + features + transitions), and the read-only
Customers/Subscriptions/Payments/Invoices/Webhook Logs/Notification Logs/
Audit Logs modules, plus the one real mutation each of those allows
(customer suspend/activate, webhook delivery retry, template edit).
"""
from app.core.seed import DEV_ADMIN_EMAIL, DEV_ADMIN_PASSWORD


def _admin_token(client) -> str:
    login = client.post("/api/v1/admin/auth/login", json={"email": DEV_ADMIN_EMAIL, "password": DEV_ADMIN_PASSWORD})
    assert login.status_code == 200, login.text
    pre_mfa_token = login.json()["pre_mfa_token"]
    verify = client.post("/api/v1/admin/auth/mfa/verify", json={"pre_mfa_token": pre_mfa_token, "code": "BYPASS"})
    assert verify.status_code == 200, verify.text
    return verify.json()["access_token"]


def _admin_headers(client) -> dict:
    return {"Authorization": f"Bearer {_admin_token(client)}"}


def _new_active_subscription(client, plan_code, email, mobile):
    resp = client.post(
        f"/api/v1/public/plans/{plan_code}/subscribe",
        json={"email": email, "mobile": mobile, "registration_data": {}},
    )
    transaction_id = resp.json()["payment"]["transaction_id"]
    subscription_id = resp.json()["subscription"]["subscription_id"]
    client.post("/api/v1/payment/mock/callback", json={"transaction_id": transaction_id, "scenario": "SUCCESS"})
    return subscription_id


def test_admin_endpoint_requires_auth(client, seeded_db):
    resp = client.get("/api/v1/admin/dashboard")
    assert resp.status_code == 401


def test_dashboard_returns_stats(client, seeded_db):
    _new_active_subscription(client, "basic", "dash@example.com", "9800000001")
    headers = _admin_headers(client)

    resp = client.get("/api/v1/admin/dashboard", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["active_subscriptions"] >= 1
    assert body["revenue_30d"] >= 2000.0


def test_plans_full_crud_flow(client, seeded_db):
    headers = _admin_headers(client)

    create = client.post(
        "/api/v1/admin/plans",
        json={"plan_code": "STARTER", "name": "Starter", "price": 999, "billing_interval": "month", "billing_frequency": 1},
        headers=headers,
    )
    assert create.status_code == 201, create.text
    assert create.json()["plan_code"] == "STARTER"
    assert create.json()["active"] is True

    duplicate = client.post(
        "/api/v1/admin/plans", json={"plan_code": "STARTER", "name": "Dup", "price": 1}, headers=headers
    )
    assert duplicate.status_code == 409

    listing = client.get("/api/v1/admin/plans", headers=headers)
    assert listing.status_code == 200
    assert any(p["plan_code"] == "STARTER" for p in listing.json())

    detail = client.get("/api/v1/admin/plans/starter", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["name"] == "Starter"

    update = client.put("/api/v1/admin/plans/starter", json={"price": 1200, "active": False}, headers=headers)
    assert update.status_code == 200
    assert update.json()["price"] == 1200.0
    assert update.json()["active"] is False

    feature = client.post(
        "/api/v1/admin/plans/starter/features",
        json={"feature_key": "support", "feature_label": "Email support", "display_order": 1},
        headers=headers,
    )
    assert feature.status_code == 201, feature.text
    feature_id = feature.json()["id"]

    feature_update = client.put(
        f"/api/v1/admin/plans/starter/features/{feature_id}",
        json={"feature_label": "Priority email support"},
        headers=headers,
    )
    assert feature_update.status_code == 200
    assert feature_update.json()["feature_label"] == "Priority email support"

    feature_delete = client.delete(f"/api/v1/admin/plans/starter/features/{feature_id}", headers=headers)
    assert feature_delete.status_code == 204

    transition_create = client.post(
        "/api/v1/admin/plans/transitions",
        json={"from_plan_code": "STARTER", "to_plan_code": "BASIC", "transition_type": "UPGRADE"},
        headers=headers,
    )
    assert transition_create.status_code == 201, transition_create.text
    transition_id = transition_create.json()["id"]

    transitions = client.get("/api/v1/admin/plans/transitions", headers=headers)
    assert transitions.status_code == 200
    assert any(t["id"] == transition_id for t in transitions.json())

    transition_delete = client.delete(f"/api/v1/admin/plans/transitions/{transition_id}", headers=headers)
    assert transition_delete.status_code == 204


def test_customers_list_detail_suspend_activate(client, seeded_db):
    subscription_id = _new_active_subscription(client, "basic", "custadmin@example.com", "9800000002")
    headers = _admin_headers(client)

    listing = client.get("/api/v1/admin/customers", params={"q": "custadmin"}, headers=headers)
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] >= 1
    customer_id = listing.json()["items"][0]["customer_id"]

    detail = client.get(f"/api/v1/admin/customers/{customer_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    assert detail.json()["customer"]["customer_id"] == customer_id
    assert any(s["subscription_id"] == subscription_id for s in detail.json()["subscriptions"])
    assert len(detail.json()["payments"]) >= 1
    assert len(detail.json()["invoices"]) >= 1

    suspend = client.post(f"/api/v1/admin/customers/{customer_id}/suspend", json={"reason": "test"}, headers=headers)
    assert suspend.status_code == 200
    assert suspend.json()["status"] == "SUSPENDED"

    activate = client.post(f"/api/v1/admin/customers/{customer_id}/activate", headers=headers)
    assert activate.status_code == 200
    assert activate.json()["status"] == "ACTIVE"


def test_subscriptions_payments_invoices_read_only(client, seeded_db):
    subscription_id = _new_active_subscription(client, "professional", "readonly@example.com", "9800000003")
    headers = _admin_headers(client)

    sub_list = client.get("/api/v1/admin/subscriptions", params={"status": "ACTIVE"}, headers=headers)
    assert sub_list.status_code == 200
    assert any(s["subscription_id"] == subscription_id for s in sub_list.json()["items"])

    sub_detail = client.get(f"/api/v1/admin/subscriptions/{subscription_id}", headers=headers)
    assert sub_detail.status_code == 200
    assert sub_detail.json()["subscription"]["subscription_id"] == subscription_id
    assert len(sub_detail.json()["history"]) >= 1

    pay_list = client.get("/api/v1/admin/payments", params={"status": "SUCCESS"}, headers=headers)
    assert pay_list.status_code == 200
    assert pay_list.json()["total"] >= 1
    transaction_id = pay_list.json()["items"][0]["transaction_id"]

    pay_detail = client.get(f"/api/v1/admin/payments/{transaction_id}", headers=headers)
    assert pay_detail.status_code == 200
    assert pay_detail.json()["transaction_id"] == transaction_id

    inv_list = client.get("/api/v1/admin/invoices", headers=headers)
    assert inv_list.status_code == 200
    assert inv_list.json()["total"] >= 1
    invoice_id = inv_list.json()["items"][0]["invoice_id"]

    inv_detail = client.get(f"/api/v1/admin/invoices/{invoice_id}", headers=headers)
    assert inv_detail.status_code == 200
    assert inv_detail.json()["invoice_id"] == invoice_id
    assert len(inv_detail.json()["items"]) >= 1


def test_webhook_logs_and_retry(client, seeded_db, db_session):
    headers = _admin_headers(client)

    # No webhook destination is configured for the seeded application by
    # default, so queue_event() (called from PaymentService on SUCCESS)
    # silently skips - point the seeded application at a destination
    # first (same fixture-setup pattern tests/test_webhooks.py uses)
    # so this test actually has an event/delivery row to read back.
    from app.applications.models import Application

    app_row = db_session.query(Application).filter(Application.code == "EVERYTICKET").first()
    app_row.webhook_url = "https://example.invalid/webhook"
    app_row.webhook_secret = "test-secret"
    db_session.add(app_row)
    db_session.commit()

    _new_active_subscription(client, "basic", "webhooklog@example.com", "9800000004")

    events = client.get("/api/v1/admin/webhooks/events", headers=headers)
    assert events.status_code == 200, events.text
    assert events.json()["total"] >= 1

    deliveries = client.get("/api/v1/admin/webhooks/deliveries", headers=headers)
    assert deliveries.status_code == 200
    assert deliveries.json()["total"] >= 1
    delivery_id = deliveries.json()["items"][0]["id"]

    retry = client.post(f"/api/v1/admin/webhooks/deliveries/{delivery_id}/retry", headers=headers)
    assert retry.status_code == 200, retry.text
    assert retry.json()["status"] == "PENDING"


def test_notification_templates_and_logs(client, seeded_db):
    headers = _admin_headers(client)

    templates = client.get("/api/v1/admin/notifications/templates", headers=headers)
    assert templates.status_code == 200
    assert any(t["template_code"] == "otp_verification" for t in templates.json())

    update = client.put(
        "/api/v1/admin/notifications/templates/otp_verification",
        json={"subject": "Your updated verification code"},
        headers=headers,
    )
    assert update.status_code == 200
    assert update.json()["subject"] == "Your updated verification code"

    # OTP verification emails are only sent on an "exact" identify match
    # (an already-registered customer) - see app.api.v1.public.identify and
    # tests/test_otp_and_duplicate_detection.py for the same pattern.
    _new_active_subscription(client, "basic", "notiflog@example.com", "9800000005")
    client.post("/api/v1/public/identify", json={"email": "notiflog@example.com", "mobile": "9800000005"})
    logs = client.get("/api/v1/admin/notifications/logs", headers=headers)
    assert logs.status_code == 200
    assert logs.json()["total"] >= 1


def test_audit_logs_capture_admin_actions(client, seeded_db):
    headers = _admin_headers(client)
    client.post(
        "/api/v1/admin/plans",
        json={"plan_code": "AUDITCHECK", "name": "Audit Check", "price": 1},
        headers=headers,
    )

    logs = client.get("/api/v1/admin/audit-logs", params={"action": "PLAN_CREATED"}, headers=headers)
    assert logs.status_code == 200
    assert any(entry["entity_id"] == "AUDITCHECK" for entry in logs.json()["items"])


def test_admin_without_permission_gets_403(client, seeded_db, db_session):
    """A valid admin token with no roles/permissions (e.g. a future
    limited-scope admin account) must be rejected by require_permission
    with 403, distinct from the 401 an invalid/missing token gets."""
    from app.auth import service as auth_service

    limited_user = auth_service.create_admin_user(
        db_session, email="limited@example.com", full_name="Limited Admin", password="LimitedPass123!", mfa_enabled=False
    )
    db_session.commit()

    login = client.post("/api/v1/admin/auth/login", json={"email": "limited@example.com", "password": "LimitedPass123!"})
    assert login.status_code == 200, login.text
    assert login.json()["mfa_required"] is False
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = client.get("/api/v1/admin/dashboard", headers=headers)
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "FORBIDDEN"


def test_registration_form_public_and_admin_crud(client, seeded_db):
    # Public: the seeded fields (museum_name, contact_person, gstin,
    # address) are readable with no auth at all - this is what the
    # dynamic form renderer (spec section 8) fetches.
    public = client.get("/api/v1/public/registration-form")
    assert public.status_code == 200, public.text
    keys = {f["field_key"] for f in public.json()}
    assert {"museum_name", "contact_person"}.issubset(keys)

    headers = _admin_headers(client)

    create = client.post(
        "/api/v1/admin/registration-form",
        json={"field_key": "tax_id", "label": "Tax ID", "field_type": "text", "required": False},
        headers=headers,
    )
    assert create.status_code == 201, create.text
    field_id = create.json()["id"]

    duplicate = client.post(
        "/api/v1/admin/registration-form",
        json={"field_key": "tax_id", "label": "Dup", "field_type": "text"},
        headers=headers,
    )
    assert duplicate.status_code == 409

    listing = client.get("/api/v1/admin/registration-form", headers=headers)
    assert listing.status_code == 200
    assert any(f["field_key"] == "tax_id" for f in listing.json())

    update = client.put(
        f"/api/v1/admin/registration-form/{field_id}",
        json={"label": "GST/Tax ID", "required": True},
        headers=headers,
    )
    assert update.status_code == 200
    assert update.json()["label"] == "GST/Tax ID"
    assert update.json()["required"] is True

    # New field should now show up on the public endpoint too.
    public_after = client.get("/api/v1/public/registration-form")
    assert any(f["field_key"] == "tax_id" for f in public_after.json())

    deactivate = client.put(
        f"/api/v1/admin/registration-form/{field_id}", json={"active": False}, headers=headers
    )
    assert deactivate.status_code == 200
    assert deactivate.json()["active"] is False

    public_after_deactivate = client.get("/api/v1/public/registration-form")
    assert not any(f["field_key"] == "tax_id" for f in public_after_deactivate.json())
