"""Pydantic schemas for subscriptions (spec sections 19-22)."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    subscription_id: str
    status: str
    provisioning_status: str
    starts_at: datetime | None = None
    expires_at: datetime | None = None


class SubscribeResponse(BaseModel):
    customer: "CustomerOut"
    subscription: SubscriptionOut
    payment: "PaymentTransactionOut"

    model_config = ConfigDict(from_attributes=True)


# Resolve forward refs lazily to avoid a circular import at module load time.
from app.customers.schemas import CustomerOut  # noqa: E402
from app.payments.schemas import PaymentTransactionOut  # noqa: E402

SubscribeResponse.model_rebuild()
