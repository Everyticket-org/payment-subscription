"""
Customer portal API (spec sections 38-43, 46, 61: /api/v1/customer/).

Every endpoint here requires a customer bearer token issued by
POST /api/v1/public/otp/verify (see app.auth.deps.get_current_customer_id).
Direct OTP-based access (spec section 48) is that same token; SSO-based
access (spec section 47) is not implemented yet - see
docs/implementation-status.md.
"""
from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.deps import get_application, get_db
from app.applications.models import Application
from app.auth.deps import get_current_customer_id
from app.core.enums import PaymentType, SubscriptionStatus
from app.core.exceptions import (
    ActionNotAllowed,
    AppError,
    CustomerNotFound,
    InvalidPlanTransition,
    PlanNotFound,
    SubscriptionNotFound,
)
from app.customers.models import Customer, CustomerRegistrationData
from app.customers.portal_schemas import CustomerPortalOut
from app.customers.schemas import CustomerOut, RegistrationDataOut
from app.invoices.models import Invoice
from app.invoices.schemas import InvoiceOut
from app.invoices.service import get_or_render_pdf
from app.notifications.email import service as email_service
from app.payments import service as payment_service
from app.payments.models import PaymentTransaction
from app.payments.schemas import PaymentTransactionOut
from app.plans.models import Plan
from app.subscriptions import service as subscription_service
from app.subscriptions.models import Subscription
from app.subscriptions.schemas import CancelRequest, PortalSubscriptionOut, SubscribeResponse, UpgradeDowngradeRequest

router = APIRouter(prefix="/customer", tags=["customer"])


class InvoiceNotFoundError(AppError):
    http_status = 404
    error_code = "INVOICE_NOT_FOUND"


def _to_portal_subscription(sub: Subscription) -> PortalSubscriptionOut:
    return PortalSubscriptionOut(
        subscription_id=sub.subscription_id,
        status=sub.status,
        provisioning_status=sub.provisioning_status,
        starts_at=sub.starts_at,
        expires_at=sub.expires_at,
        plan_code=sub.plan.plan_code,
        plan_name=sub.plan.name,
        price=float(sub.plan.price),
        currency=sub.plan.currency,
        billing_interval=sub.plan.billing_interval,
        billing_frequency=sub.plan.billing_frequency,
        is_trial=sub.is_trial,
    )


def _to_portal_payment(payment: PaymentTransaction) -> PaymentTransactionOut:
    """Same base shape payment_service.build_payment_out() produces, plus
    subscription_ref - see PaymentTransactionOut.subscription_ref's own
    comment for why that field can't just auto-populate from the ORM row."""
    out = PaymentTransactionOut.model_validate(payment)
    out.subscription_ref = payment.subscription.subscription_id
    return out


def _to_portal_invoice(invoice: Invoice) -> InvoiceOut:
    out = InvoiceOut.model_validate(invoice)
    out.subscription_ref = invoice.subscription.subscription_id
    out.transaction_id = invoice.payment_transaction.transaction_id
    return out


def _get_customer(db: Session, customer_id: str) -> Customer:
    customer = db.query(Customer).filter(Customer.customer_id == customer_id).first()
    if customer is None:
        raise CustomerNotFound(f"Unknown customer {customer_id}")
    return customer


def _get_owned_subscription(db: Session, *, customer: Customer, subscription_id: str) -> Subscription:
    subscription = (
        db.query(Subscription)
        .filter(Subscription.subscription_id == subscription_id, Subscription.customer_id == customer.id)
        .first()
    )
    if subscription is None:
        raise SubscriptionNotFound(f"Unknown subscription {subscription_id}")
    return subscription


@router.get("/me", response_model=CustomerPortalOut)
def get_portal(
    db: Session = Depends(get_db),
    customer_id: str = Depends(get_current_customer_id),
    application: Application = Depends(get_application),
):
    """Spec section 46: current plan/status/dates, payment history,
    invoices, subscription history."""
    customer = _get_customer(db, customer_id)

    subscriptions = (
        db.query(Subscription)
        .filter(Subscription.customer_id == customer.id, Subscription.application_id == application.id)
        .order_by(Subscription.created_at.desc())
        .all()
    )
    active = next((s for s in subscriptions if s.status == SubscriptionStatus.ACTIVE.value), None)

    payments = (
        db.query(PaymentTransaction).filter(PaymentTransaction.customer_id == customer.id).order_by(PaymentTransaction.created_at.desc()).all()
    )
    invoices = (
        db.query(Invoice).filter(Invoice.customer_id == customer.id).order_by(Invoice.created_at.desc()).all()
    )
    # Filtered by customer_id only - same as the admin customer-detail
    # endpoint's equivalent query (app/api/v1/admin_customers.py). V1 only
    # ever has one Application row, but there's no reason for this one
    # query to be stricter than the admin one and risk silently hiding a
    # real submission if application_id ever drifted (e.g. a reseed).
    registration_data = (
        db.query(CustomerRegistrationData)
        .filter(CustomerRegistrationData.customer_id == customer.id)
        .order_by(CustomerRegistrationData.created_at.desc())
        .all()
    )

    return CustomerPortalOut(
        customer=CustomerOut.model_validate(customer),
        registration_data=[RegistrationDataOut.model_validate(r) for r in registration_data],
        active_subscription=_to_portal_subscription(active) if active else None,
        subscriptions=[_to_portal_subscription(s) for s in subscriptions],
        payments=[_to_portal_payment(p) for p in payments],
        invoices=[_to_portal_invoice(i) for i in invoices],
    )


@router.get("/invoices/{invoice_id}/pdf")
def download_invoice_pdf(
    invoice_id: str,
    db: Session = Depends(get_db),
    customer_id: str = Depends(get_current_customer_id),
):
    """Spec section 45/46: a customer may only download their own
    invoices - ownership is checked directly on the query, not just on
    the invoice_id being well-formed."""
    customer = _get_customer(db, customer_id)
    invoice = (
        db.query(Invoice)
        .filter(Invoice.invoice_id == invoice_id, Invoice.customer_id == customer.id)
        .first()
    )
    if invoice is None:
        raise InvoiceNotFoundError(f"Unknown invoice {invoice_id}")
    pdf_bytes = get_or_render_pdf(db, invoice)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{invoice.invoice_id}.pdf"'},
    )


@router.post("/subscriptions/{subscription_id}/upgrade", response_model=SubscribeResponse)
def upgrade(
    subscription_id: str,
    body: UpgradeDowngradeRequest,
    db: Session = Depends(get_db),
    customer_id: str = Depends(get_current_customer_id),
    application: Application = Depends(get_application),
):
    """Spec section 42: immediate on payment success, no proration, no
    refund. If the payment fails, the current plan remains active
    (enforced in PaymentService.process_gateway_result -> mark_payment_failed
    only touches PENDING_PAYMENT subscriptions, never an already-ACTIVE one)."""
    return _change_plan(db, subscription_id, body.target_plan_code, customer_id, application, expect_type="UPGRADE")


@router.post("/subscriptions/{subscription_id}/downgrade", response_model=SubscribeResponse)
def downgrade(
    subscription_id: str,
    body: UpgradeDowngradeRequest,
    db: Session = Depends(get_db),
    customer_id: str = Depends(get_current_customer_id),
    application: Application = Depends(get_application),
):
    return _change_plan(db, subscription_id, body.target_plan_code, customer_id, application, expect_type="DOWNGRADE")


def _change_plan(db, subscription_id, target_plan_code, customer_id, application, expect_type):
    if expect_type == "UPGRADE" and not application.allow_upgrade:
        raise ActionNotAllowed("Upgrades are currently disabled for this application")
    if expect_type == "DOWNGRADE" and not application.allow_downgrade:
        raise ActionNotAllowed("Downgrades are currently disabled for this application")
    customer = _get_customer(db, customer_id)
    subscription = _get_owned_subscription(db, customer=customer, subscription_id=subscription_id)

    target_plan = (
        db.query(Plan)
        .filter(Plan.application_id == application.id, Plan.plan_code == target_plan_code.upper(), Plan.active.is_(True))
        .first()
    )
    if target_plan is None:
        raise PlanNotFound(f"No active plan '{target_plan_code}'")
    if target_plan.is_trial:
        # A free trial can only ever be reached as a brand-new
        # subscription (spec follow-up: one trial per customer lifetime,
        # checked in create_pending_subscription()) - never as an
        # upgrade/downgrade target for an existing subscription.
        raise InvalidPlanTransition("Cannot switch to a free trial plan")

    transition_type = subscription_service.assert_transition_allowed(
        db, from_plan=subscription.plan, to_plan=target_plan
    )
    # assert_transition_allowed derives UPGRADE/DOWNGRADE from the two
    # plans' prices (no admin-configured allow-list required any more -
    # see that function's own docstring); expect_type is just which
    # endpoint the caller hit, kept for the allow_upgrade/allow_downgrade
    # gate above.
    payment_type = PaymentType.UPGRADE.value if transition_type == "UPGRADE" else PaymentType.DOWNGRADE.value

    payment = payment_service.create_payment_transaction(
        db,
        customer=customer,
        subscription=subscription,
        plan=target_plan,
        payment_type=payment_type,
        gateway_code=application.default_gateway,
        gateway_mode=application.gateway_mode,
        application=application,
    )
    db.commit()
    db.refresh(customer)
    db.refresh(subscription)
    db.refresh(payment)
    return SubscribeResponse(
        customer=customer, subscription=subscription, payment=payment_service.build_payment_out(payment)
    )


@router.post("/subscriptions/{subscription_id}/renew", response_model=SubscribeResponse)
def renew(
    subscription_id: str,
    db: Session = Depends(get_db),
    customer_id: str = Depends(get_current_customer_id),
    application: Application = Depends(get_application),
):
    """Spec section 38: manual/on-demand renewal payment. Automatic
    renewal on a billing schedule requires a Celery beat task, which is
    not wired up yet (see docs/implementation-status.md) - this endpoint
    is what that task would eventually call into as well."""
    if not application.renewal_enabled:
        raise ActionNotAllowed("Renewal is currently disabled for this application")
    customer = _get_customer(db, customer_id)
    subscription = _get_owned_subscription(db, customer=customer, subscription_id=subscription_id)
    if subscription.plan.is_trial:
        # Spec follow-up: a trial simply expires (and re-fires the
        # subscription.expired webhook via the existing expiry sweep) -
        # there is no renewal payment flow for it. A customer who wants to
        # keep using the product after their trial ends subscribes to a
        # paid plan instead (a fresh, non-trial create_pending_subscription
        # call), they don't "renew" the trial itself.
        raise ActionNotAllowed("A free trial subscription cannot be renewed")

    payment = payment_service.create_payment_transaction(
        db,
        customer=customer,
        subscription=subscription,
        plan=subscription.plan,
        payment_type=PaymentType.RENEWAL.value,
        gateway_code=application.default_gateway,
        gateway_mode=application.gateway_mode,
        application=application,
    )
    db.commit()
    db.refresh(customer)
    db.refresh(subscription)
    db.refresh(payment)
    return SubscribeResponse(
        customer=customer, subscription=subscription, payment=payment_service.build_payment_out(payment)
    )


@router.post("/subscriptions/{subscription_id}/cancel", response_model=PortalSubscriptionOut)
def cancel(
    subscription_id: str,
    body: CancelRequest,
    db: Session = Depends(get_db),
    customer_id: str = Depends(get_current_customer_id),
    application: Application = Depends(get_application),
):
    """Spec section 43: immediate, no refund, no future renewal."""
    if not application.allow_cancellation:
        raise ActionNotAllowed("Cancellation is currently disabled for this application")
    customer = _get_customer(db, customer_id)
    subscription = _get_owned_subscription(db, customer=customer, subscription_id=subscription_id)

    plan_name = subscription.plan.name
    subscription_service.cancel_subscription(
        db, subscription=subscription, cancelled_by=customer.customer_id, reason=body.reason, application=application
    )
    db.commit()
    db.refresh(subscription)

    email_service.send_templated_email(
        db,
        template_code="subscription_cancelled",
        to=customer.email,
        context={"plan_name": plan_name},
        related_entity_type="subscription",
        related_entity_id=subscription.subscription_id,
        application=application,
    )

    return _to_portal_subscription(subscription)
