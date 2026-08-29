"""Admin Invoices (spec section 45, 51) - read-only. Generation/PDF/email
delivery is a separate, not-yet-built increment (see
docs/implementation-status.md) - this module only surfaces invoices that
already exist."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_db
from app.api.v1.admin_common import DEFAULT_LIMIT, MAX_LIMIT, PageOut, paginate
from app.api.v1.admin_serializers import to_invoice_admin_out
from app.auth.deps import require_permission
from app.auth.models import AdminUser
from app.core.exceptions import AppError
from app.customers.models import Customer
from app.invoices.models import Invoice
from app.invoices.schemas import InvoiceAdminOut

router = APIRouter(prefix="/invoices", tags=["admin-invoices"])


class InvoiceNotFoundError(AppError):
    http_status = 404
    error_code = "INVOICE_NOT_FOUND"


@router.get("", response_model=PageOut[InvoiceAdminOut])
def list_invoices(
    customer_id: str | None = Query(default=None, description="Public CUS-xxxx id"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(require_permission("INVOICES_VIEW")),
):
    query = db.query(Invoice).options(
        joinedload(Invoice.customer), joinedload(Invoice.subscription), joinedload(Invoice.payment_transaction)
    )
    if customer_id:
        query = query.join(Invoice.customer).filter(Customer.customer_id == customer_id)
    query = query.order_by(Invoice.created_at.desc())

    items, total = paginate(query, limit=limit, offset=offset)
    return PageOut(items=[to_invoice_admin_out(i) for i in items], total=total, limit=limit, offset=offset)


@router.get("/{invoice_id}", response_model=InvoiceAdminOut)
def get_invoice(
    invoice_id: str,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(require_permission("INVOICES_VIEW")),
):
    invoice = db.query(Invoice).filter(Invoice.invoice_id == invoice_id).first()
    if invoice is None:
        raise InvoiceNotFoundError(f"Unknown invoice {invoice_id}")
    return to_invoice_admin_out(invoice)
