"""2026-09 pricing refresh: Starter / Institutional / Custom catalog and
"Talk to us" (contact-sales) plans that can never be self-served."""
from app.core.seed import seed
from app.customers.models import Customer
from app.plans.models import Plan
from app.subscriptions.models import Subscription
from tests.test_admin_api import _admin_headers, _new_active_subscription
from tests.test_subscription_lifecycle import _customer_token


def _public_plans(client) -> dict:
    resp = client.get("/api/v1/public/plans")
    assert resp.status_code == 200, resp.text
    return {plan["plan_code"]: plan for plan in resp.json()}


def test_public_catalog_lists_new_plans_with_features(client, seeded_db):
    plans = _public_plans(client)

    assert plans["STARTER"]["price"] == 6999.0
    assert plans["INSTITUTIONAL"]["price"] == 14999.0
    assert plans["CUSTOM"]["is_contact_sales"] is True
    assert plans["CUSTOM"]["price"] == 0.0
    assert plans["STARTER"]["is_contact_sales"] is False

    starter_features = {f["feature_key"]: f for f in plans["STARTER"]["features"]}
    assert starter_features["monthly_ticket_limit"]["feature_value"] == "2,000 tickets"
    assert starter_features["staff_accounts"]["feature_value"] is None
    institutional_features = {f["feature_key"]: f for f in plans["INSTITUTIONAL"]["features"]}
    assert institutional_features["ticket_overage"]["feature_value"] == "₹4 per ticket beyond 4,000"

    trial_features = {f["feature_key"] for f in plans["FREE_TRIAL"]["features"]}
    assert {"free_tickets", "ticket_overage"} <= trial_features


def test_default_seed_retires_legacy_plans(client, db_session):
    # The production/dev default - unlike the seeded_db fixture, which keeps
    # the legacy plans active for the lifecycle tests.
    seed(db_session)
    plans = _public_plans(client)

    assert set(plans) == {"FREE_TRIAL", "STARTER", "INSTITUTIONAL", "CUSTOM"}
    assert [code for code in plans] == ["FREE_TRIAL", "STARTER", "INSTITUTIONAL", "CUSTOM"]
    legacy = db_session.query(Plan).filter(Plan.plan_code.in_(["BASIC", "PROFESSIONAL", "ENTERPRISE"])).all()
    assert len(legacy) == 3 and not any(plan.active for plan in legacy)


def test_seed_is_idempotent_for_features(client, seeded_db):
    seed(seeded_db, legacy_plans_active=True)
    plans = _public_plans(client)
    keys = [f["feature_key"] for f in plans["STARTER"]["features"]]
    assert len(keys) == len(set(keys))


def test_subscribe_to_contact_sales_plan_is_refused_without_creating_a_customer(client, seeded_db):
    resp = client.post(
        "/api/v1/public/plans/custom/subscribe",
        json={"email": "custom@example.com", "mobile": "9600000001", "registration_data": {}},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "PLAN_REQUIRES_SALES_CONTACT"
    assert seeded_db.query(Customer).filter(Customer.email == "custom@example.com").first() is None
    assert seeded_db.query(Subscription).count() == 0


def test_portal_upgrade_to_contact_sales_plan_is_refused(client, seeded_db):
    subscription_id = _new_active_subscription(client, "starter", "tocustom@example.com", "9600000002")
    token = _customer_token(client, "tocustom@example.com", "9600000002")

    resp = client.post(
        f"/api/v1/customer/subscriptions/{subscription_id}/downgrade",  # price 0 would classify as a downgrade
        json={"target_plan_code": "custom"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "PLAN_REQUIRES_SALES_CONTACT"

    portal = client.get("/api/v1/customer/me", headers={"Authorization": f"Bearer {token}"})
    assert portal.json()["active_subscription"]["plan_code"] == "STARTER"


def test_signed_in_subscribe_to_contact_sales_plan_is_refused(client, seeded_db):
    # The auto-routed upgrade/downgrade path for an existing customer.
    _new_active_subscription(client, "institutional", "autoroute@example.com", "9600000003")
    token = _customer_token(client, "autoroute@example.com", "9600000003")

    resp = client.post(
        "/api/v1/public/plans/custom/subscribe",
        json={"registration_data": {}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "PLAN_REQUIRES_SALES_CONTACT"


def test_admin_contact_sales_plan_validation(client, seeded_db):
    headers = _admin_headers(client)

    priced = client.post(
        "/api/v1/admin/plans",
        json={"plan_code": "BADSALES1", "name": "Bad", "price": 100, "is_contact_sales": True},
        headers=headers,
    )
    assert priced.status_code == 422, priced.text
    assert priced.json()["error_code"] == "INVALID_PLAN_CONFIGURATION"

    trial_and_sales = client.post(
        "/api/v1/admin/plans",
        json={
            "plan_code": "BADSALES2", "name": "Bad", "price": 0,
            "is_contact_sales": True, "is_trial": True, "trial_period_days": 7,
        },
        headers=headers,
    )
    assert trial_and_sales.status_code == 422, trial_and_sales.text

    ok = client.post(
        "/api/v1/admin/plans",
        json={"plan_code": "SALESONLY", "name": "Sales only", "price": 0, "is_contact_sales": True},
        headers=headers,
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["is_contact_sales"] is True

    # Switching it back to a normal plan needs a real price in the same PUT.
    unpriced = client.put("/api/v1/admin/plans/SALESONLY", json={"is_contact_sales": False}, headers=headers)
    assert unpriced.status_code == 422, unpriced.text
    repriced = client.put(
        "/api/v1/admin/plans/SALESONLY", json={"is_contact_sales": False, "price": 999}, headers=headers
    )
    assert repriced.status_code == 200, repriced.text


def test_support_email_is_configurable_and_public(client, seeded_db):
    headers = _admin_headers(client)
    body = {"name": "Everyticket", "currency": "INR", "gateway_mode": "test", "support_email": "sales@example.com"}

    resp = client.put("/api/v1/admin/config/application/general", json=body, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["support_email"] == "sales@example.com"
    assert client.get("/api/v1/public/messages").json()["support_email"] == "sales@example.com"

    invalid = client.put(
        "/api/v1/admin/config/application/general", json={**body, "support_email": "not-an-email"}, headers=headers
    )
    assert invalid.status_code == 422

    cleared = client.put(
        "/api/v1/admin/config/application/general", json={**body, "support_email": ""}, headers=headers
    )
    assert cleared.status_code == 200, cleared.text
    assert client.get("/api/v1/public/messages").json()["support_email"] is None
