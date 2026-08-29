"""
Invoice GST/tax config, PDF generation, download, and email delivery
(spec section 45 - the last item of the pre-existing "explicitly not
implemented yet" list: tax_amount was always 0, no PDF/email).

Covers: generate_invoice() tax math and customer-GSTIN lookup at the
service layer, the get_or_render_pdf() disk cache, the admin tax-config
GET/PUT endpoints (+ permission gates), admin/customer PDF downloads
(+ ownership check on the customer side), and the admin invoice-email
resend endpoint (via a faked SMTP, same pattern as test_email_service.py).
"""
import os

from app.applications.models import Application
from app.customers import service as customer_service
from app.customers.models import CustomerRegistrationData
from app.invoices import service as invoice_service
from app.invoices.schemas import TaxConfigUpdate
from app.invoices.tax import get_tax_config, set_tax_config
from app.notifications.email.providers.smtp import provider as smtp_provider
from app.payments import service as payment_service
from app.plans.models import Plan
from app.subscriptions import service as subscription_service

from tests.test_admin_api import _admin_headers


def _basic_plan(db):
    application = db.query(Application).filter(Application.code == "EVERYTICKET").first()
    return application, db.query(Plan).filter(Plan.plan_code == "BASIC", Plan.application_id == application.id).one()


def _paid_subscription(db, *, email: str, mobile: str):
    """Drives a customer all the way to an ACTIVE subscription with a
    SUCCESS payment - i.e. exactly what generate_invoice() needs -
    without going through the HTTP layer, so tests can inspect the
    resulting Invoice/PaymentTransaction rows directly."""
    application, plan = _basic_plan(db)
    customer = customer_service.create_customer(db, email=email, mobile=mobile)
    subscription = subscription_service.create_pending_subscription(
        db, customer=customer, application=application, plan=plan
    )
    payment = payment_service.create_payment_transaction(
        db, customer=customer, subscription=subscription, plan=plan, payment_type="NEW", gateway_code="mock"
    )
    db.commit()
    transaction, invoice = payment_service.simulate_mock_callback(
        db, transaction_id=payment.transaction_id, scenario="SUCCESS"
    )
    return customer, subscription, transaction, invoice


def test_generate_invoice_defaults_to_zero_tax_when_unconfigured(seeded_db):
    _customer, _sub, _txn, invoice = _paid_subscription(seeded_db, email="notax@example.com", mobile="9822200001")
    assert float(invoice.tax_amount) == 0.0
    assert float(invoice.total_amount) == float(invoice.amount)
    assert invoice.gst_number is None


def test_generate_invoice_applies_configured_tax_rate(seeded_db):
    set_tax_config(
        seeded_db, update=TaxConfigUpdate(gst_rate_percent=18, seller_gstin="27AAAAA0000A1Z5", tax_label="GST")
    )

    _customer, _sub, _txn, invoice = _paid_subscription(seeded_db, email="withtax@example.com", mobile="9822200002")

    expected_tax = round(float(invoice.amount) * 0.18, 2)
    assert float(invoice.tax_amount) == expected_tax
    assert float(invoice.total_amount) == round(float(invoice.amount) + expected_tax, 2)


def test_generate_invoice_picks_up_customer_gstin_from_registration_data(seeded_db):
    application, plan = _basic_plan(seeded_db)
    customer = customer_service.create_customer(seeded_db, email="gstincust@example.com", mobile="9822200003")
    seeded_db.add(
        CustomerRegistrationData(
            customer_id=customer.id, application_id=application.id, data={"gstin": "29BBBBB1111B1Z1"}
        )
    )
    seeded_db.commit()

    subscription = subscription_service.create_pending_subscription(
        seeded_db, customer=customer, application=application, plan=plan
    )
    payment = payment_service.create_payment_transaction(
        seeded_db, customer=customer, subscription=subscription, plan=plan, payment_type="NEW", gateway_code="mock"
    )
    seeded_db.commit()
    _txn, invoice = payment_service.simulate_mock_callback(
        seeded_db, transaction_id=payment.transaction_id, scenario="SUCCESS"
    )

    assert invoice.gst_number == "29BBBBB1111B1Z1"


def test_get_or_render_pdf_caches_to_disk(seeded_db, monkeypatch):
    _customer, _sub, _txn, invoice = _paid_subscription(seeded_db, email="pdfcache@example.com", mobile="9822200004")

    # The automatic post-payment invoice email (payments/service.py) already
    # rendered + cached a PDF for this invoice as a side effect of the
    # payment succeeding - confirm that, then verify get_or_render_pdf()
    # serves the cached file rather than re-rendering, and correctly
    # re-renders if the cached file goes missing from disk.
    assert invoice.pdf_path is not None
    cached_path = invoice.pdf_path

    render_calls = []
    real_build = invoice_service.build_invoice_pdf

    def _counting_build(*args, **kwargs):
        render_calls.append(1)
        return real_build(*args, **kwargs)

    monkeypatch.setattr(invoice_service, "build_invoice_pdf", _counting_build)

    first = invoice_service.get_or_render_pdf(seeded_db, invoice)
    assert first.startswith(b"%PDF")
    assert len(render_calls) == 0  # served from the disk cache, not re-rendered

    os.remove(cached_path)
    second = invoice_service.get_or_render_pdf(seeded_db, invoice)
    assert second.startswith(b"%PDF")
    assert len(render_calls) == 1  # cache file gone -> re-rendered exactly once
    assert os.path.exists(invoice.pdf_path)


def test_admin_tax_config_get_defaults_and_round_trips(client, seeded_db):
    headers = _admin_headers(client)

    default = client.get("/api/v1/admin/invoices/tax-config", headers=headers)
    assert default.status_code == 200, default.text
    assert default.json()["gst_rate_percent"] == 0
    assert default.json()["seller_gstin"] is None

    updated = client.put(
        "/api/v1/admin/invoices/tax-config",
        json={"gst_rate_percent": 12, "seller_gstin": "27CCCCC2222C1Z9", "tax_label": "GST"},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["gst_rate_percent"] == 12
    assert updated.json()["seller_gstin"] == "27CCCCC2222C1Z9"

    refetched = client.get("/api/v1/admin/invoices/tax-config", headers=headers)
    assert refetched.json()["gst_rate_percent"] == 12


def test_admin_tax_config_requires_permission(client, seeded_db, db_session):
    from app.auth import service as auth_service

    auth_service.create_admin_user(
        db_session, email="notaxperm@example.com", full_name="No Perm", password="LimitedPass123!", mfa_enabled=False
    )
    db_session.commit()
    login = client.post("/api/v1/admin/auth/login", json={"email": "notaxperm@example.com", "password": "LimitedPass123!"})
    limited_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = client.get("/api/v1/admin/invoices/tax-config", headers=limited_headers)
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "FORBIDDEN"

    resp2 = client.put(
        "/api/v1/admin/invoices/tax-config", json={"gst_rate_percent": 5}, headers=limited_headers
    )
    assert resp2.status_code == 403


def test_admin_and_customer_invoice_pdf_download(client, seeded_db):
    resp = client.post(
        "/api/v1/public/plans/basic/subscribe",
        json={"email": "pdfdownload@example.com", "mobile": "9822200005", "registration_data": {}},
    )
    assert resp.status_code == 200, resp.text
    transaction_id = resp.json()["payment"]["transaction_id"]
    client.post("/api/v1/payment/mock/callback", json={"transaction_id": transaction_id, "scenario": "SUCCESS"})

    admin_headers = _admin_headers(client)
    inv_list = client.get("/api/v1/admin/invoices", params={"customer_id": resp.json()["customer"]["customer_id"]}, headers=admin_headers)
    invoice_id = inv_list.json()["items"][0]["invoice_id"]

    admin_pdf = client.get(f"/api/v1/admin/invoices/{invoice_id}/pdf", headers=admin_headers)
    assert admin_pdf.status_code == 200, admin_pdf.text
    assert admin_pdf.headers["content-type"] == "application/pdf"
    assert admin_pdf.content.startswith(b"%PDF")

    # Customer download: verify + get a customer session token, then
    # confirm they can fetch their own invoice's PDF.
    identify = client.post(
        "/api/v1/public/identify", json={"email": "pdfdownload@example.com", "mobile": "9822200005"}
    )
    otp_session_id = identify.json()["otp_session_id"]
    debug_code = identify.json()["debug_otp_code"]
    verify = client.post(
        "/api/v1/public/otp/verify", json={"otp_session_id": otp_session_id, "code": debug_code}
    )
    customer_token = verify.json()["access_token"]
    customer_headers = {"Authorization": f"Bearer {customer_token}"}

    customer_pdf = client.get(f"/api/v1/customer/invoices/{invoice_id}/pdf", headers=customer_headers)
    assert customer_pdf.status_code == 200, customer_pdf.text
    assert customer_pdf.content.startswith(b"%PDF")


def test_customer_cannot_download_another_customers_invoice_pdf(client, seeded_db):
    owner = client.post(
        "/api/v1/public/plans/basic/subscribe",
        json={"email": "owner@example.com", "mobile": "9822200006", "registration_data": {}},
    )
    transaction_id = owner.json()["payment"]["transaction_id"]
    client.post("/api/v1/payment/mock/callback", json={"transaction_id": transaction_id, "scenario": "SUCCESS"})

    admin_headers = _admin_headers(client)
    inv_list = client.get(
        "/api/v1/admin/invoices", params={"customer_id": owner.json()["customer"]["customer_id"]}, headers=admin_headers
    )
    invoice_id = inv_list.json()["items"][0]["invoice_id"]

    client.post(
        "/api/v1/public/plans/basic/subscribe",
        json={"email": "intruder@example.com", "mobile": "9822200007", "registration_data": {}},
    )
    identify = client.post("/api/v1/public/identify", json={"email": "intruder@example.com", "mobile": "9822200007"})
    otp_session_id = identify.json()["otp_session_id"]
    debug_code = identify.json()["debug_otp_code"]
    verify = client.post("/api/v1/public/otp/verify", json={"otp_session_id": otp_session_id, "code": debug_code})
    intruder_headers = {"Authorization": f"Bearer {verify.json()['access_token']}"}

    resp = client.get(f"/api/v1/customer/invoices/{invoice_id}/pdf", headers=intruder_headers)
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "INVOICE_NOT_FOUND"


def test_admin_send_invoice_email(client, seeded_db, monkeypatch):
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
            sent.append(message)

    monkeypatch.setattr(smtp_provider.smtplib, "SMTP", _FakeSMTP)

    resp = client.post(
        "/api/v1/public/plans/basic/subscribe",
        json={"email": "resend@example.com", "mobile": "9822200008", "registration_data": {}},
    )
    transaction_id = resp.json()["payment"]["transaction_id"]
    client.post("/api/v1/payment/mock/callback", json={"transaction_id": transaction_id, "scenario": "SUCCESS"})
    sent.clear()  # the automatic post-payment invoice email already fired above - isolate the resend call

    admin_headers = _admin_headers(client)
    inv_list = client.get(
        "/api/v1/admin/invoices", params={"customer_id": resp.json()["customer"]["customer_id"]}, headers=admin_headers
    )
    invoice_id = inv_list.json()["items"][0]["invoice_id"]

    result = client.post(f"/api/v1/admin/invoices/{invoice_id}/send-email", headers=admin_headers)
    assert result.status_code == 200, result.text
    assert result.json()["sent"] is True
    assert result.json()["to"] == "resend@example.com"
    assert len(sent) == 1
    assert "invoice.pdf" in sent[0] or f"{invoice_id}.pdf" in sent[0]
