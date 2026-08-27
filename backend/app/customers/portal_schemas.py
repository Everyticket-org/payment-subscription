"""Customer portal read schema (spec section 46). Kept out of
app/customers/schemas.py to avoid a circular import (it needs
SubscriptionOut/PaymentTransactionOut/InvoiceOut, which themselves avoid
importing back into customers.schemas)."""
from pydantic import BaseModel

from app.customers.schemas import CustomerOut
from app.invoices.schemas import InvoiceOut
from app.payments.schemas import PaymentTransactionOut
from app.subscriptions.schemas import PortalSubscriptionOut


class CustomerPortalOut(BaseModel):
    customer: CustomerOut
    active_subscription: PortalSubscriptionOut | None
    subscriptions: list[PortalSubscriptionOut]
    payments: list[PaymentTransactionOut]
    invoices: list[InvoiceOut]
