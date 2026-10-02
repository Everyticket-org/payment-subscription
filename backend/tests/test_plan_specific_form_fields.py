"""Plan-specific registration questions (2026-10 Custom plan follow-up).

RegistrationFormField.plan_codes turns a field into a "Show only for plans"
question - seeded for the CUSTOM plan as expected_monthly_tickets /
average_ticket_price (app.plans.catalog.CUSTOM_PLAN_FORM_FIELDS). Covers:
  - the public form only returns them for the matching plan;
  - required + regex are enforced on /public/.../subscribe and the portal
    upgrade, for new and returning customers;
  - answers are stored per subscription and reach the
    subscription.activated webhook payload;
  - another plan's answers are dropped;
  - admin API normalises/validates plan_codes.
"""
import pytest

from app.core.seed import DEV_ADMIN_EMAIL, DEV_ADMIN_PASSWORD
from app.customers.models import CustomerRegistrationData
from app.plans.models import Plan
from app.subscriptions.models import Subscription
from app.webhooks.models import WebhookEvent

CUSTOM_ANSWERS = {"expected_monthly_tickets": "5000", "average_ticket_price": "249.50"}


@pytest.fixture()
def custom_self_serve(seeded_db):
    """The seeded CUSTOM plan is contact-sales ("Talk to us"); these tests
    cover it after an admin has given it a price, which is what makes it
    subscribable like any other plan."""
    plan = seeded_db.query(Plan).filter(Plan.plan_code == "CUSTOM").one()
    plan.is_contact_sales = False
    plan.price = 50000
    seeded_db.commit()
    return seeded_db


def _admin_headers(client) -> dict:
    login = client.post("/api/v1/admin/auth/login", json={"email": DEV_ADMIN_EMAIL, "password": DEV_ADMIN_PASSWORD})
    pre_mfa_token = login.json()["pre_mfa_token"]
    verify = client.post("/api/v1/admin/auth/mfa/verify", json={"pre_mfa_token": pre_mfa_token, "code": "BYPASS"})
    return {"Authorization": f"Bearer {verify.json()['access_token']}"}


def _customer_token(client, email, mobile):
    identify = client.post("/api/v1/public/identify", json={"email": email, "mobile": mobile})
    verify = client.post(
        "/api/v1/public/otp/verify", json={"otp_session_id": identify.json()["otp_session_id"], "code": "BYPASS"}
    )
    return verify.json()["access_token"]


def _subscribe(client, plan_code, email, mobile, registration_data):
    return client.post(
        f"/api/v1/public/plans/{plan_code}/subscribe",
        json={"email": email, "mobile": mobile, "registration_data": registration_data},
    )


def _pay(client, subscribe_resp):
    txn = subscribe_resp.json()["payment"]["transaction_id"]
    return client.post("/api/v1/payment/mock/callback", json={"transaction_id": txn, "scenario": "SUCCESS"})


# --- public form ---------------------------------------------------------


def test_public_form_returns_custom_questions_only_for_custom(client, seeded_db):
    general = {f["field_key"] for f in client.get("/api/v1/public/registration-form").json()}
    starter = {f["field_key"] for f in client.get("/api/v1/public/registration-form?plan_code=STARTER").json()}
    custom = client.get("/api/v1/public/registration-form?plan_code=custom").json()
    custom_keys = {f["field_key"] for f in custom}

    assert "museum_name" in general and "museum_name" in custom_keys
    assert not general & set(CUSTOM_ANSWERS)
    assert not starter & set(CUSTOM_ANSWERS)
    assert set(CUSTOM_ANSWERS) <= custom_keys
    ticket_field = next(f for f in custom if f["field_key"] == "expected_monthly_tickets")
    assert ticket_field["plan_codes"] == ["CUSTOM"]
    assert ticket_field["required"] is True


# --- new subscription ----------------------------------------------------


def test_custom_subscribe_requires_plan_questions(client, custom_self_serve):
    resp = _subscribe(client, "custom", "c1@example.com", "9600000001", {"museum_name": "M"})
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "REGISTRATION_DATA_INVALID"
    assert resp.json()["message"] == "Expected tickets per month is required"


def test_custom_subscribe_rejects_invalid_ticket_price(client, custom_self_serve):
    resp = _subscribe(
        client, "custom", "c2@example.com", "9600000002",
        {"expected_monthly_tickets": "5000", "average_ticket_price": "two hundred"},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["message"] == "Enter the average ticket price in rupees, e.g. 250 or 249.50"


def test_custom_subscribe_stores_answers_and_sends_them_in_activation_webhook(client, custom_self_serve):
    db = custom_self_serve
    resp = _subscribe(client, "custom", "c3@example.com", "9600000003", {"museum_name": "City Museum", **CUSTOM_ANSWERS})
    assert resp.status_code == 200, resp.text
    assert resp.json()["payment"]["amount"] == 50000.0
    assert _pay(client, resp).json()["subscription"]["status"] == "ACTIVE"

    subscription_id = resp.json()["subscription"]["subscription_id"]
    subscription = db.query(Subscription).filter(Subscription.subscription_id == subscription_id).one()
    row = db.query(CustomerRegistrationData).filter(CustomerRegistrationData.subscription_id == subscription.id).one()
    assert row.data == {"museum_name": "City Museum", **CUSTOM_ANSWERS}

    event = (
        db.query(WebhookEvent)
        .filter(WebhookEvent.event_type == "subscription.activated", WebhookEvent.entity_id == subscription_id)
        .one()
    )
    assert event.payload["expected_monthly_tickets"] == "5000"
    assert event.payload["average_ticket_price"] == "249.50"
    # Nested too, so Everyticket can tell plan answers from general registration data.
    assert event.payload["plan_details"] == CUSTOM_ANSWERS


def test_other_plans_answers_are_dropped(client, custom_self_serve):
    db = custom_self_serve
    resp = _subscribe(client, "basic", "c4@example.com", "9600000004", {"museum_name": "M", **CUSTOM_ANSWERS})
    assert resp.status_code == 200, resp.text
    row = db.query(CustomerRegistrationData).one()
    assert row.data == {"museum_name": "M"}
    _pay(client, resp)
    event = db.query(WebhookEvent).filter(WebhookEvent.event_type == "subscription.activated").one()
    assert "plan_details" not in event.payload


def test_non_custom_plan_unaffected_by_custom_required_questions(client, custom_self_serve):
    # General fields keep the lenient behaviour (required not enforced server-side).
    resp = _subscribe(client, "basic", "c5@example.com", "9600000005", {})
    assert resp.status_code == 200, resp.text


def test_returning_customer_answers_custom_questions_on_repurchase(client, custom_self_serve):
    db = custom_self_serve
    first = _subscribe(client, "basic", "c6@example.com", "9600000006", {"museum_name": "M"})
    _pay(client, first)
    # Lapsed (EXPIRED) - so the next subscribe is a fresh repurchase, not a plan change.
    lapsed = db.query(Subscription).filter(
        Subscription.subscription_id == first.json()["subscription"]["subscription_id"]
    ).one()
    lapsed.status = "EXPIRED"
    db.commit()
    token = _customer_token(client, "c6@example.com", "9600000006")
    headers = {"Authorization": f"Bearer {token}"}

    missing = client.post("/api/v1/public/plans/custom/subscribe", json={"registration_data": {}}, headers=headers)
    assert missing.status_code == 422, missing.text

    ok = client.post(
        "/api/v1/public/plans/custom/subscribe", json={"registration_data": CUSTOM_ANSWERS}, headers=headers
    )
    assert ok.status_code == 200, ok.text
    new_sub = db.query(Subscription).filter(Subscription.subscription_id == ok.json()["subscription"]["subscription_id"]).one()
    row = db.query(CustomerRegistrationData).filter(CustomerRegistrationData.subscription_id == new_sub.id).one()
    assert row.data == CUSTOM_ANSWERS


# --- portal upgrade ------------------------------------------------------


def test_portal_upgrade_to_custom_requires_and_stores_answers(client, custom_self_serve):
    db = custom_self_serve
    first = _subscribe(client, "basic", "c7@example.com", "9600000007", {"museum_name": "M"})
    _pay(client, first)
    sub_id = first.json()["subscription"]["subscription_id"]
    headers = {"Authorization": f"Bearer {_customer_token(client, 'c7@example.com', '9600000007')}"}
    url = f"/api/v1/customer/subscriptions/{sub_id}/upgrade"

    missing = client.post(url, json={"target_plan_code": "custom"}, headers=headers)
    assert missing.status_code == 422, missing.text

    ok = client.post(
        url,
        json={"target_plan_code": "custom", "registration_data": {"museum_name": "ignored", **CUSTOM_ANSWERS}},
        headers=headers,
    )
    assert ok.status_code == 200, ok.text
    assert _pay(client, ok).json()["subscription"]["status"] == "ACTIVE"

    subscription = db.query(Subscription).filter(Subscription.subscription_id == sub_id).one()
    rows = (
        db.query(CustomerRegistrationData)
        .filter(CustomerRegistrationData.subscription_id == subscription.id)
        .order_by(CustomerRegistrationData.id)
        .all()
    )
    # first-signup data untouched + a new row holding only the Custom answers
    assert [r.data for r in rows] == [{"museum_name": "M"}, CUSTOM_ANSWERS]
    event = db.query(WebhookEvent).filter(WebhookEvent.event_type == "subscription.upgraded").one()
    assert event.payload["plan_code"] == "CUSTOM"
    assert event.payload["plan_details"] == CUSTOM_ANSWERS


def test_portal_upgrade_to_plan_without_questions_needs_no_answers(client, custom_self_serve):
    first = _subscribe(client, "basic", "c8@example.com", "9600000008", {})
    _pay(client, first)
    sub_id = first.json()["subscription"]["subscription_id"]
    headers = {"Authorization": f"Bearer {_customer_token(client, 'c8@example.com', '9600000008')}"}
    resp = client.post(
        f"/api/v1/customer/subscriptions/{sub_id}/upgrade", json={"target_plan_code": "professional"}, headers=headers
    )
    assert resp.status_code == 200, resp.text


# --- admin API -----------------------------------------------------------


def test_admin_plan_codes_normalised_validated_and_clearable(client, seeded_db):
    headers = _admin_headers(client)
    created = client.post(
        "/api/v1/admin/registration-form",
        json={
            "field_key": "number_of_venues", "label": "Number of venues", "field_type": "number",
            "plan_codes": [" custom ", "CUSTOM", "starter"], "display_order": 103,
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["plan_codes"] == ["CUSTOM", "STARTER"]

    unknown = client.post(
        "/api/v1/admin/registration-form",
        json={"field_key": "x_field", "label": "X", "field_type": "text", "plan_codes": ["NOPE"]},
        headers=headers,
    )
    assert unknown.status_code == 422, unknown.text
    assert unknown.json()["error_code"] == "UNKNOWN_PLAN_CODES"

    field_id = created.json()["id"]
    cleared = client.put(f"/api/v1/admin/registration-form/{field_id}", json={"plan_codes": []}, headers=headers)
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["plan_codes"] is None
    general = {f["field_key"] for f in client.get("/api/v1/public/registration-form").json()}
    assert "number_of_venues" in general
