"""
Admin Testing / Developer Tools module (spec sections 54, 55).

"Mandatory" per the spec, and must allow complete testing without
repeatedly performing real payments/emails/webhooks. Every endpoint here
is gated by BOTH require_test_mode() (spec section 55: backend-enforced,
never available in production - TEST_MODE itself is force-reset to False
outside development/staging by Settings.enforce_test_mode_restrictions,
so this can never open up in a real deployment even via a stray env var)
and require_permission("TESTING_TOOLS_USE"), and every mutating action
writes an audit-log entry (spec section 56 explicitly lists "Test payment
simulated" as an audit example).

Each tool deliberately reuses the SAME internal service functions a real
request would use, rather than re-implementing a parallel "test" code
path:
  - TEST PAYMENT calls payment_service.simulate_mock_callback() - the
    exact function a real MockPaymentGateway callback drives.
  - TEST SUBSCRIPTION EVENTS calls the same subscription_service
    functions the real payment/portal flows call.
  - TEST EVERYTICKET WEBHOOK / WEBHOOK FAILURE SIMULATOR reuse
    app.webhooks.service's signing (_sign) and single-delivery-attempt
    (_attempt_one, via the public attempt_delivery_with_client wrapper)
    logic - only the HTTP transport is swapped out.
  - TEST EMAIL calls notifications.email.service.send_templated_email()
    directly.
  - TEST SSO reuses increment 9's POST /admin/customers/{id}/sso-link -
    no separate endpoint needed here, see AdminTestingPage's own "SSO"
    section on the frontend, which just links to that existing action.

TEST DATA GENERATOR marks everything it creates with a "TEST-" plan_code
prefix and a "@test.invalid" customer email domain (spec section 54: "Mark
test records clearly as TEST") so CLEANUP can find and remove exactly
those rows, in FK-safe child-to-parent order, without ever touching a
real customer/plan/subscription.
"""
import secrets
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_application, get_db
from app.api.v1.admin_serializers import to_payment_admin_out, to_subscription_admin_out
from app.applications.models import Application, CustomerApplicationMapping
from app.audit import service as audit_service
from app.auth.deps import require_permission, require_test_mode
from app.auth.models import AdminUser
from app.core.config import get_settings
from app.core.enums import PaymentType, SubscriptionEventType
from app.core.exceptions import CustomerNotFound, PlanNotFound, SubscriptionNotFound
from app.customers import service as customer_service
from app.customers.models import Customer
from app.invoices.models import Invoice, InvoiceItem
from app.notifications.email import service as email_service
from app.notifications.models import NotificationLog
from app.payments import service as payment_service
from app.payments.models import PaymentTransaction
from app.payments.schemas import PaymentAdminOut
from app.plans.models import Plan
from app.subscriptions import service as subscription_service
from app.subscriptions.models import Subscription, SubscriptionHistory
from app.subscriptions.schemas import SubscriptionAdminOut
from app.webhooks import service as webhook_service
from app.webhooks.models import WebhookDelivery, WebhookEvent
from app.webhooks.schemas import WebhookDeliveryOut

router = APIRouter(prefix="/testing", tags=["admin-testing"])

_TEST_EMAIL_DOMAIN = "test.invalid"
_TEST_PLAN_PREFIX = "TEST-"

# Sample context values matching each seeded template's Jinja2 variables
# (app/core/seed.py) - just enough to render something recognizable when
# an admin test-sends it; not meant to reflect real data.
_SAMPLE_EMAIL_CONTEXT: dict[str, dict] = {
    "otp_verification": {"code": "123456"},
    "payment_success": {"plan_name": "Professional", "currency": "INR", "amount": "5000.00", "transaction_id": "TXN-TESTSEND01"},
    "payment_failed": {"plan_name": "Professional", "currency": "INR", "amount": "5000.00", "failure_reason": "Simulated failure (test send)"},
    "subscription_cancelled": {"plan_name": "Professional"},
    "renewal_reminder": {"plan_name": "Professional", "expires_at": "2026-12-31"},
}


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _short_suffix() -> str:
    return secrets.token_hex(4).upper()


# --- TEST PAYMENT ---------------------------------------------------------


class TestPaymentRequest(BaseModel):
    customer_id: str
    plan_code: str
    scenario: str  # SUCCESS | FAILED | PENDING | TIMEOUT | DUPLICATE_CALLBACK


class TestPaymentResult(BaseModel):
    payment: PaymentAdminOut
    subscription: SubscriptionAdminOut
    invoice_id: str | None
    note: str


@router.post("/payment", response_model=TestPaymentResult)
def test_payment(
    body: TestPaymentRequest,
    request: Request,
    db: Session = Depends(get_db),
    application: Application = Depends(get_application),
    admin: AdminUser = Depends(require_permission("TESTING_TOOLS_USE")),
    _test_mode: None = Depends(require_test_mode),
):
    """Spec section 54 TEST PAYMENT. Always simulated via MockPaymentGateway
    (per the spec's own wording), regardless of the application's
    configured production gateway - PayU's real hosted-checkout flow can't
    be driven headlessly from an admin click, but every downstream effect
    (subscription activation, invoice, webhook, email) goes through the
    exact same process_gateway_result() path a real callback uses."""
    customer = db.query(Customer).filter(Customer.customer_id == body.customer_id).first()
    if customer is None:
        raise CustomerNotFound(f"Unknown customer {body.customer_id}")

    plan = (
        db.query(Plan)
        .filter(Plan.application_id == application.id, Plan.plan_code == body.plan_code.upper(), Plan.active.is_(True))
        .first()
    )
    if plan is None:
        raise PlanNotFound(f"No active plan '{body.plan_code}'")

    scenario = body.scenario.upper()
    if scenario not in {"SUCCESS", "FAILED", "PENDING", "TIMEOUT", "DUPLICATE_CALLBACK"}:
        raise HTTPException(status_code=422, detail="scenario must be one of SUCCESS, FAILED, PENDING, TIMEOUT, DUPLICATE_CALLBACK")

    subscription = subscription_service.create_pending_subscription(db, customer=customer, application=application, plan=plan)
    payment = payment_service.create_payment_transaction(
        db, customer=customer, subscription=subscription, plan=plan, payment_type=PaymentType.NEW.value, gateway_code="mock"
    )
    db.commit()

    effective_scenario = "SUCCESS" if scenario == "DUPLICATE_CALLBACK" else scenario
    transaction, invoice = payment_service.simulate_mock_callback(db, transaction_id=payment.transaction_id, scenario=effective_scenario)
    note = f"Simulated {scenario} via MockPaymentGateway."
    if scenario == "DUPLICATE_CALLBACK":
        # Second callback with the same terminal result - process_gateway_result()'s
        # terminal-status guard (spec section 28) must no-op rather than
        # double-activate/double-invoice.
        transaction, invoice = payment_service.simulate_mock_callback(db, transaction_id=payment.transaction_id, scenario="SUCCESS")
        note = "Simulated SUCCESS twice (DUPLICATE_CALLBACK) - second callback was a safe no-op."

    audit_service.record(
        db,
        actor=admin.email,
        action="TEST_PAYMENT_SIMULATED",
        entity_type="payment_transaction",
        entity_id=transaction.transaction_id,
        new_value={"scenario": scenario, "customer_id": customer.customer_id, "plan_code": plan.plan_code},
        ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(transaction)
    db.refresh(subscription)

    return TestPaymentResult(
        payment=to_payment_admin_out(transaction),
        subscription=to_subscription_admin_out(subscription),
        invoice_id=invoice.invoice_id if invoice else None,
        note=note,
    )


# --- TEST SUBSCRIPTION EVENTS ---------------------------------------------


class TestSubscriptionEventRequest(BaseModel):
    subscription_id: str
    event: str  # ACTIVATE | RENEW | UPGRADE | DOWNGRADE | CANCEL | EXPIRE | PAYMENT_FAILED
    target_plan_code: str | None = None  # required for UPGRADE / DOWNGRADE


_EVENT_TYPES = {"ACTIVATE", "RENEW", "UPGRADE", "DOWNGRADE", "CANCEL", "EXPIRE", "PAYMENT_FAILED"}


@router.post("/subscription-event", response_model=SubscriptionAdminOut)
def test_subscription_event(
    body: TestSubscriptionEventRequest,
    request: Request,
    db: Session = Depends(get_db),
    application: Application = Depends(get_application),
    admin: AdminUser = Depends(require_permission("TESTING_TOOLS_USE")),
    _test_mode: None = Depends(require_test_mode),
):
    """Spec section 54 TEST SUBSCRIPTION EVENTS - drives the same
    subscription_service functions a real payment callback or Celery beat
    sweep would call, without needing a real payment or the expiry
    scheduler to actually run."""
    event = body.event.upper()
    if event not in _EVENT_TYPES:
        raise HTTPException(status_code=422, detail=f"event must be one of {sorted(_EVENT_TYPES)}")

    subscription = (
        db.query(Subscription)
        .filter(Subscription.subscription_id == body.subscription_id, Subscription.application_id == application.id)
        .first()
    )
    if subscription is None:
        raise SubscriptionNotFound(f"Unknown subscription {body.subscription_id}")

    if event in {"UPGRADE", "DOWNGRADE"}:
        if not body.target_plan_code:
            raise HTTPException(status_code=422, detail=f"target_plan_code is required for {event}")
        target_plan = (
            db.query(Plan)
            .filter(Plan.application_id == application.id, Plan.plan_code == body.target_plan_code.upper())
            .first()
        )
        if target_plan is None:
            raise PlanNotFound(f"No plan '{body.target_plan_code}'")
        event_type = SubscriptionEventType.UPGRADED.value if event == "UPGRADE" else SubscriptionEventType.DOWNGRADED.value
        subscription_service.apply_plan_change(db, subscription=subscription, new_plan=target_plan, event_type=event_type)
    elif event == "ACTIVATE":
        subscription_service.activate_subscription(db, subscription=subscription)
    elif event == "RENEW":
        subscription_service.renew_subscription(db, subscription=subscription)
    elif event == "CANCEL":
        subscription_service.cancel_subscription(
            db, subscription=subscription, cancelled_by=admin.email, reason="Test event via admin Testing module"
        )
    elif event == "EXPIRE":
        subscription_service.expire_subscription(db, subscription=subscription)
    elif event == "PAYMENT_FAILED":
        subscription_service.mark_payment_failed(db, subscription=subscription)

    audit_service.record(
        db,
        actor=admin.email,
        action="TEST_SUBSCRIPTION_EVENT_SENT",
        entity_type="subscription",
        entity_id=subscription.subscription_id,
        new_value={"event": event, "target_plan_code": body.target_plan_code},
        ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(subscription)
    return to_subscription_admin_out(subscription)


# --- TEST EVERYTICKET WEBHOOK ----------------------------------------------


class TestWebhookSendRequest(BaseModel):
    payload: dict
    headers: dict[str, str] | None = None


@router.post("/webhook/send")
def test_webhook_send(
    body: TestWebhookSendRequest,
    request: Request,
    db: Session = Depends(get_db),
    application: Application = Depends(get_application),
    admin: AdminUser = Depends(require_permission("TESTING_TOOLS_USE")),
    _test_mode: None = Depends(require_test_mode),
):
    """Spec section 54 TEST EVERYTICKET WEBHOOK: admin-edited JSON body +
    optional extra headers, signed exactly like a real dispatch and sent
    directly to the application's configured webhook destination. Shows
    the request, response, HTTP status, and elapsed time - never queues a
    WebhookEvent/WebhookDelivery row, since this is a live diagnostic
    send, not a real business event."""
    result = webhook_service.send_ad_hoc_webhook(application=application, payload=body.payload, extra_headers=body.headers)
    audit_service.record(
        db,
        actor=admin.email,
        action="TEST_WEBHOOK_SENT",
        entity_type="application",
        entity_id=application.code,
        new_value={"sent": result.get("sent"), "http_status": result.get("http_status")},
        ip_address=_client_ip(request),
    )
    db.commit()
    return result


# --- WEBHOOK FAILURE SIMULATOR ---------------------------------------------


class TestWebhookFailureRequest(BaseModel):
    status_code: str  # "400" | "401" | "404" | "500" | "timeout"


_SIMULATABLE_FAILURES = {"400", "401", "404", "500", "timeout"}


@router.post("/webhook/simulate-failure", response_model=WebhookDeliveryOut)
def test_webhook_failure(
    body: TestWebhookFailureRequest,
    request: Request,
    db: Session = Depends(get_db),
    application: Application = Depends(get_application),
    admin: AdminUser = Depends(require_permission("TESTING_TOOLS_USE")),
    _test_mode: None = Depends(require_test_mode),
):
    """Spec section 54 WEBHOOK FAILURE SIMULATOR: queues one real
    WebhookEvent/WebhookDelivery row (so the normal retry-schedule
    bookkeeping applies), then attempts JUST that delivery through an
    httpx.MockTransport that always returns the requested status (or
    raises a timeout) - reusing the exact retry/EXHAUSTED logic
    dispatch_pending() itself uses, so the returned delivery's
    attempt_count/status/next_retry_at genuinely reflect that logic
    rather than a hand-simulated approximation. Never touches any other
    pending delivery (see attempt_delivery_with_client's docstring)."""
    status_code = body.status_code.lower()
    if status_code not in _SIMULATABLE_FAILURES:
        raise HTTPException(status_code=422, detail=f"status_code must be one of {sorted(_SIMULATABLE_FAILURES)}")

    event = webhook_service.queue_event(
        db,
        application=application,
        event_type="test.webhook_failure_simulation",
        entity_type="test",
        entity_id=f"TEST-SIM-{_short_suffix()}",
        payload={"simulated_failure": status_code},
    )
    if event is None:
        raise HTTPException(
            status_code=422,
            detail="No webhook destination configured for this application (set webhook_url or EVERYTICKET_WEBHOOK_URL first)",
        )
    db.commit()

    delivery = db.query(WebhookDelivery).filter(WebhookDelivery.webhook_event_id == event.id).first()

    def _handler(httpx_request: httpx.Request) -> httpx.Response:
        if status_code == "timeout":
            raise httpx.TimeoutException("Simulated timeout (admin Testing module)", request=httpx_request)
        return httpx.Response(int(status_code), json={"simulated": True, "requested_status": status_code})

    with httpx.Client(transport=httpx.MockTransport(_handler)) as fake_client:
        webhook_service.attempt_delivery_with_client(db, delivery, http_client=fake_client)

    audit_service.record(
        db,
        actor=admin.email,
        action="TEST_WEBHOOK_FAILURE_SIMULATED",
        entity_type="webhook_delivery",
        entity_id=str(delivery.id),
        new_value={"requested_status": status_code, "resulting_status": delivery.status, "attempt_count": delivery.attempt_count},
        ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(delivery)
    return delivery


# --- TEST EMAIL -------------------------------------------------------------


class TestEmailRequest(BaseModel):
    template_code: str
    to: str


class TestEmailResult(BaseModel):
    sent: bool
    status: str | None
    provider_response: str | None


@router.post("/email", response_model=TestEmailResult)
def test_email(
    body: TestEmailRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_permission("TESTING_TOOLS_USE")),
    _test_mode: None = Depends(require_test_mode),
):
    """Spec section 54 TEST EMAIL: renders and sends the chosen template
    with representative sample values via the exact same
    send_templated_email() every real trigger point uses, then reports
    back the NotificationLog row it just wrote (spec: "Show delivery
    result")."""
    context = _SAMPLE_EMAIL_CONTEXT.get(body.template_code, {})
    sent = email_service.send_templated_email(
        db,
        template_code=body.template_code,
        to=body.to,
        context=context,
        related_entity_type="test_email",
        related_entity_id=f"TEST-EMAIL-{_short_suffix()}",
    )
    log = (
        db.query(NotificationLog)
        .filter(NotificationLog.template_code == body.template_code, NotificationLog.recipient == body.to)
        .order_by(NotificationLog.id.desc())
        .first()
    )
    audit_service.record(
        db,
        actor=admin.email,
        action="TEST_EMAIL_SENT",
        entity_type="notification_template",
        entity_id=body.template_code,
        new_value={"to": body.to, "sent": sent},
        ip_address=_client_ip(request),
    )
    db.commit()
    return TestEmailResult(sent=sent, status=log.status if log else None, provider_response=log.provider_response if log else None)


# --- OTP / MFA BYPASS (spec sections 11, 12, 54, 55) ------------------------


class TestModeStatusOut(BaseModel):
    environment: str
    test_mode: bool
    allow_otp_bypass: bool
    allow_admin_mfa_bypass: bool


class OtpMfaBypassRequest(BaseModel):
    allow_otp_bypass: bool | None = None
    allow_admin_mfa_bypass: bool | None = None


@router.get("/status", response_model=TestModeStatusOut)
def get_test_mode_status(
    admin: AdminUser = Depends(require_permission("TESTING_TOOLS_USE")),
    _test_mode: None = Depends(require_test_mode),
):
    settings = get_settings()
    return TestModeStatusOut(
        environment=settings.ENVIRONMENT,
        test_mode=settings.TEST_MODE,
        allow_otp_bypass=settings.ALLOW_OTP_BYPASS,
        allow_admin_mfa_bypass=settings.ALLOW_ADMIN_MFA_BYPASS,
    )


@router.post("/otp-mfa-bypass", response_model=TestModeStatusOut)
def set_otp_mfa_bypass(
    body: OtpMfaBypassRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_permission("TESTING_TOOLS_USE")),
    _test_mode: None = Depends(require_test_mode),
):
    """Spec section 54 OTP/MFA BYPASS controls. Mutates the running
    process's cached Settings singleton in-memory only (never persisted,
    never written back to .env) - it resets to whatever .env actually
    says on the next restart. Reachable at all only because
    require_test_mode already guarantees settings.is_production is False
    (enforce_test_mode_restrictions force-resets TEST_MODE in production
    regardless of any env misconfiguration) - the explicit check below is
    deliberate defense-in-depth on top of that, not a substitute for it,
    per spec section 55's "never rely only on hiding frontend routes."
    Every change is audit-logged (spec section 56 lists "OTP bypassed" /
    "MFA bypassed" as audit examples)."""
    settings = get_settings()
    if settings.is_production:
        raise HTTPException(status_code=403, detail="OTP/MFA bypass controls are never available in production")

    old_value = {"allow_otp_bypass": settings.ALLOW_OTP_BYPASS, "allow_admin_mfa_bypass": settings.ALLOW_ADMIN_MFA_BYPASS}
    if body.allow_otp_bypass is not None:
        settings.ALLOW_OTP_BYPASS = body.allow_otp_bypass
    if body.allow_admin_mfa_bypass is not None:
        settings.ALLOW_ADMIN_MFA_BYPASS = body.allow_admin_mfa_bypass

    audit_service.record(
        db,
        actor=admin.email,
        action="TEST_MODE_BYPASS_FLAGS_CHANGED",
        entity_type="settings",
        entity_id="runtime",
        old_value=old_value,
        new_value={"allow_otp_bypass": settings.ALLOW_OTP_BYPASS, "allow_admin_mfa_bypass": settings.ALLOW_ADMIN_MFA_BYPASS},
        ip_address=_client_ip(request),
    )
    db.commit()
    return TestModeStatusOut(
        environment=settings.ENVIRONMENT,
        test_mode=settings.TEST_MODE,
        allow_otp_bypass=settings.ALLOW_OTP_BYPASS,
        allow_admin_mfa_bypass=settings.ALLOW_ADMIN_MFA_BYPASS,
    )


# --- TEST DATA GENERATOR ----------------------------------------------------


class TestDataGeneratedOut(BaseModel):
    customer_id: str
    plan_code: str
    subscription_id: str
    transaction_id: str
    invoice_id: str | None
    external_customer_id: str


class TestDataCleanupOut(BaseModel):
    plans_deleted: int
    customers_deleted: int
    subscriptions_deleted: int


@router.post("/data/generate", response_model=TestDataGeneratedOut)
def generate_test_data(
    request: Request,
    db: Session = Depends(get_db),
    application: Application = Depends(get_application),
    admin: AdminUser = Depends(require_permission("TESTING_TOOLS_USE")),
    _test_mode: None = Depends(require_test_mode),
):
    """Spec section 54 TEST DATA GENERATOR: one call creates a full,
    linked chain - test plan, test customer, test subscription (ACTIVE,
    via the same simulate_mock_callback() path TEST PAYMENT above uses,
    so it also generates a real invoice and queues a real webhook event
    if a destination is configured) - plus an Everyticket mapping row.
    Every generated row is clearly marked TEST (plan_code prefixed
    "TEST-", customer email on the "@test.invalid" domain) so /data/cleanup
    below can find exactly these rows and nothing else."""
    suffix = _short_suffix()
    plan = Plan(
        application_id=application.id,
        plan_code=f"{_TEST_PLAN_PREFIX}{suffix}",
        name=f"TEST Plan {suffix}",
        description="Generated by the admin Testing/Developer Tools module - safe to delete via /testing/data/cleanup.",
        price=1.00,
        currency=application.currency,
        billing_interval="month",
        billing_frequency=1,
        active=True,
        display_order=999,
    )
    db.add(plan)
    db.flush()

    customer = customer_service.create_customer(
        db, email=f"test-{suffix.lower()}@{_TEST_EMAIL_DOMAIN}", mobile=f"9{secrets.randbelow(10**9):09d}"
    )
    mapping = CustomerApplicationMapping(
        customer_id=customer.id, application_id=application.id, external_customer_id=f"TEST-EXT-{suffix}"
    )
    db.add(mapping)
    db.flush()

    subscription = subscription_service.create_pending_subscription(db, customer=customer, application=application, plan=plan)
    payment = payment_service.create_payment_transaction(
        db, customer=customer, subscription=subscription, plan=plan, payment_type=PaymentType.NEW.value, gateway_code="mock"
    )
    db.commit()

    transaction, invoice = payment_service.simulate_mock_callback(db, transaction_id=payment.transaction_id, scenario="SUCCESS")

    audit_service.record(
        db,
        actor=admin.email,
        action="TEST_DATA_GENERATED",
        entity_type="customer",
        entity_id=customer.customer_id,
        new_value={"plan_code": plan.plan_code, "subscription_id": subscription.subscription_id},
        ip_address=_client_ip(request),
    )
    db.commit()

    return TestDataGeneratedOut(
        customer_id=customer.customer_id,
        plan_code=plan.plan_code,
        subscription_id=subscription.subscription_id,
        transaction_id=transaction.transaction_id,
        invoice_id=invoice.invoice_id if invoice else None,
        external_customer_id=mapping.external_customer_id,
    )


@router.post("/data/cleanup", response_model=TestDataCleanupOut)
def cleanup_test_data(
    request: Request,
    db: Session = Depends(get_db),
    application: Application = Depends(get_application),
    admin: AdminUser = Depends(require_permission("TESTING_TOOLS_USE")),
    _test_mode: None = Depends(require_test_mode),
):
    """Deletes every row the generator above (or a repeated call to it)
    has created for this application - identified solely by the TEST-
    plan_code prefix / @test.invalid customer domain, never by any other
    heuristic - in FK-safe child-to-parent order. A real customer/plan
    can never match either marker, so this can't touch real data."""
    test_plans = db.query(Plan).filter(Plan.application_id == application.id, Plan.plan_code.like(f"{_TEST_PLAN_PREFIX}%")).all()
    plan_ids = [p.id for p in test_plans]

    test_customers = db.query(Customer).filter(Customer.email.like(f"%@{_TEST_EMAIL_DOMAIN}")).all()
    customer_ids = [c.id for c in test_customers]

    subscriptions = db.query(Subscription).filter(Subscription.plan_id.in_(plan_ids)).all() if plan_ids else []
    sub_ids = [s.id for s in subscriptions]
    sub_public_ids = [s.subscription_id for s in subscriptions]

    if sub_ids:
        invoices = db.query(Invoice).filter(Invoice.subscription_id.in_(sub_ids)).all()
        invoice_ids = [inv.id for inv in invoices]
        if invoice_ids:
            db.query(InvoiceItem).filter(InvoiceItem.invoice_id.in_(invoice_ids)).delete(synchronize_session=False)
            db.query(Invoice).filter(Invoice.id.in_(invoice_ids)).delete(synchronize_session=False)

        events = db.query(WebhookEvent).filter(WebhookEvent.entity_type == "subscription", WebhookEvent.entity_id.in_(sub_public_ids)).all()
        event_ids = [e.id for e in events]
        if event_ids:
            db.query(WebhookDelivery).filter(WebhookDelivery.webhook_event_id.in_(event_ids)).delete(synchronize_session=False)
            db.query(WebhookEvent).filter(WebhookEvent.id.in_(event_ids)).delete(synchronize_session=False)

        db.query(PaymentTransaction).filter(PaymentTransaction.subscription_id.in_(sub_ids)).delete(synchronize_session=False)
        db.query(SubscriptionHistory).filter(SubscriptionHistory.subscription_id.in_(sub_ids)).delete(synchronize_session=False)
        db.query(Subscription).filter(Subscription.id.in_(sub_ids)).delete(synchronize_session=False)

    if customer_ids:
        db.query(CustomerApplicationMapping).filter(CustomerApplicationMapping.customer_id.in_(customer_ids)).delete(synchronize_session=False)
        db.query(Customer).filter(Customer.id.in_(customer_ids)).delete(synchronize_session=False)

    if plan_ids:
        db.query(Plan).filter(Plan.id.in_(plan_ids)).delete(synchronize_session=False)

    audit_service.record(
        db,
        actor=admin.email,
        action="TEST_DATA_CLEANED_UP",
        entity_type="application",
        entity_id=application.code,
        new_value={"plans_deleted": len(plan_ids), "customers_deleted": len(customer_ids), "subscriptions_deleted": len(sub_ids)},
        ip_address=_client_ip(request),
    )
    db.commit()

    return TestDataCleanupOut(plans_deleted=len(plan_ids), customers_deleted=len(customer_ids), subscriptions_deleted=len(sub_ids))
