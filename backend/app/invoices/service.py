"""Invoice generation (spec section 45).

Tax is computed from the admin-configurable rate in
app.invoices.tax.get_tax_config() (0% / disabled until an admin sets a
rate - see that module's docstring). `gst_number` on the invoice is the
CUSTOMER's own GSTIN (captured via the dynamic registration form's
"gstin" field, spec section 18) if they supplied one - the seller's own
GSTIN is business-level config (TaxConfigOut.seller_gstin) printed on the
PDF directly rather than duplicated onto every invoice row.

PDF generation is on-demand + cached to disk (see get_or_render_pdf) -
nothing renders a PDF until the first view/download/email actually needs
one, but every one of those call sites gets the same cached bytes back
afterwards without re-rendering.
"""
import os
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.ids import new_invoice_id
from app.customers.models import CustomerRegistrationData
from app.invoices.models import Invoice, InvoiceItem
from app.invoices.pdf import build_invoice_pdf
from app.invoices.tax import get_tax_config
from app.payments.models import PaymentTransaction
from app.subscriptions.models import Subscription


def _lookup_customer_gstin(db: Session, *, customer_id: int, application_id: int) -> str | None:
    """Most recent registration-data submission that included a "gstin"
    value for this customer, if any (spec section 18's dynamic form
    already collects this - see app/core/seed.py's default field set)."""
    rows = (
        db.query(CustomerRegistrationData)
        .filter(
            CustomerRegistrationData.customer_id == customer_id,
            CustomerRegistrationData.application_id == application_id,
        )
        .order_by(CustomerRegistrationData.created_at.desc())
        .all()
    )
    for row in rows:
        value = (row.data or {}).get("gstin")
        if value:
            return str(value)
    return None


def generate_invoice(
    db: Session, *, subscription: Subscription, payment: PaymentTransaction
) -> Invoice:
    today = datetime.now(timezone.utc).date()
    period_start: date = subscription.starts_at.date() if subscription.starts_at else today
    period_end: date = subscription.expires_at.date() if subscription.expires_at else today

    tax_config = get_tax_config(db)
    amount = float(payment.amount)
    tax_amount = round(amount * float(tax_config.gst_rate_percent) / 100, 2) if tax_config.gst_rate_percent else 0.0
    total_amount = amount + tax_amount
    gst_number = _lookup_customer_gstin(
        db, customer_id=subscription.customer_id, application_id=subscription.application_id
    )

    invoice = Invoice(
        invoice_id=new_invoice_id(),
        customer_id=subscription.customer_id,
        subscription_id=subscription.id,
        payment_transaction_id=payment.id,
        invoice_date=today,
        billing_period_start=period_start,
        billing_period_end=period_end,
        gst_number=gst_number,
        amount=amount,
        tax_amount=tax_amount,
        total_amount=total_amount,
        currency=payment.currency,
    )
    db.add(invoice)
    db.flush()

    db.add(
        InvoiceItem(
            invoice_id=invoice.id,
            description=f"{subscription.plan.name} subscription ({payment.payment_type})",
            quantity=1,
            unit_price=payment.amount,
            amount=payment.amount,
        )
    )
    db.flush()
    return invoice


def _pdf_storage_path(invoice: Invoice) -> str:
    settings = get_settings()
    directory = settings.INVOICE_PDF_STORAGE_DIR
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, f"{invoice.invoice_id}.pdf")


def get_or_render_pdf(db: Session, invoice: Invoice) -> bytes:
    """Returns this invoice's PDF bytes, rendering + caching to disk on
    first use. Safe to call repeatedly (view, download, email-resend all
    share the same cached file) - a corrupt/missing cached file on disk
    (e.g. deleted out-of-band) just triggers a fresh render rather than
    erroring."""
    path = invoice.pdf_path or _pdf_storage_path(invoice)
    if invoice.pdf_path and os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()

    tax_config = get_tax_config(db)
    pdf_bytes = build_invoice_pdf(invoice, tax_config=tax_config)

    path = _pdf_storage_path(invoice)
    with open(path, "wb") as f:
        f.write(pdf_bytes)

    invoice.pdf_path = path
    db.add(invoice)
    db.commit()
    db.refresh(invoice)
    return pdf_bytes
