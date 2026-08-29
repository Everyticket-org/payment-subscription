"""Admin Subscriptions (spec sections 51, 53) - read-only list/detail plus
the append-only history trail. No mutation endpoints: subscription state
transitions always go through app.subscriptions.service, driven by real
payment events or the (separate, not-yet-built) Testing module - never a
direct admin edit, per spec section 53's "do not allow unsafe editing"."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_db
from app.api.v1.admin_common import DEFAULT_LIMIT, MAX_LIMIT, PageOut, paginate
from app.api.v1.admin_serializers import to_subscription_admin_out
from app.auth.deps import require_permission
from app.auth.models import AdminUser
from app.core.exceptions import SubscriptionNotFound
from app.customers.models import Customer
from app.plans.models import Plan
from app.subscriptions.models import Subscription, SubscriptionHistory
from app.subscriptions.schemas import SubscriptionAdminOut, SubscriptionDetailAdminOut, SubscriptionHistoryOut

router = APIRouter(prefix="/subscriptions", tags=["admin-subscriptions"])


@router.get("", response_model=PageOut[SubscriptionAdminOut])
def list_subscriptions(
    status_filter: str | None = Query(default=None, alias="status"),
    plan_code: str | None = Query(default=None),
    customer_id: str | None = Query(default=None, description="Public CUS-xxxx id"),
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(require_permission("SUBSCRIPTIONS_VIEW")),
):
    query = db.query(Subscription).options(joinedload(Subscription.customer), joinedload(Subscription.plan))
    if status_filter:
        query = query.filter(Subscription.status == status_filter.upper())
    if plan_code:
        query = query.join(Subscription.plan).filter(Plan.plan_code == plan_code.upper())
    if customer_id:
        query = query.join(Subscription.customer).filter(Customer.customer_id == customer_id)
    query = query.order_by(Subscription.created_at.desc())

    items, total = paginate(query, limit=limit, offset=offset)
    return PageOut(items=[to_subscription_admin_out(s) for s in items], total=total, limit=limit, offset=offset)


@router.get("/{subscription_id}", response_model=SubscriptionDetailAdminOut)
def get_subscription(
    subscription_id: str,
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(require_permission("SUBSCRIPTIONS_VIEW")),
):
    subscription = db.query(Subscription).filter(Subscription.subscription_id == subscription_id).first()
    if subscription is None:
        raise SubscriptionNotFound(f"Unknown subscription {subscription_id}")

    history = (
        db.query(SubscriptionHistory)
        .filter(SubscriptionHistory.subscription_id == subscription.id)
        .order_by(SubscriptionHistory.occurred_at)
        .all()
    )
    return SubscriptionDetailAdminOut(
        subscription=to_subscription_admin_out(subscription),
        history=[SubscriptionHistoryOut.model_validate(h) for h in history],
    )
