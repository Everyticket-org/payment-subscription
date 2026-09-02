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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.applications.models import Application
from app.core.enums import ProvisioningStatus, SubscriptionEventType, SubscriptionStatus
from app.core.exceptions import (
    CustomerAlreadySubscribed,
    InvalidPlanTransition,
    PlanNotFound,
    TrialAlreadyUsed,
)
from app.core.ids import new_subscription_id
from app.core.time import ensure_aware
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


def assert_trial_not_already_used(db: Session, *, customer_id: int, application_id: int) -> None:
    """"One credentials can take only one trial lifetime" (spec follow-up):
    checked regardless of that prior trial subscription's current status -
    PENDING_PAYMENT/ACTIVE/EXPIRED/CANCELLED all count, so a customer can't
    get a second trial just by letting the first one expire or cancelling
    it. This is the application-level pre-check; the real guarantee against
    a race between two concurrent trial-signup requests for the same
    customer is the DB-level partial unique index
    (uq_one_trial_subscription_per_customer_application on
    subscriptions(customer_id, application_id) WHERE is_trial), backed up
    by the IntegrityError catch in create_pending_subscription() below."""
    prior_trial = (
        db.query(Subscription.id)
        .filter(
            Subscription.customer_id == customer_id,
            Subscription.application_id == application_id,
            Subscription.is_trial.is_(True),
        )
        .first()
    )
    if prior_trial is not None:
        raise TrialAlreadyUsed("This customer has already used their free trial for this application")


def create_pending_subscription(
    db: Session, *, customer: Customer, application: Application, plan: Plan
) -> Subscription:
    """
    New subscription flow (spec section 19), up to and including
    PENDING_PAYMENT + payment transaction creation (payment transaction is
    created by PaymentService, not here).

    Refuses (CustomerAlreadySubscribed) if the customer already has an
    ACTIVE subscription for this application - upgrade/downgrade go
    through apply_plan_change() via the dedicated
    /customer/subscriptions/{id}/upgrade|downgrade endpoints instead, not
    through here.

    For a trial plan (plan.is_trial), also refuses (TrialAlreadyUsed) if
    this customer has ever had a trial subscription for this application
    before - belt and suspenders: a pre-check here, PLUS an IntegrityError
    catch around the flush translating a lost race (two concurrent trial
    signups) into the same clean 409 rather than a raw DB error. Scoped to
    the is_trial branch only, so the far more common non-trial path is
    unaffected.
    """
    if plan.application_id != application.id:
        raise PlanNotFound(f"Plan {plan.plan_code} does not belong to application {application.code}")

    existing_active = get_active_subscription(db, customer_id=customer.id, application_id=application.id)
    if existing_active is not None:
        raise CustomerAlreadySubscribed(
            f"Customer {customer.customer_id} already has an active subscription "
            f"({existing_active.subscription_id}) for {application.code}"
        )

    if plan.is_trial:
        assert_trial_not_already_used(db, customer_id=customer.id, application_id=application.id)

    subscription = Subscription(
        subscription_id=new_subscription_id(),
        customer_id=customer.id,
        application_id=application.id,
        plan_id=plan.id,
        status=SubscriptionStatus.PENDING_PAYMENT.value,
        provisioning_status=ProvisioningStatus.NOT_STARTED.value,
        is_trial=plan.is_trial,
    )
    db.add(subscription)

    if plan.is_trial:
        # SAVEPOINT, not a full db.rollback(): a lost race here must only
        # discard this one insert, not any other not-yet-committed work the
        # caller's outer transaction may already hold (e.g. a newly created
        # Customer row earlier in the same /public/subscribe request).
        try:
            with db.begin_nested():
                db.flush()
        except IntegrityError:
            db.expunge(subscription)
            raise TrialAlreadyUsed(
                "This customer has already used their free trial for this application"
            )
    else:
        db.flush()
    return subscription


def _billing_period_end(start: datetime, plan: Plan) -> datetime:
    if plan.is_trial:
        # Trial billing period is day-based off the plan's configurable
        # trial_period_days, not the month/year billing_interval used by
        # paid plans (spec follow-up: free trial as its own distinct,
        # configurable-duration plan).
        days = plan.trial_period_days or 0
    elif plan.billing_interval == "year":
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


def assert_transition_allowed(db: Session, *, from_plan: Plan, to_plan: Plan) -> str:
    """Spec section 16 originally required every plan-to-plan transition to
    be an explicit admin-configured allow-list entry (the PlanTransition
    table/admin CRUD still exist, unused by this function now). Per
    Vishal's own request (admin panel changes, 2026-09: "Plan transitions
    are not required for now as we are giving dropdown to user for
    change plan") this now auto-determines UPGRADE vs DOWNGRADE purely
    from the two plans' prices, so any plan can be switched to any other
    plan without an admin having to pre-configure every pair - matching
    the customer portal's own dropdown, which already offers every other
    active plan as a target. `db` is kept in the signature only for
    interface stability (both call sites already have a session in
    scope); nothing here queries it any more.
    """
    if from_plan.id == to_plan.id:
        raise InvalidPlanTransition(f"{to_plan.plan_code} is already the current plan")
    return "UPGRADE" if to_plan.price > from_plan.price else "DOWNGRADE"


def apply_plan_change(
    db: Session, *, subscription: Subscription, new_plan: Plan, event_type: str
) -> Subscription:
    """
    Payment SUCCESS on an UPGRADE/DOWNGRADE transaction (spec section 42):
    immediate plan swap, no proration, no refund. The new payment was
    already taken at the target plan's full price, so this also resets
    the billing period to a fresh cycle starting now - the same as a new
    purchase would.

    Idempotent the same way activate_subscription() is: if the
    subscription is already on new_plan, this is a no-op (duplicate
    callback safety, spec section 28).
    """
    if subscription.plan_id == new_plan.id:
        return subscription

    old_plan_id = subscription.plan_id
    now = datetime.now(timezone.utc)
    subscription.plan_id = new_plan.id
    subscription.status = SubscriptionStatus.ACTIVE.value
    subscription.starts_at = now
    subscription.expires_at = _billing_period_end(now, new_plan)
    db.add(subscription)

    db.add(
        SubscriptionHistory(
            subscription_id=subscription.id,
            event_type=event_type,
            from_plan_id=old_plan_id,
            to_plan_id=new_plan.id,
            occurred_at=now,
        )
    )
    db.flush()
    return subscription


def renew_subscription(db: Session, *, subscription: Subscription) -> Subscription:
    """Payment SUCCESS on a RENEWAL transaction (spec section 38): extends
    expires_at by one more billing period on the *current* plan. Extends
    from the later of (now, current expires_at) so renewing early doesn't
    lose the remaining paid-for time."""
    now = datetime.now(timezone.utc)
    current_expiry = ensure_aware(subscription.expires_at) if subscription.expires_at else None
    base = current_expiry if current_expiry and current_expiry > now else now
    subscription.status = SubscriptionStatus.ACTIVE.value
    subscription.expires_at = _billing_period_end(base, subscription.plan)
    db.add(subscription)

    db.add(
        SubscriptionHistory(
            subscription_id=subscription.id,
            event_type=SubscriptionEventType.RENEWED.value,
            to_plan_id=subscription.plan_id,
            occurred_at=now,
        )
    )
    db.flush()
    return subscription


def expire_subscription(db: Session, *, subscription: Subscription) -> Subscription:
    """ACTIVE -> EXPIRED (spec section 40). Intended to be driven by a
    Celery beat task once background jobs are wired up (see
    docs/implementation-status.md) - the function is ready for that, it
    just isn't scheduled anywhere yet."""
    if subscription.status != SubscriptionStatus.ACTIVE.value:
        return subscription

    now = datetime.now(timezone.utc)
    subscription.status = SubscriptionStatus.EXPIRED.value
    db.add(subscription)

    db.add(
        SubscriptionHistory(
            subscription_id=subscription.id,
            event_type=SubscriptionEventType.EXPIRED.value,
            occurred_at=now,
        )
    )
    db.flush()
    return subscription


def expire_due_subscriptions(db: Session) -> int:
    """Sweep entry point for the Celery beat task (app/subscriptions/tasks.py,
    spec section 40) - unlike expire_subscription() above (which the
    caller commits), this owns its own commits since nothing else is
    driving the same transaction. Also queues a subscription.expired
    webhook event per expired subscription (spec sections 19, 31),
    same DB-only queue_event() pattern PaymentService uses, via
    app.webhooks.payloads.expiry_payload (2026-09 follow-up: "second
    [webhook] for making status inactive when plan expires"; trimmed to
    just subscription_id in follow-up 3). Returns how many subscriptions
    were expired."""
    from app.webhooks import service as webhook_service  # local import: avoids a module-load cycle
    from app.webhooks.payloads import expiry_payload

    now = datetime.now(timezone.utc)
    due = (
        db.query(Subscription)
        .filter(
            Subscription.status == SubscriptionStatus.ACTIVE.value,
            Subscription.expires_at.isnot(None),
            Subscription.expires_at <= now,
        )
        .all()
    )
    expired_count = 0
    for subscription in due:
        expire_subscription(db, subscription=subscription)
        application = db.get(Application, subscription.application_id)
        if application is not None:
            webhook_service.queue_event(
                db,
                application=application,
                event_type="subscription.expired",
                entity_type="subscription",
                entity_id=subscription.subscription_id,
                payload=expiry_payload(subscription_id=subscription.subscription_id),
            )
        db.commit()
        expired_count += 1
    return expired_count


def archive_stale_subscriptions(db: Session) -> int:
    """Sweep entry point for the Celery beat task (app/subscriptions/tasks.py).
    EXPIRED -> ARCHIVED once an application's admin-configured
    archive_after_days has elapsed since the subscription expired
    (2026-09 follow-up: "third [webhook] to delete/archive when user do
    not renew for x days"; payload trimmed to just subscription_id in
    follow-up 3) - opt-in per application: archive_after_days
    None or <= 0 means this application never archives, matching every
    other admin-configurable threshold in this app (e.g. webhook_retry_limit).

    Uses SubscriptionHistory's own EXPIRED row's occurred_at as "when it
    expired" rather than re-deriving it from expires_at, since a
    subscription can only reach EXPIRED via expire_subscription() above,
    which always writes that history row at the same moment - the two
    are equivalent, but the history row is the actual audit trail this
    app already keeps for exactly this purpose. Returns how many
    subscriptions were archived."""
    from app.subscriptions.models import SubscriptionHistory
    from app.webhooks import service as webhook_service  # local import: avoids a module-load cycle
    from app.webhooks.payloads import archive_payload

    now = datetime.now(timezone.utc)
    candidates = (
        db.query(Subscription)
        .join(Application, Subscription.application_id == Application.id)
        .filter(
            Subscription.status == SubscriptionStatus.EXPIRED.value,
            Application.archive_after_days.isnot(None),
            Application.archive_after_days > 0,
        )
        .all()
    )
    archived_count = 0
    for subscription in candidates:
        application = db.get(Application, subscription.application_id)
        if application is None or not application.archive_after_days:
            continue

        expired_history = (
            db.query(SubscriptionHistory)
            .filter(
                SubscriptionHistory.subscription_id == subscription.id,
                SubscriptionHistory.event_type == SubscriptionEventType.EXPIRED.value,
            )
            .order_by(SubscriptionHistory.occurred_at.desc())
            .first()
        )
        expired_at = ensure_aware(expired_history.occurred_at) if expired_history else None
        if expired_at is None:
            continue
        days_since_expiry = (now - expired_at).days
        if days_since_expiry < application.archive_after_days:
            continue

        subscription.status = SubscriptionStatus.ARCHIVED.value
        db.add(subscription)
        db.add(
            SubscriptionHistory(
                subscription_id=subscription.id,
                event_type=SubscriptionEventType.ARCHIVED.value,
                occurred_at=now,
            )
        )

        webhook_service.queue_event(
            db,
            application=application,
            event_type="subscription.archived",
            entity_type="subscription",
            entity_id=subscription.subscription_id,
            payload=archive_payload(subscription_id=subscription.subscription_id),
        )
        db.commit()
        archived_count += 1
    return archived_count


def send_renewal_reminders(db: Session) -> int:
    """Sweep entry point for the Celery beat task (app/subscriptions/tasks.py,
    spec section 49) - emails every ACTIVE subscription expiring within
    RENEWAL_REMINDER_DAYS_BEFORE days. A trial subscription (plan.is_trial)
    gets the 'trial_ending' template instead of 'renewal_reminder' (spec
    follow-up: "before trial over - email to renew") - same sweep, same
    RENEWAL_REMINDER_DAYS_BEFORE window, just a different template_code, so
    trial customers get a nudge before their trial's day-based expiry the
    same way paid customers do before a billing-cycle expiry. Idempotency
    is a heuristic rather than a dedicated column: it skips a subscription
    if a NotificationLog for the relevant template already exists for it
    within a window wide enough to cover the current expiry cycle - good
    enough to avoid spamming the same reminder every few minutes without
    adding new schema for this pass (see docs/implementation-status.md)."""
    from app.core.config import get_settings
    from app.notifications.email import service as email_service
    from app.notifications.models import NotificationLog

    settings = get_settings()
    now = datetime.now(timezone.utc)
    window_end = now + timedelta(days=settings.RENEWAL_REMINDER_DAYS_BEFORE)

    due = (
        db.query(Subscription)
        .filter(
            Subscription.status == SubscriptionStatus.ACTIVE.value,
            Subscription.expires_at.isnot(None),
            Subscription.expires_at > now,
            Subscription.expires_at <= window_end,
        )
        .all()
    )

    reminder_lookback = now - timedelta(days=settings.RENEWAL_REMINDER_DAYS_BEFORE + 2)
    sent_count = 0
    for subscription in due:
        template_code = "trial_ending" if subscription.plan.is_trial else "renewal_reminder"
        already_reminded = (
            db.query(NotificationLog)
            .filter(
                NotificationLog.template_code == template_code,
                NotificationLog.related_entity_id == subscription.subscription_id,
                NotificationLog.created_at >= reminder_lookback,
            )
            .first()
        )
        if already_reminded is not None:
            continue

        sent = email_service.send_templated_email(
            db,
            template_code=template_code,
            to=subscription.customer.email,
            context={
                "plan_name": subscription.plan.name,
                "expires_at": subscription.expires_at.date().isoformat(),
            },
            related_entity_type="subscription",
            related_entity_id=subscription.subscription_id,
            application=db.get(Application, subscription.application_id),
        )
        if sent:
            sent_count += 1
    return sent_count


def cancel_subscription(
    db: Session, *, subscription: Subscription, cancelled_by: str, reason: str | None, application: Application | None = None
) -> Subscription:
    """Immediate cancellation (spec section 43): no refund, no future
    renewal. Also queues a subscription.cancelled webhook (2026-09
    follow-up 3: "Add one more webhook for renew" - Vishal's full list
    was Renew/Expire/Cancel/Archived, all payload-trimmed to just
    subscription_id) - application is optional only so this still works
    for any pre-existing caller that hasn't been updated to pass it;
    both real call sites (app.api.v1.customer, app.api.v1.admin_testing)
    already have the application in scope and pass it."""
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

    if application is not None:
        from app.webhooks import service as webhook_service  # local import: avoids a module-load cycle
        from app.webhooks.payloads import cancelled_payload

        webhook_service.queue_event(
            db,
            application=application,
            event_type="subscription.cancelled",
            entity_type="subscription",
            entity_id=subscription.subscription_id,
            payload=cancelled_payload(subscription_id=subscription.subscription_id),
        )

    return subscription
