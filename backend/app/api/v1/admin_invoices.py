"""Admin Invoices (spec section 45, 51) - view, PDF download, GST/tax
configuration, and on-demand invoice-email resend."""
from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import get_db
from app.api.v1.admin_common import DEFAULT_LIMIT, MAX_LIMIT, PageOut, paginate
from app.api.v1.admin_serializers import to_invoice_admin_out
from app.audit import service as audit_service
from app.auth.deps import require_permission
from app.auth.models import AdminUser
from app.core.exceptions import AppError
from app.applications.models import Application
from app.customers.models import Customer
from app.invoices.models import Invoice
from app.invoices.schemas import InvoiceAdminOut, InvoiceEmailResult, TaxConfigOut, TaxConfigUpdate
from app.invoices.service import get_or_render_pdf
from app.invoices.tax import get_tax_config, set_tax_config
from app.notifications.email import service as email_service
from sqlalchemy.orm import Session, joinedload

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


# NOTE: these two literal routes must be registered before the "/{invoice_id}"
# routes below, or FastAPI would try to match "tax-config" as an invoice_id.
@router.get("/tax-config", response_model=TaxConfigOut)
def get_invoice_tax_config(
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(require_permission("INVOICES_VIEW")),
):
    return get_tax_config(db)


@router.put("/tax-config", response_model=TaxConfigOut)
def update_invoice_tax_config(
    body: TaxConfigUpdate,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_permission("INVOICES_MANAGE")),
):
    updated = set_tax_config(db, update=body)
    audit_service.record(
        db, actor=admin.email, action="INVOICE_TAX_CONFIG_UPDATED", entity_type="system_setting",
        entity_id="invoice_tax_config", new_value=updated.model_dump(),
    )
    db.commit()
    return updated


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


@router.get("/{invoice_id}/pdf")
def download_invoice_pdf(
    invoice_id: str,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(require_permission("INVOICES_VIEW")),
):
    invoice = db.query(Invoice).filter(Invoice.invoice_id == invoice_id).first()
    if invoice is None:
        raise InvoiceNotFoundError(f"Unknown invoice {invoice_id}")
    pdf_bytes = get_or_render_pdf(db, invoice)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{invoice.invoice_id}.pdf"'},
    )


@router.post("/{invoice_id}/send-email", response_model=InvoiceEmailResult)
def send_invoice_email(
    invoice_id: str,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_permission("INVOICES_MANAGE")),
):
    invoice = db.query(Invoice).filter(Invoice.invoice_id == invoice_id).first()
    if invoice is None:
        raise InvoiceNotFoundError(f"Unknown invoice {invoice_id}")

    pdf_bytes = get_or_render_pdf(db, invoice)
    to = invoice.customer.email
    application = db.get(Application, invoice.subscription.application_id)
    sent = email_service.send_templated_email(
        db,
        template_code="invoice_generated",
        to=to,
        context={
            "invoice_id": invoice.invoice_id,
            "plan_name": invoice.subscription.plan.name,
            "currency": invoice.currency,
            "amount": f"{float(invoice.amount):.2f}",
            "tax_amount": f"{float(invoice.tax_amount):.2f}",
            "total_amount": f"{float(invoice.total_amount):.2f}",
        },
        related_entity_type="invoice",
        related_entity_id=invoice.invoice_id,
        attachments=[(f"{invoice.invoice_id}.pdf", pdf_bytes, "pdf")],
        application=application,
    )
    audit_service.record(
        db, actor=admin.email, action="INVOICE_EMAIL_RESENT", entity_type="invoice",
        entity_id=invoice.invoice_id, new_value={"sent": sent, "to": to},
    )
    db.commit()
    return InvoiceEmailResult(sent=sent, to=to)
