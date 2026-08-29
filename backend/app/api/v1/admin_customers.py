"""
Admin Customers (spec section 51 'Customers' / 53).

Spec section 53 explicitly says "do not allow unsafe editing of financial
transaction history" - so this module only ever changes Customer.status
(suspend/activate); subscriptions/payments/invoices are surfaced here
read-only, sourced from their own domain models, never mutated.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import get_application, get_db
from app.api.v1.admin_common import DEFAULT_LIMIT, MAX_LIMIT, PageOut, paginate
from app.api.v1.admin_serializers import to_invoice_admin_out, to_payment_admin_out, to_subscription_admin_out
from app.applications.models import Application, CustomerApplicationMapping
from app.audit import service as audit_service
from app.auth.deps import require_permission, require_test_mode
from app.auth.models import AdminUser
from app.core.config import get_settings
from app.core.enums import CustomerStatus
from app.core.exceptions import CustomerNotFound
from app.customers.models import Customer, CustomerRegistrationData
from app.customers.schemas import (
    ApplicationMappingOut,
    CustomerAdminDetailOut,
    CustomerAdminListItem,
    CustomerOut,
    RegistrationDataOut,
    SuspendCustomerRequest,
)
from app.invoices.models import Invoice
from app.payments.models import PaymentTransaction
from app.subscriptions.models import Subscription
from app.sso import service as sso_service
from app.sso.schemas import SsoLinkOut

router = APIRouter(prefix="/customers", tags=["admin-customers"])


def _get_customer(db: Session, customer_id: str) -> Customer:
    customer = db.query(Customer).filter(Customer.customer_id == customer_id).first()
    if customer is None:
        raise CustomerNotFound(f"Unknown customer {customer_id}")
    return customer


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@router.get("", response_model=PageOut[CustomerAdminListItem])
def list_customers(
    q: str | None = Query(default=None, description="Search by email, mobile, or customer_id"),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(require_permission("CUSTOMERS_VIEW")),
):
    query = db.query(Customer)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(Customer.email.ilike(like), Customer.mobile.ilike(like), Customer.customer_id.ilike(like))
        )
    if status_filter:
        query = query.filter(Customer.status == status_filter.upper())
    query = query.order_by(Customer.created_at.desc())

    items, total = paginate(query, limit=limit, offset=offset)
    return PageOut(items=[CustomerAdminListItem.model_validate(c) for c in items], total=total, limit=limit, offset=offset)


@router.get("/{customer_id}", response_model=CustomerAdminDetailOut)
def get_customer(
    customer_id: str,
    db: Session = Depends(get_db),
    application: Application = Depends(get_application),
    _admin: AdminUser = Depends(require_permission("CUSTOMERS_VIEW")),
):
    customer = _get_customer(db, customer_id)

    registration_rows = (
        db.query(CustomerRegistrationData)
        .filter(CustomerRegistrationData.customer_id == customer.id)
        .order_by(CustomerRegistrationData.created_at.desc())
        .all()
    )
    mapping = (
        db.query(CustomerApplicationMapping)
        .filter(
            CustomerApplicationMapping.customer_id == customer.id,
            CustomerApplicationMapping.application_id == application.id,
        )
        .first()
    )
    subscriptions = (
        db.query(Subscription)
        .filter(Subscription.customer_id == customer.id)
        .order_by(Subscription.created_at.desc())
        .all()
    )
    payments = (
        db.query(PaymentTransaction)
        .filter(PaymentTransaction.customer_id == customer.id)
        .order_by(PaymentTransaction.created_at.desc())
        .all()
    )
    invoices = (
        db.query(Invoice).filter(Invoice.customer_id == customer.id).order_by(Invoice.created_at.desc()).all()
    )

    return CustomerAdminDetailOut(
        customer=CustomerOut.model_validate(customer),
        registration_data=[RegistrationDataOut.model_validate(r) for r in registration_rows],
        application_mapping=ApplicationMappingOut.model_validate(mapping) if mapping else None,
        subscriptions=[to_subscription_admin_out(s) for s in subscriptions],
        payments=[to_payment_admin_out(p) for p in payments],
        invoices=[to_invoice_admin_out(i) for i in invoices],
    )


@router.post("/{customer_id}/suspend", response_model=CustomerOut)
def suspend_customer(
    customer_id: str,
    body: SuspendCustomerRequest,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_permission("CUSTOMERS_MANAGE")),
):
    customer = _get_customer(db, customer_id)
    old_status = customer.status
    customer.status = CustomerStatus.SUSPENDED.value
    db.add(customer)

    audit_service.record(
        db,
        actor=admin.email,
        action="CUSTOMER_SUSPENDED",
        entity_type="customer",
        entity_id=customer.customer_id,
        old_value={"status": old_status},
        new_value={"status": customer.status, "reason": body.reason},
        ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(customer)
    return CustomerOut.model_validate(customer)


@router.post("/{customer_id}/activate", response_model=CustomerOut)
def activate_customer(
    customer_id: str,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_permission("CUSTOMERS_MANAGE")),
):
    customer = _get_customer(db, customer_id)
    old_status = customer.status
    customer.status = CustomerStatus.ACTIVE.value
    db.add(customer)

    audit_service.record(
        db,
        actor=admin.email,
        action="CUSTOMER_ACTIVATED",
        entity_type="customer",
        entity_id=customer.customer_id,
        old_value={"status": old_status},
        new_value={"status": customer.status},
        ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(customer)
    return CustomerOut.model_validate(customer)


@router.post("/{customer_id}/sso-link", response_model=SsoLinkOut)
def generate_test_sso_link(
    customer_id: str,
    request: Request,
    db: Session = Depends(get_db),
    application: Application = Depends(get_application),
    admin: AdminUser = Depends(require_permission("CUSTOMERS_MANAGE")),
    _test_mode: None = Depends(require_test_mode),
):
    """TEST_MODE-only convenience (spec section 47/54): in production only
    Everyticket itself ever calls sso_service.create_sso_token() (as part
    of its own redirect flow, entirely outside this app). There is no real
    Everyticket instance in this build, so this endpoint lets an admin
    generate a working, single-use SSO token/consume-link for a given
    customer to exercise the full handoff end-to-end."""
    settings = get_settings()
    customer = _get_customer(db, customer_id)
    token = sso_service.create_sso_token(db, application=application, customer=customer)

    audit_service.record(
        db,
        actor=admin.email,
        action="SSO_TEST_LINK_GENERATED",
        entity_type="customer",
        entity_id=customer.customer_id,
        new_value={"application_code": application.code},
        ip_address=_client_ip(request),
    )
    db.commit()

    expires_at = _utcnow() + timedelta(seconds=settings.SSO_TOKEN_TTL_SECONDS)
    consume_url = f"{settings.FRONTEND_URL.rstrip('/')}/sso/consume?token={token}"
    return SsoLinkOut(sso_token=token, consume_url=consume_url, expires_at=expires_at)
