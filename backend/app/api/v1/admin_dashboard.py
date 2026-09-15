"""Admin dashboard (spec section 52: active/new subscriptions, revenue,
failed payments, expiring/expired subscriptions, provisioning failures,
webhook failures - all scoped to the current application and a rolling
30-day window unless noted otherwise).

2026-09-15 follow-up ("suggest better design of admin panel... start with
dashboard design"): the approved dashboard redesign mockup wanted trend
indicators, a revenue-by-month chart, a plan-mix breakdown, and a "recent
subscriptions" table - none of that data existed on this endpoint before.
Every new field below is computed from real rows (nothing fabricated the
way the review mockup's numbers were) and is purely ADDITIVE to
DashboardStatsOut, so any caller relying only on the original 9 fields is
unaffected. Month/plan grouping is done in Python rather than a SQL
GROUP BY specifically to stay portable across the SQLite (tests) / MySQL
(real deployment) split this app already has to support (see the
2026-09-13 MySQL-switch notes) - the row counts here are small enough
(one admin dashboard's worth of recent activity) that this isn't a
performance concern."""
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_application, get_db
from app.applications.models import Application
from app.auth.deps import require_permission
from app.core.enums import PaymentStatus, ProvisioningStatus, SubscriptionStatus, WebhookDeliveryStatus
from app.payments.models import PaymentTransaction
from app.plans.models import Plan
from app.subscriptions.models import Subscription
from app.webhooks.models import WebhookDelivery

router = APIRouter(prefix="/dashboard", tags=["admin-dashboard"])

_MONTH_ABBR = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_RECENT_SUBSCRIPTIONS_LIMIT = 8
_REVENUE_TREND_MONTHS = 6


def _month_start(reference: datetime, months_back: int) -> datetime:
    """First instant of the month that is `months_back` months before
    `reference`'s month (0 = reference's own month). Plain calendar
    arithmetic, no dialect-specific date functions - kept here rather than
    pushed into SQL so revenue_by_month's bucketing works identically on
    SQLite (tests) and MySQL (real deployment)."""
    year = reference.year
    month = reference.month - months_back
    while month <= 0:
        month += 12
        year -= 1
    return reference.replace(year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0)


class RevenueMonthPoint(BaseModel):
    month: str  # "2026-04", stable sort/lookup key
    month_label: str  # "Apr 2026", for display
    amount: float


class PlanMixItem(BaseModel):
    plan_code: str
    plan_name: str
    count: int
    percentage: float


class RecentSubscriptionItem(BaseModel):
    subscription_id: str
    customer_id: str
    customer_email: str
    plan_name: str
    status: str
    amount: float | None
    currency: str
    created_at: datetime


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
    # Previous-30-day-window comparators (2026-09-15 dashboard redesign) -
    # sent as raw values, not a pre-computed percentage, so the frontend
    # can decide how to present a zero-baseline ("new" vs "+100%") without
    # this endpoint guessing. Deliberately NOT provided for
    # active_subscriptions: that figure is a point-in-time count, not a
    # windowed sum, so there is no honest "30 days ago" comparison to make
    # without a historical snapshot this app doesn't keep.
    new_subscriptions_30d_prev: int
    revenue_30d_prev: float
    failed_payments_30d_prev: int
    revenue_by_month: list[RevenueMonthPoint]
    plan_mix: list[PlanMixItem]
    recent_subscriptions: list[RecentSubscriptionItem]


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

    # ---- Previous-30-day-window comparators (2026-09-15 dashboard redesign) ----
    # The window immediately before the current one, same width, so the
    # frontend can render a "+12% vs previous 30 days" style trend chip.
    prev_window_start = window_start - timedelta(days=30)
    prev_window_end = window_start

    new_subscriptions_30d_prev = (
        db.query(Subscription)
        .filter(
            Subscription.application_id == application.id,
            Subscription.created_at >= prev_window_start,
            Subscription.created_at < prev_window_end,
        )
        .count()
    )
    revenue_30d_prev = (
        db.query(func.coalesce(func.sum(PaymentTransaction.amount), 0))
        .join(Subscription, PaymentTransaction.subscription_id == Subscription.id)
        .filter(
            Subscription.application_id == application.id,
            PaymentTransaction.status == PaymentStatus.SUCCESS.value,
            PaymentTransaction.created_at >= prev_window_start,
            PaymentTransaction.created_at < prev_window_end,
        )
        .scalar()
        or 0
    )
    failed_payments_30d_prev = (
        db.query(PaymentTransaction)
        .join(Subscription, PaymentTransaction.subscription_id == Subscription.id)
        .filter(
            Subscription.application_id == application.id,
            PaymentTransaction.status == PaymentStatus.FAILED.value,
            PaymentTransaction.created_at >= prev_window_start,
            PaymentTransaction.created_at < prev_window_end,
        )
        .count()
    )

    # ---- revenue_by_month: last _REVENUE_TREND_MONTHS calendar months of
    # successful payments, bucketed in Python (see _month_start docstring). ----
    trend_start = _month_start(now, _REVENUE_TREND_MONTHS - 1)
    month_totals: "OrderedDict[str, float]" = OrderedDict()
    for months_back in range(_REVENUE_TREND_MONTHS - 1, -1, -1):
        bucket_start = _month_start(now, months_back)
        month_totals[f"{bucket_start.year:04d}-{bucket_start.month:02d}"] = 0.0

    trend_rows = (
        db.query(PaymentTransaction.created_at, PaymentTransaction.amount)
        .join(Subscription, PaymentTransaction.subscription_id == Subscription.id)
        .filter(
            Subscription.application_id == application.id,
            PaymentTransaction.status == PaymentStatus.SUCCESS.value,
            PaymentTransaction.created_at >= trend_start,
        )
        .all()
    )
    for created_at, amount in trend_rows:
        bucket_key = f"{created_at.year:04d}-{created_at.month:02d}"
        if bucket_key in month_totals:
            month_totals[bucket_key] += float(amount)

    revenue_by_month = [
        RevenueMonthPoint(
            month=bucket_key,
            month_label=f"{_MONTH_ABBR[int(bucket_key[5:7])]} {bucket_key[:4]}",
            amount=round(total, 2),
        )
        for bucket_key, total in month_totals.items()
    ]

    # ---- plan_mix: current ACTIVE subscriptions grouped by plan, computed
    # in Python (row volume is small - one dashboard's worth of active
    # subscriptions) rather than a SQL GROUP BY, for the same portability
    # reason as revenue_by_month. ----
    active_subs_for_mix = (
        db.query(Subscription)
        .options(joinedload(Subscription.plan))
        .filter(Subscription.application_id == application.id, Subscription.status == SubscriptionStatus.ACTIVE.value)
        .all()
    )
    plan_counts: "OrderedDict[str, dict]" = OrderedDict()
    for sub in active_subs_for_mix:
        plan_key = sub.plan.plan_code
        if plan_key not in plan_counts:
            plan_counts[plan_key] = {"plan_code": sub.plan.plan_code, "plan_name": sub.plan.name, "count": 0}
        plan_counts[plan_key]["count"] += 1

    total_active_for_mix = len(active_subs_for_mix)
    plan_mix = [
        PlanMixItem(
            plan_code=item["plan_code"],
            plan_name=item["plan_name"],
            count=item["count"],
            percentage=round(item["count"] / total_active_for_mix * 100, 1) if total_active_for_mix else 0.0,
        )
        for item in sorted(plan_counts.values(), key=lambda entry: entry["count"], reverse=True)
    ]

    # ---- recent_subscriptions: last _RECENT_SUBSCRIPTIONS_LIMIT subscriptions
    # (any status), with the latest payment transaction per subscription
    # batch-looked-up (one extra query, not one per row). ----
    recent_subs_rows = (
        db.query(Subscription)
        .options(joinedload(Subscription.customer), joinedload(Subscription.plan))
        .filter(Subscription.application_id == application.id)
        .order_by(Subscription.created_at.desc())
        .limit(_RECENT_SUBSCRIPTIONS_LIMIT)
        .all()
    )

    latest_payment_by_subscription_id: dict[int, PaymentTransaction] = {}
    recent_sub_ids = [sub.id for sub in recent_subs_rows]
    if recent_sub_ids:
        payment_rows = (
            db.query(PaymentTransaction)
            .filter(PaymentTransaction.subscription_id.in_(recent_sub_ids))
            .order_by(PaymentTransaction.subscription_id, PaymentTransaction.created_at.desc())
            .all()
        )
        for payment in payment_rows:
            # Rows arrive ordered by (subscription_id, created_at DESC), so
            # the first one seen per subscription_id is its latest payment.
            latest_payment_by_subscription_id.setdefault(payment.subscription_id, payment)

    recent_subscriptions = [
        RecentSubscriptionItem(
            subscription_id=sub.subscription_id,
            customer_id=sub.customer.customer_id,
            customer_email=sub.customer.email,
            plan_name=sub.plan.name,
            status=sub.status,
            amount=(
                float(latest_payment_by_subscription_id[sub.id].amount)
                if sub.id in latest_payment_by_subscription_id
                else None
            ),
            currency=(
                latest_payment_by_subscription_id[sub.id].currency
                if sub.id in latest_payment_by_subscription_id
                else application.currency
            ),
            created_at=sub.created_at,
        )
        for sub in recent_subs_rows
    ]

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
        new_subscriptions_30d_prev=new_subscriptions_30d_prev,
        revenue_30d_prev=float(revenue_30d_prev),
        failed_payments_30d_prev=failed_payments_30d_prev,
        revenue_by_month=revenue_by_month,
        plan_mix=plan_mix,
        recent_subscriptions=recent_subscriptions,
    )
