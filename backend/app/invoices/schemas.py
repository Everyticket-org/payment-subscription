"""Pydantic schemas for invoices (spec section 45)."""
from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    invoice_id: str
    invoice_date: date
    amount: float
    tax_amount: float
    total_amount: float
    currency: str
    # Same deliberate pattern as PaymentTransactionOut.subscription_ref
    # (see that field's comment): Invoice.subscription_id is the internal
    # integer FK, not the public string, so these two are set explicitly
    # by the caller rather than auto-populated by model_validate(). Added
    # for the customer-portal combined subscriptions+payments+invoices
    # table (admin-panel request, 2026-09).
    subscription_ref: str | None = None
    transaction_id: str | None = None


class InvoiceItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    description: str
    quantity: int
    unit_price: float
    amount: float


class InvoiceAdminOut(BaseModel):
    """Admin list/detail row (spec section 51 'Invoices' module) - full
    detail including customer/subscription/payment linkage and line items,
    unlike the customer-portal InvoiceOut above which only needs enough to
    render a list."""
    model_config = ConfigDict(from_attributes=False)
    invoice_id: str
    customer_id: str
    subscription_id: str
    transaction_id: str
    invoice_date: date
    billing_period_start: date
    billing_period_end: date
    gst_number: str | None = None
    amount: float
    tax_amount: float
    total_amount: float
    currency: str
    items: list[InvoiceItemOut] = []


class TaxConfigOut(BaseModel):
    """Current GST/tax configuration used when generating new invoices
    (spec sections 45, 51, 81). `seller_gstin` is this business's own
    GSTIN, printed on every invoice PDF - distinct from a customer's own
    GSTIN, which is captured per-customer via the dynamic registration
    form's "gstin" field (spec section 18) and shown as that invoice's
    `gst_number`."""
    gst_rate_percent: float = 0
    seller_gstin: str | None = None
    tax_label: str = "GST"


class TaxConfigUpdate(BaseModel):
    gst_rate_percent: float = Field(ge=0, le=100)
    seller_gstin: str | None = None
    tax_label: str = "GST"


class InvoiceEmailResult(BaseModel):
    sent: bool
    to: str | None = None
