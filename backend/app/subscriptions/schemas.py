"""Pydantic schemas for subscriptions (spec sections 19-22, 38-43, 46)."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    subscription_id: str
    status: str
    provisioning_status: str
    starts_at: datetime | None = None
    expires_at: datetime | None = None


class PortalSubscriptionOut(SubscriptionOut):
    """SubscriptionOut plus the plan snapshot the customer portal needs to
    render (spec section 46) without a second round trip."""
    plan_code: str
    plan_name: str
    price: float
    currency: str


class SubscribeResponse(BaseModel):
    customer: "CustomerOut"
    subscription: SubscriptionOut
    payment: "PaymentTransactionOut"

    model_config = ConfigDict(from_attributes=True)


class UpgradeDowngradeRequest(BaseModel):
    target_plan_code: str


class CancelRequest(BaseModel):
    reason: str | None = None


# Resolve forward refs lazily to avoid a circular import at module load time.
from app.customers.schemas import CustomerOut  # noqa: E402
from app.payments.schemas import PaymentTransactionOut  # noqa: E402

SubscribeResponse.model_rebuild()
