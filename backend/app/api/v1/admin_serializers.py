"""
Shared ORM -> admin-schema converters (spec section 51).

These build schemas whose fields don't line up 1:1 with a single model's
own columns (e.g. SubscriptionAdminOut.customer_id is the CUSTOMER's
public id, reached via subscription.customer.customer_id, not a column on
Subscription itself) - so pydantic's from_attributes can't construct them
directly and every admin_*.py list/detail endpoint that needs one of these
would otherwise repeat the same relationship-walking code.
"""
from app.invoices.models import Invoice
from app.invoices.schemas import InvoiceAdminOut, InvoiceItemOut
from app.payments.models import PaymentTransaction
from app.payments.schemas import PaymentAdminOut
from app.subscriptions.models import Subscription
from app.subscriptions.schemas import SubscriptionAdminOut


def to_subscription_admin_out(sub: Subscription) -> SubscriptionAdminOut:
    return SubscriptionAdminOut(
        subscription_id=sub.subscription_id,
        customer_id=sub.customer.customer_id,
        plan_code=sub.plan.plan_code,
        plan_name=sub.plan.name,
        status=sub.status,
        provisioning_status=sub.provisioning_status,
        starts_at=sub.starts_at,
        expires_at=sub.expires_at,
        cancelled_at=sub.cancelled_at,
        cancellation_reason=sub.cancellation_reason,
        created_at=sub.created_at,
    )


def to_payment_admin_out(payment: PaymentTransaction) -> PaymentAdminOut:
    return PaymentAdminOut(
        transaction_id=payment.transaction_id,
        customer_id=payment.customer.customer_id,
        subscription_id=payment.subscription.subscription_id,
        plan_code=payment.target_plan.plan_code,
        gateway=payment.gateway,
        gateway_transaction_id=payment.gateway_transaction_id,
        amount=float(payment.amount),
        currency=payment.currency,
        payment_type=payment.payment_type,
        status=payment.status,
        failure_reason=payment.failure_reason,
        created_at=payment.created_at,
        updated_at=payment.updated_at,
        raw_gateway_response=payment.raw_gateway_response,
    )


def to_invoice_admin_out(invoice: Invoice) -> InvoiceAdminOut:
    return InvoiceAdminOut(
        invoice_id=invoice.invoice_id,
        customer_id=invoice.customer.customer_id,
        subscription_id=invoice.subscription.subscription_id,
        transaction_id=invoice.payment_transaction.transaction_id,
        invoice_date=invoice.invoice_date,
        billing_period_start=invoice.billing_period_start,
        billing_period_end=invoice.billing_period_end,
        gst_number=invoice.gst_number,
        amount=float(invoice.amount),
        tax_amount=float(invoice.tax_amount),
        total_amount=float(invoice.total_amount),
        currency=invoice.currency,
        items=[InvoiceItemOut.model_validate(item) for item in invoice.items],
    )
