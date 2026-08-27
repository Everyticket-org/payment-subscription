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
