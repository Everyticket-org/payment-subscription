"""
Subscription lifecycle service (spec sections 19-22, 38-43, 58, 67).

State transitions always go through here (never set .status directly from
API code) so the one-active-subscription rule and history trail stay
consistent. All writes happen on the caller's session without an
intermediate commit - the caller (typically PaymentService, inside one DB
transaction per spec section 58) decides when to commit.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.applications.models import Application
from app.core.enums import ProvisioningStatus, SubscriptionEventType, SubscriptionStatus
from app.core.exceptions import CustomerAlreadySubscribed, PlanNotFound
from app.core.ids import new_subscription_id
from app.customers.models import Customer
from app.plans.models import Plan
from app.subscriptions.models import Subscription, SubscriptionHistory


def get_active_subscription(db: Session, *, customer_id: int, application_id: int) -> Subscription | None:
    return (
        db.query(Subscription)
        .filter(
            and_(
                Subscription.customer_id == customer_id,
                Subscription.application_id == application_id,
                Subscription.status == SubscriptionStatus.ACTIVE.value,
            )
        )
        .first()
    )


def create_pending_subscription(
    db: Session, *, customer: Customer, application: Application, plan: Plan
) -> Subscription:
    """
    New subscription flow (spec section 19), up to and including
    PENDING_PAYMENT + payment transaction creation (payment transaction is
    created by PaymentService, not here).

    LIMITATION: full SAME/HIGHER/LOWER/EXPIRED routing (spec section 9) is
    not implemented yet - if the customer already has an ACTIVE
    subscription for this application, this simply refuses (
    CustomerAlreadySubscribed) rather than routing to upgrade/downgrade.
    Upgrade/downgrade as first-class operations are a follow-up (see
    docs/implementation-status.md).
    """
    if plan.application_id != application.id:
        raise PlanNotFound(f"Plan {plan.plan_code} does not belong to application {application.code}")

    existing_active = get_active_subscription(db, customer_id=customer.id, application_id=application.id)
    if existing_active is not None:
        raise CustomerAlreadySubscribed(
            f"Customer {customer.customer_id} already has an active subscription "
            f"({existing_active.subscription_id}) for {application.code}"
        )

    subscription = Subscription(
        subscription_id=new_subscription_id(),
        customer_id=customer.id,
        application_id=application.id,
        plan_id=plan.id,
        status=SubscriptionStatus.PENDING_PAYMENT.value,
        provisioning_status=ProvisioningStatus.NOT_STARTED.value,
    )
    db.add(subscription)
    db.flush()
    return subscription


def _billing_period_end(start: datetime, plan: Plan) -> datetime:
    if plan.billing_interval == "year":
        days = 365 * plan.billing_frequency
    else:
        days = 30 * plan.billing_frequency
    return start + timedelta(days=days)


def activate_subscription(db: Session, *, subscription: Subscription) -> Subscription:
    """Payment SUCCESS -> subscription ACTIVE (spec section 19). Idempotent:
    calling this twice on an already-ACTIVE subscription is a no-op, which
    matters because PaymentService's duplicate-callback guard calls this
    path defensively."""
    if subscription.status == SubscriptionStatus.ACTIVE.value:
        return subscription

    now = datetime.now(timezone.utc)
    subscription.status = SubscriptionStatus.ACTIVE.value
    subscription.starts_at = now
    subscription.expires_at = _billing_period_end(now, subscription.plan)
    db.add(subscription)

    db.add(
        SubscriptionHistory(
            subscription_id=subscription.id,
            event_type=SubscriptionEventType.ACTIVATED.value,
            to_plan_id=subscription.plan_id,
            occurred_at=now,
        )
    )
    db.flush()
    return subscription


def mark_payment_failed(db: Session, *, subscription: Subscription) -> Subscription:
    """Payment FAILED on a still-pending subscription -> PAYMENT_FAILED
    (spec section 20). Never called on an already-ACTIVE subscription - a
    failed renewal/upgrade payment must not deactivate a currently active
    plan (spec section 42: 'if payment fails, existing plan remains
    active')."""
    if subscription.status != SubscriptionStatus.PENDING_PAYMENT.value:
        return subscription

    subscription.status = SubscriptionStatus.PAYMENT_FAILED.value
    db.add(subscription)

    db.add(
        SubscriptionHistory(
            subscription_id=subscription.id,
            event_type=SubscriptionEventType.PAYMENT_FAILED.value,
            occurred_at=datetime.now(timezone.utc),
        )
    )
    db.flush()
    return subscription


def cancel_subscription(db: Session, *, subscription: Subscription, cancelled_by: str, reason: str | None) -> Subscription:
    """Immediate cancellation (spec section 43): no refund, no future renewal."""
    now = datetime.now(timezone.utc)
    subscription.status = SubscriptionStatus.CANCELLED.value
    subscription.cancelled_at = now
    subscription.cancelled_by = cancelled_by
    subscription.cancellation_reason = reason
    db.add(subscription)

    db.add(
        SubscriptionHistory(
            subscription_id=subscription.id,
            event_type=SubscriptionEventType.CANCELLED.value,
            occurred_at=now,
            event_metadata={"cancelled_by": cancelled_by, "reason": reason},
        )
    )
    db.flush()
    return subscription
