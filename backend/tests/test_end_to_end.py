"""
End-to-end subscription flow (spec section 72, scoped to what's
implemented so far - see docs/implementation-status.md):

    New customer -> choose Professional -> submit dynamic form ->
    create customer -> create subscription (PENDING_PAYMENT) ->
    mock payment SUCCESS -> subscription ACTIVE -> invoice generated

Plus the idempotency (duplicate callback) and payment-failure guarantees
from spec sections 27-28 and 20.

Everyticket webhook dispatch, SSO, upgrade/downgrade, and cancellation are
NOT exercised here yet - those flows aren't implemented in this pass.
"""
from app.customers.models import Customer
from app.invoices.models import Invoice
from app.payments.models import PaymentTransaction
from app.subscriptions.models import Subscription


def test_new_subscription_mock_payment_success_activates_and_invoices(client, seeded_db):
    resp = client.post(
        "/api/v1/public/plans/professional/subscribe",
        json={
            "email": "admin@museum.example",
            "mobile": "9876543210",
            "registration_data": {
                "museum_name": "CSMVS",
                "contact_person": "Priya Shah",
                "gstin": "27ABCDE1234F1Z5",
                "address": "Mumbai",
            },
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["subscription"]["status"] == "PENDING_PAYMENT"
    assert body["payment"]["status"] == "INITIATED"
    transaction_id = body["payment"]["transaction_id"]
    subscription_id = body["subscription"]["subscription_id"]

    callback = client.post(
        "/api/v1/payment/mock/callback",
        json={"transaction_id": transaction_id, "scenario": "SUCCESS"},
    )
    assert callback.status_code == 200, callback.text
    callback_body = callback.json()
    assert callback_body["payment"]["status"] == "SUCCESS"
    assert callback_body["subscription"]["status"] == "ACTIVE"
    assert callback_body["invoice_id"] is not None

    subscription = seeded_db.query(Subscription).filter(Subscription.subscription_id == subscription_id).one()
    assert subscription.status == "ACTIVE"
    assert subscription.starts_at is not None
    assert subscription.expires_at is not None
    assert len(subscription.history) == 1
    assert subscription.history[0].event_type == "activated"

    customer = seeded_db.query(Customer).filter(Customer.id == subscription.customer_id).one()
    assert customer.customer_id.startswith("CUS-")

    payment = seeded_db.query(PaymentTransaction).filter(PaymentTransaction.transaction_id == transaction_id).one()
    assert payment.status == "SUCCESS"

    invoice = seeded_db.query(Invoice).filter(Invoice.subscription_id == subscription.id).one()
    assert invoice.invoice_id.startswith("INV-")
    assert float(invoice.total_amount) == float(payment.amount)


def test_duplicate_success_callback_is_idempotent(client, seeded_db):
    resp = client.post(
        "/api/v1/public/plans/basic/subscribe",
        json={"email": "dup@museum.example", "mobile": "9000000001", "registration_data": {}},
    )
    transaction_id = resp.json()["payment"]["transaction_id"]

    first = client.post("/api/v1/payment/mock/callback", json={"transaction_id": transaction_id, "scenario": "SUCCESS"})
    second = client.post("/api/v1/payment/mock/callback", json={"transaction_id": transaction_id, "scenario": "SUCCESS"})
    third = client.post("/api/v1/payment/mock/callback", json={"transaction_id": transaction_id, "scenario": "SUCCESS"})

    for r in (first, second, third):
        assert r.status_code == 200
        assert r.json()["subscription"]["status"] == "ACTIVE"

    subscription_id = first.json()["subscription"]["subscription_id"]
    subscription = seeded_db.query(Subscription).filter(Subscription.subscription_id == subscription_id).one()

    # Exactly one activation event and one invoice, no matter how many
    # times the SUCCESS callback was replayed (spec section 28).
    assert len(subscription.history) == 1
    invoices = seeded_db.query(Invoice).filter(Invoice.subscription_id == subscription.id).all()
    assert len(invoices) == 1


def test_failed_payment_marks_subscription_payment_failed_not_active(client, seeded_db):
    resp = client.post(
        "/api/v1/public/plans/basic/subscribe",
        json={"email": "fail@museum.example", "mobile": "9000000002", "registration_data": {}},
    )
    transaction_id = resp.json()["payment"]["transaction_id"]

    callback = client.post("/api/v1/payment/mock/callback", json={"transaction_id": transaction_id, "scenario": "FAILED"})
    assert callback.status_code == 200
    assert callback.json()["subscription"]["status"] == "PAYMENT_FAILED"
    assert callback.json()["invoice_id"] is None


def test_second_subscription_attempt_while_active_is_rejected(client, seeded_db):
    first = client.post(
        "/api/v1/public/plans/basic/subscribe",
        json={"email": "repeat@museum.example", "mobile": "9000000003", "registration_data": {}},
    )
    transaction_id = first.json()["payment"]["transaction_id"]
    client.post("/api/v1/payment/mock/callback", json={"transaction_id": transaction_id, "scenario": "SUCCESS"})

    second = client.post(
        "/api/v1/public/plans/professional/subscribe",
        json={"email": "repeat@museum.example", "mobile": "9000000003", "registration_data": {}},
    )
    assert second.status_code == 409
    assert second.json()["error_code"] == "CUSTOMER_ALREADY_SUBSCRIBED"


def test_health_and_ready_endpoints(client):
    assert client.get("/health").status_code == 200
    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ok"
