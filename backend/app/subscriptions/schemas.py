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
    render (spec section 46) without a second round trip.
    billing_interval/billing_frequency were added for the combined
    subscriptions+payments+invoices table (admin-panel request, 2026-09)
    so the portal can show a "Billing Cycle" column (e.g. "Monthly" /
    "Annual") without a second call to /public/plans."""
    plan_code: str
    plan_name: str
    price: float
    currency: str
    billing_interval: str
    billing_frequency: int


class SubscribeResponse(BaseModel):
    customer: "CustomerOut"
    subscription: SubscriptionOut
    payment: "PaymentTransactionOut"

    model_config = ConfigDict(from_attributes=True)


class UpgradeDowngradeRequest(BaseModel):
    target_plan_code: str


class CancelRequest(BaseModel):
    reason: str | None = None


class SubscriptionHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    event_type: str
    occurred_at: datetime
    event_metadata: dict | None = None


class SubscriptionAdminOut(BaseModel):
    """Admin list/detail row (spec section 51 'Subscriptions' module).
    `customer_id`/`plan_code` are the public string ids, never internal
    surrogate PKs - consistent with every other admin-facing schema."""
    model_config = ConfigDict(from_attributes=True)
    subscription_id: str
    customer_id: str
    plan_code: str
    plan_name: str
    status: str
    provisioning_status: str
    starts_at: datetime | None = None
    expires_at: datetime | None = None
    cancelled_at: datetime | None = None
    cancellation_reason: str | None = None
    created_at: datetime


class SubscriptionDetailAdminOut(BaseModel):
    subscription: SubscriptionAdminOut
    history: list[SubscriptionHistoryOut] = []


# Resolve forward refs lazily to avoid a circular import at module load time.
from app.customers.schemas import CustomerOut  # noqa: E402
from app.payments.schemas import PaymentTransactionOut  # noqa: E402

SubscribeResponse.model_rebuild()
