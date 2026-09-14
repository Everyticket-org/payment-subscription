"""
Free trial plan (spec follow-up, 2026-09): a trial is its own distinct Plan
(price=0, is_trial=True, configurable trial_period_days) rather than an
attribute of an existing paid plan - "process will be the same" per the
feature request, refined by Vishal's four explicit numbered requirements:

    1. before trial over - email to renew
    2. once trial over, make subscription expired and call webhook again
    3. one credentials can take only one trial lifetime
    4. make sure security, if multiple trial scripts has been fired then
       it will create unnecessary dumping

Covers (in order): admin cross-field validation on create/update, the
subscribe->activate flow using a day-based (not month/year) billing period,
one-trial-per-customer-lifetime enforcement across subscription statuses,
blocking a trial as an upgrade/downgrade target (both the dedicated
endpoints and the /public/subscribe auto-routing path), blocking renewal of
a trial subscription, the existing expiry sweep expiring a trial and
re-queuing the subscription.expired webhook (item 2 - zero new code needed
there, verified here anyway), the trial-ending reminder email using the
'trial_ending' template instead of 'renewal_reminder', and the application-
level IntegrityError->TrialAlreadyUsed race-condition translation (item 4).

Like the existing one-active-subscription-per-customer rule (see
conftest.py's own docstring), the real DB-level guarantee here is a
Postgres-only partial unique index
(uq_one_trial_subscription_per_customer_application) that this SQLite test
suite cannot exercise directly - verified separately against real Postgres
when the migration is applied. What IS verified here, at the application
level: the pre-check (assert_trial_not_already_used, exercised through the
HTTP layer below) AND the IntegrityError-catching code path itself (via a
direct unit test that mocks db.flush() to simulate a lost race), so the
race-condition handling code is exercised even though the real constraint
that would trigger it in production isn't present in this test database.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.exc import IntegrityError

from app.applications.models import Application
from app.core.config import get_settings
from app.core.exceptions import TrialAlreadyUsed
from app.core.seed import DEV_ADMIN_EMAIL, DEV_ADMIN_PASSWORD
from app.customers import service as customer_service
from app.invoices.models import Invoice
from app.notifications.models import NotificationLog
from app.plans.models import Plan
from app.subscriptions import service as subscription_service
from app.subscriptions.models import Subscription
from app.webhooks.models import WebhookEvent

from tests.test_email_service import fake_smtp_success
from tests.test_subscription_lifecycle import _customer_token, _new_active_subscription


def _admin_headers(client):
    """Dev-seeded admin has MFA enabled (see app.core.seed) - log in, then
    complete MFA with the dev/staging "BYPASS" code (the application is
    seeded with mfa_bypass_enabled=True) to get a usable access token."""
    login = client.post(
        "/api/v1/admin/auth/login", json={"email": DEV_ADMIN_EMAIL, "password": DEV_ADMIN_PASSWORD}
    )
    body = login.json()
    if body.get("mfa_required"):
        verify = client.post(
            "/api/v1/admin/auth/mfa/verify",
            json={"pre_mfa_token": body["pre_mfa_token"], "code": "BYPASS"},
        )
        token = verify.json()["access_token"]
    else:
        token = body["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _subscribe_and_activate_trial(client, email, mobile):
    resp = client.post(
        "/api/v1/public/plans/free_trial/subscribe",
        json={"email": email, "mobile": mobile, "registration_data": {}},
    )
    assert resp.status_code == 200, resp.text
    txn = resp.json()["payment"]["transaction_id"]
    callback = client.post("/api/v1/payment/mock/callback", json={"transaction_id": txn, "scenario": "SUCCESS"})
    assert callback.status_code == 200, callback.text
    return resp.json()["subscription"]["subscription_id"]


# --- Admin cross-field validation (app/api/v1/admin_plans.py) ---


def test_create_trial_plan_requires_zero_price(client, seeded_db):
    headers = _admin_headers(client)
    resp = client.post(
        "/api/v1/admin/plans",
        json={"plan_code": "BADTRIAL1", "name": "Bad Trial", "price": 500, "is_trial": True, "trial_period_days": 7},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "INVALID_PLAN_CONFIGURATION"


def test_create_trial_plan_requires_positive_trial_period_days(client, seeded_db):
    headers = _admin_headers(client)
    resp = client.post(
        "/api/v1/admin/plans",
        json={"plan_code": "BADTRIAL2", "name": "Bad Trial", "price": 0, "is_trial": True},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "INVALID_PLAN_CONFIGURATION"


def test_create_non_trial_plan_requires_positive_price(client, seeded_db):
    headers = _admin_headers(client)
    resp = client.post(
        "/api/v1/admin/plans",
        json={"plan_code": "BADPRICE", "name": "Free Forever", "price": 0, "is_trial": False},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "INVALID_PLAN_CONFIGURATION"


def test_create_valid_trial_plan(client, seeded_db):
    headers = _admin_headers(client)
    resp = client.post(
        "/api/v1/admin/plans",
        json={
            "plan_code": "GOODTRIAL",
            "name": "Good Trial",
            "price": 0,
            "is_trial": True,
            "trial_period_days": 21,
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["is_trial"] is True
    assert body["trial_period_days"] == 21
    assert body["price"] == 0.0


def test_update_plan_into_trial_without_duration_rejected(client, seeded_db):
    """A partial PUT that only sets is_trial=True (leaving trial_period_days
    unset) must be validated against the MERGED effective state, not just
    the fields the request happened to include."""
    headers = _admin_headers(client)
    resp = client.put("/api/v1/admin/plans/basic", json={"is_trial": True}, headers=headers)
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "INVALID_PLAN_CONFIGURATION"


def test_update_trial_plan_price_to_nonzero_rejected(client, seeded_db):
    """FREE_TRIAL is already is_trial=True in the seed data - a PUT that
    only changes price (leaving is_trial untouched) must still be caught
    against the plan's existing is_trial=True."""
    headers = _admin_headers(client)
    resp = client.put("/api/v1/admin/plans/free_trial", json={"price": 999}, headers=headers)
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "INVALID_PLAN_CONFIGURATION"


def test_update_trial_plan_to_non_trial_without_price_rejected(client, seeded_db):
    headers = _admin_headers(client)
    resp = client.put("/api/v1/admin/plans/free_trial", json={"is_trial": False}, headers=headers)
    assert resp.status_code == 422, resp.text
    assert resp.json()["error_code"] == "INVALID_PLAN_CONFIGURATION"


# --- Subscribe/activate flow: day-based billing period ---


def test_trial_subscribe_and_activate_uses_day_based_expiry(client, seeded_db):
    subscription_id = _subscribe_and_activate_trial(client, "trial1@example.com", "9800000001")

    subscription = seeded_db.query(Subscription).filter(Subscription.subscription_id == subscription_id).first()
    seeded_db.refresh(subscription)
    assert subscription.status == "ACTIVE"
    assert subscription.is_trial is True

    application = seeded_db.query(Application).filter(Application.code == "EVERYTICKET").first()
    plan = seeded_db.query(Plan).filter(Plan.application_id == application.id, Plan.plan_code == "FREE_TRIAL").first()
    assert plan.trial_period_days == 14  # seeded duration

    delta = subscription.expires_at - subscription.starts_at
    assert delta.days == 14  # day-based, NOT the month/year billing_interval a paid plan would use

    token = _customer_token(client, "trial1@example.com", "9800000001")
    portal = client.get("/api/v1/customer/me", headers={"Authorization": f"Bearer {token}"}).json()
    assert portal["active_subscription"]["is_trial"] is True
    assert portal["active_subscription"]["plan_code"] == "FREE_TRIAL"


def test_trial_subscription_is_free(client, seeded_db):
    resp = client.post(
        "/api/v1/public/plans/free_trial/subscribe",
        json={"email": "trialfree@example.com", "mobile": "9800000002", "registration_data": {}},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["payment"]["amount"] == 0.0


def test_trial_subscribe_skips_payment_gateway_and_activates_immediately(client, seeded_db):
    """2026-09-13 follow-up: "if price of plan is 0 then no need to
    redirect to payment gateway" - a free trial (the only plan shape that
    can ever be priced at 0, see app/api/v1/admin_plans.py's cross-field
    validation) must come back from /subscribe already ACTIVE/SUCCESS,
    with its invoice already generated, rather than sitting in
    PENDING_PAYMENT/INITIATED awaiting a mock-gateway "simulate" call or a
    real gateway redirect (see test_end_to_end.py's paid-plan test for the
    contrasting PENDING_PAYMENT/INITIATED behavior that non-zero-price
    plans still correctly go through)."""
    resp = client.post(
        "/api/v1/public/plans/free_trial/subscribe",
        json={"email": "trialnogateway@example.com", "mobile": "9800000012", "registration_data": {}},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["subscription"]["status"] == "ACTIVE"
    assert body["payment"]["status"] == "SUCCESS"
    assert body["payment"]["checkout"] is None

    subscription_id = body["subscription"]["subscription_id"]
    invoice = seeded_db.query(Invoice).filter(Invoice.subscription.has(subscription_id=subscription_id)).first()
    assert invoice is not None


# --- One trial per customer, for their full account lifetime ---


def test_one_trial_per_customer_lifetime_even_after_cancellation(client, seeded_db):
    email, mobile = "trialonce@example.com", "9800000003"
    subscription_id = _subscribe_and_activate_trial(client, email, mobile)

    token = _customer_token(client, email, mobile)
    headers = {"Authorization": f"Bearer {token}"}
    cancel = client.post(f"/api/v1/customer/subscriptions/{subscription_id}/cancel", json={}, headers=headers)
    assert cancel.status_code == 200, cancel.text

    # No ACTIVE subscription remains (it's CANCELLED), so this would
    # otherwise fall through to a fresh create_pending_subscription() call
    # (the ordinary repurchase path) - the trial-lifetime check must still
    # catch it regardless.
    second = client.post(
        "/api/v1/public/plans/free_trial/subscribe",
        json={"registration_data": {}},
        headers=headers,
    )
    assert second.status_code == 409, second.text
    assert second.json()["error_code"] == "TRIAL_ALREADY_USED"


def test_trial_lifetime_check_is_scoped_per_customer(client, seeded_db):
    """Sanity check that the check is scoped to (customer, application), not
    global - a different customer must still be able to take the trial."""
    _subscribe_and_activate_trial(client, "trialfirst@example.com", "9800000004")

    resp = client.post(
        "/api/v1/public/plans/free_trial/subscribe",
        json={"email": "trialsecondcustomer@example.com", "mobile": "9800000005", "registration_data": {}},
    )
    assert resp.status_code == 200, resp.text


# --- A trial can never be reached as an upgrade/downgrade target ---


def test_cannot_switch_to_trial_via_downgrade_endpoint(client, seeded_db):
    subscription_id = _new_active_subscription(client, "basic", "notrial1@example.com", "9800000006")
    token = _customer_token(client, "notrial1@example.com", "9800000006")
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        f"/api/v1/customer/subscriptions/{subscription_id}/downgrade",
        json={"target_plan_code": "free_trial"},
        headers=headers,
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "INVALID_PLAN_TRANSITION"


def test_cannot_switch_to_trial_via_public_subscribe_auto_routing(client, seeded_db):
    _new_active_subscription(client, "basic", "notrial2@example.com", "9800000007")
    token = _customer_token(client, "notrial2@example.com", "9800000007")
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(
        "/api/v1/public/plans/free_trial/subscribe",
        json={"registration_data": {}},
        headers=headers,
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "INVALID_PLAN_TRANSITION"


# --- A trial subscription cannot be renewed - it simply expires ---


def test_cannot_renew_trial_subscription(client, seeded_db):
    subscription_id = _subscribe_and_activate_trial(client, "norenew@example.com", "9800000008")
    token = _customer_token(client, "norenew@example.com", "9800000008")
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.post(f"/api/v1/customer/subscriptions/{subscription_id}/renew", headers=headers)
    assert resp.status_code == 403, resp.text
    assert resp.json()["error_code"] == "ACTION_NOT_ALLOWED"


# --- Trial expiry: existing sweep + webhook, zero new code needed there ---


def test_trial_expiry_sweep_expires_and_queues_webhook(client, seeded_db):
    subscription_id = _subscribe_and_activate_trial(client, "trialexpire@example.com", "9800000009")

    # queue_event() queues nothing at all if there's no configured webhook
    # destination (see app.webhooks.service._resolve_destination) - the
    # seeded EVERYTICKET application has none by default, matching how
    # test_provisioning.py sets this up for its own webhook assertions.
    application = seeded_db.query(Application).filter(Application.code == "EVERYTICKET").first()
    application.webhook_url = "http://everyticket.example.com/hooks"
    seeded_db.add(application)

    subscription = seeded_db.query(Subscription).filter(Subscription.subscription_id == subscription_id).first()
    subscription.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    seeded_db.add(subscription)
    seeded_db.commit()

    expired_count = subscription_service.expire_due_subscriptions(seeded_db)
    assert expired_count == 1

    seeded_db.refresh(subscription)
    assert subscription.status == "EXPIRED"

    event = (
        seeded_db.query(WebhookEvent)
        .filter(WebhookEvent.event_type == "subscription.expired", WebhookEvent.entity_id == subscription_id)
        .first()
    )
    assert event is not None
    # Trimmed to just subscription_id (2026-09 follow-up 3) - plan_code
    # is no longer part of the expiry payload.
    assert event.payload["subscription_id"] == subscription_id


# --- Trial-ending reminder email, item 1: "before trial over - email to renew" ---


def test_trial_ending_reminder_uses_trial_template_not_renewal_reminder(client, seeded_db, fake_smtp_success):
    # SMTP is faked (no real network) the same way test_email_service.py's
    # own send_renewal_reminders test does - without this, send_templated_
    # email() attempts a real SMTP connection, gets refused in this test
    # environment, and send_renewal_reminders() silently counts it as not
    # sent (sent_count stays 0) even though the NotificationLog row is
    # still written as FAILED.
    subscription_id = _subscribe_and_activate_trial(client, "trialreminder@example.com", "9800000010")

    settings = get_settings()
    subscription = seeded_db.query(Subscription).filter(Subscription.subscription_id == subscription_id).first()
    subscription.expires_at = datetime.now(timezone.utc) + timedelta(days=max(settings.RENEWAL_REMINDER_DAYS_BEFORE - 1, 0))
    seeded_db.add(subscription)
    seeded_db.commit()

    # fake_smtp_success also collects the payment_success/invoice_generated
    # emails the subscribe+activate step above already sent, so the
    # meaningful assertion is send_renewal_reminders()'s own return value
    # and the NotificationLog row it wrote - not a raw count of everything
    # this whole test happened to send.
    sent_before = len(fake_smtp_success)
    sent_count = subscription_service.send_renewal_reminders(seeded_db)
    assert sent_count == 1
    assert len(fake_smtp_success) == sent_before + 1

    log = seeded_db.query(NotificationLog).filter(
        NotificationLog.related_entity_id == subscription_id, NotificationLog.template_code == "trial_ending"
    ).first()
    assert log is not None

    # Calling the sweep again immediately must not double-send.
    assert subscription_service.send_renewal_reminders(seeded_db) == 0
    assert len(fake_smtp_success) == sent_before + 1


# --- Race-condition safety (item 4): IntegrityError -> clean TrialAlreadyUsed ---


def test_trial_race_condition_integrity_error_becomes_clean_conflict(seeded_db):
    """Simulates two concurrent trial-signup requests racing past the
    application-level pre-check at the same time - the DB-level partial
    unique index (Postgres-only, not present in this SQLite test database)
    is what would actually catch the second insert in production. Here,
    db.flush() is mocked to raise the IntegrityError that constraint would
    produce, to verify create_pending_subscription() translates it into a
    clean TrialAlreadyUsed (409) - not a raw 500 - and leaves no dangling
    subscription row or broken session behind."""
    application = seeded_db.query(Application).filter(Application.code == "EVERYTICKET").first()
    plan = (
        seeded_db.query(Plan)
        .filter(Plan.application_id == application.id, Plan.plan_code == "FREE_TRIAL")
        .first()
    )
    customer = customer_service.create_customer(seeded_db, email="race@example.com", mobile="9800000011")
    seeded_db.commit()

    with patch.object(seeded_db, "flush", side_effect=IntegrityError("INSERT", {}, Exception("unique violation"))):
        with pytest.raises(TrialAlreadyUsed):
            subscription_service.create_pending_subscription(
                seeded_db, customer=customer, application=application, plan=plan
            )

    # No half-created subscription was left behind, and the session is
    # still usable for a normal query afterwards (flush is un-mocked again
    # once the `with patch.object(...)` block above exits).
    assert (
        seeded_db.query(Subscription)
        .filter(Subscription.customer_id == customer.id, Subscription.plan_id == plan.id)
        .count()
        == 0
    )
