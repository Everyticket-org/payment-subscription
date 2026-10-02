"""Admin Payments (spec sections 23-28, 51, 53) - read-only. Spec section
53's "do not allow unsafe editing of financial transaction history"
applies most strongly here: there is no admin endpoint anywhere that can
change a PaymentTransaction's status/amount - that only ever happens
through app.payments.service, driven by a real (or, later, simulated)
gateway callback."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_db
from app.api.v1.admin_common import DEFAULT_LIMIT, MAX_LIMIT, PageOut, paginate
from app.api.v1.admin_serializers import to_payment_admin_out
from app.auth.deps import require_permission
from app.auth.models import AdminUser
from app.core.exceptions import PaymentTransactionNotFound
from app.customers.models import Customer
from app.payments.models import PaymentEvent, PaymentTransaction
from app.payments.schemas import PaymentAdminOut, PaymentEventOut

router = APIRouter(prefix="/payments", tags=["admin-payments"])


@router.get("", response_model=PageOut[PaymentAdminOut])
def list_payments(
    status_filter: str | None = Query(default=None, alias="status"),
    gateway: str | None = Query(default=None),
    customer_id: str | None = Query(default=None, description="Public CUS-xxxx id"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(require_permission("PAYMENTS_VIEW")),
):
    query = db.query(PaymentTransaction).options(
        joinedload(PaymentTransaction.customer),
        joinedload(PaymentTransaction.subscription),
        joinedload(PaymentTransaction.target_plan),
    )
    if status_filter:
        query = query.filter(PaymentTransaction.status == status_filter.upper())
    if gateway:
        query = query.filter(PaymentTransaction.gateway == gateway.lower())
    if customer_id:
        query = query.join(PaymentTransaction.customer).filter(Customer.customer_id == customer_id)
    query = query.order_by(PaymentTransaction.created_at.desc())

    items, total = paginate(query, limit=limit, offset=offset)
    return PageOut(items=[to_payment_admin_out(p) for p in items], total=total, limit=limit, offset=offset)


@router.get("/{transaction_id}", response_model=PaymentAdminOut)
def get_payment(
    transaction_id: str,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(require_permission("PAYMENTS_VIEW")),
):
    payment = db.query(PaymentTransaction).filter(PaymentTransaction.transaction_id == transaction_id).first()
    if payment is None:
        raise PaymentTransactionNotFound(f"Unknown payment transaction {transaction_id}")
    return to_payment_admin_out(payment)


@router.get("/{transaction_id}/events", response_model=list[PaymentEventOut])
def list_payment_events(
    transaction_id: str,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(require_permission("PAYMENTS_VIEW")),
):
    """This payment's history, oldest first (app.payments.events): where it
    was started, the surl/furl PayU was given, and every browser return,
    webhook and reconciliation check that arrived. Read-only."""
    exists = db.query(PaymentTransaction.id).filter(PaymentTransaction.transaction_id == transaction_id).first()
    if exists is None:
        raise PaymentTransactionNotFound(f"Unknown payment transaction {transaction_id}")
    events = (
        db.query(PaymentEvent)
        .filter(PaymentEvent.transaction_id == transaction_id)
        .order_by(PaymentEvent.created_at.asc(), PaymentEvent.id.asc())
        .all()
    )
    return [PaymentEventOut.model_validate(event) for event in events]
