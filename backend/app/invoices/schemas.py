"""Pydantic schemas for invoices (spec section 45)."""
from datetime import date

from pydantic import BaseModel, ConfigDict


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    invoice_id: str
    invoice_date: date
    amount: float
    tax_amount: float
    total_amount: float
    currency: str


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
