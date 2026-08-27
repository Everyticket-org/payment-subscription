"""Invoice generation (spec section 45).

LIMITATION: tax_amount is always 0 in this pass (no GST rate configuration
yet) - total_amount == amount until tax calculation is implemented. PDF
generation/email delivery are also not wired up yet (see
docs/implementation-status.md)."""
from datetime import date, datetime, timezone

from sqlalchemy.orm import Session

from app.core.ids import new_invoice_id
from app.invoices.models import Invoice, InvoiceItem
from app.payments.models import PaymentTransaction
from app.subscriptions.models import Subscription


def generate_invoice(
    db: Session, *, subscription: Subscription, payment: PaymentTransaction
) -> Invoice:
    today = datetime.now(timezone.utc).date()
    period_start: date = subscription.starts_at.date() if subscription.starts_at else today
    period_end: date = subscription.expires_at.date() if subscription.expires_at else today

    invoice = Invoice(
        invoice_id=new_invoice_id(),
        customer_id=subscription.customer_id,
        subscription_id=subscription.id,
        payment_transaction_id=payment.id,
        invoice_date=today,
        billing_period_start=period_start,
        billing_period_end=period_end,
        amount=payment.amount,
        tax_amount=0,
        total_amount=payment.amount,
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
