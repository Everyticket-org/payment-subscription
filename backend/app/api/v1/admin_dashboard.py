"""Admin dashboard (spec section 52: active/new subscriptions, revenue,
failed payments, expiring/expired subscriptions, provisioning failures,
webhook failures - all scoped to the current application and a rolling
30-day window unless noted otherwise)."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_application, get_db
from app.applications.models import Application
from app.auth.deps import require_permission
from app.core.enums import PaymentStatus, ProvisioningStatus, SubscriptionStatus, WebhookDeliveryStatus
from app.payments.models import PaymentTransaction
from app.subscriptions.models import Subscription
from app.webhooks.models import WebhookDelivery

router = APIRouter(prefix="/dashboard", tags=["admin-dashboard"])


class DashboardStatsOut(BaseModel):
    active_subscriptions: int
    new_subscriptions_30d: int
    revenue_30d: float
    revenue_currency: str
    failed_payments_30d: int
    expiring_within_7d: int
    expired_total: int
    provisioning_failures: int
    webhook_failures: int


@router.get("", response_model=DashboardStatsOut)
def get_dashboard(
    db: Session = Depends(get_db),
    application: Application = Depends(get_application),
    _admin=Depends(require_permission("DASHBOARD_VIEW")),
):
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=30)
    soon = now + timedelta(days=7)

    active_subscriptions = (
        db.query(Subscription)
        .filter(Subscription.application_id == application.id, Subscription.status == SubscriptionStatus.ACTIVE.value)
        .count()
    )
    new_subscriptions_30d = (
        db.query(Subscription)
        .filter(Subscription.application_id == application.id, Subscription.created_at >= window_start)
        .count()
    )
    revenue_30d = (
        db.query(func.coalesce(func.sum(PaymentTransaction.amount), 0))
        .join(Subscription, PaymentTransaction.subscription_id == Subscription.id)
        .filter(
            Subscription.application_id == application.id,
            PaymentTransaction.status == PaymentStatus.SUCCESS.value,
            PaymentTransaction.created_at >= window_start,
        )
        .scalar()
        or 0
    )
    failed_payments_30d = (
        db.query(PaymentTransaction)
        .join(Subscription, PaymentTransaction.subscription_id == Subscription.id)
        .filter(
            Subscription.application_id == application.id,
            PaymentTransaction.status == PaymentStatus.FAILED.value,
            PaymentTransaction.created_at >= window_start,
        )
        .count()
    )
    expiring_within_7d = (
        db.query(Subscription)
        .filter(
            Subscription.application_id == application.id,
            Subscription.status == SubscriptionStatus.ACTIVE.value,
            Subscription.expires_at.isnot(None),
            Subscription.expires_at <= soon,
        )
        .count()
    )
    expired_total = (
        db.query(Subscription)
        .filter(Subscription.application_id == application.id, Subscription.status == SubscriptionStatus.EXPIRED.value)
        .count()
    )
    provisioning_failures = (
        db.query(Subscription)
        .filter(
            Subscription.application_id == application.id,
            Subscription.provisioning_status == ProvisioningStatus.FAILED.value,
        )
        .count()
    )
    webhook_failures = (
        db.query(WebhookDelivery)
        .filter(
            WebhookDelivery.destination_application_id == application.id,
            WebhookDelivery.status.in_([WebhookDeliveryStatus.FAILED.value, WebhookDeliveryStatus.EXHAUSTED.value]),
        )
        .count()
    )

    return DashboardStatsOut(
        active_subscriptions=active_subscriptions,
        new_subscriptions_30d=new_subscriptions_30d,
        revenue_30d=float(revenue_30d),
        revenue_currency=application.currency,
        failed_payments_30d=failed_payments_30d,
        expiring_within_7d=expiring_within_7d,
        expired_total=expired_total,
        provisioning_failures=provisioning_failures,
        webhook_failures=webhook_failures,
    )
