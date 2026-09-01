"""Customer portal read schema (spec section 46). Kept out of
app/customers/schemas.py to avoid a circular import (it needs
SubscriptionOut/PaymentTransactionOut/InvoiceOut, which themselves avoid
importing back into customers.schemas)."""
from pydantic import BaseModel

from app.customers.schemas import CustomerOut, RegistrationDataOut
from app.invoices.schemas import InvoiceOut
from app.payments.schemas import PaymentTransactionOut
from app.subscriptions.schemas import PortalSubscriptionOut


class CustomerPortalOut(BaseModel):
    customer: CustomerOut
    # The customer's own dynamic-registration-form submission(s) (spec
    # section 18) - added so "My account" can show identity + registration
    # details together in one card (admin-panel/frontend request, 2026-09)
    # instead of the customer having no way to see what they submitted at
    # signup.
    registration_data: list[RegistrationDataOut] = []
    active_subscription: PortalSubscriptionOut | None
    subscriptions: list[PortalSubscriptionOut]
    payments: list[PaymentTransactionOut]
    invoices: list[InvoiceOut]
