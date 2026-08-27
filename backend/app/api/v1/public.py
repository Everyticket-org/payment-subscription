"""
Public subscription API (spec sections 17, 19, 61: /api/v1/public/).

No auth required - this is what a plan's public URL (/subscribe/{code})
drives. See app/customers/service.py and app/subscriptions/service.py
docstrings for the current limitations (duplicate detection / OTP not
wired in yet).
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_application, get_db
from app.applications.models import Application
from app.core.enums import PaymentType
from app.core.exceptions import PlanNotFound
from app.customers import service as customer_service
from app.customers.schemas import SubscribeRequest
from app.customers.models import CustomerRegistrationData
from app.payments import service as payment_service
from app.plans.models import Plan
from app.plans.schemas import PlanOut
from app.subscriptions import service as subscription_service
from app.subscriptions.schemas import SubscribeResponse

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/plans", response_model=list[PlanOut])
def list_plans(db: Session = Depends(get_db), application: Application = Depends(get_application)):
    plans = (
        db.query(Plan)
        .filter(Plan.application_id == application.id, Plan.active.is_(True))
        .order_by(Plan.display_order)
        .all()
    )
    return plans


@router.get("/plans/{plan_code}", response_model=PlanOut)
def get_plan(plan_code: str, db: Session = Depends(get_db), application: Application = Depends(get_application)):
    plan = (
        db.query(Plan)
        .filter(
            Plan.application_id == application.id,
            Plan.plan_code == plan_code.upper(),
            Plan.active.is_(True),
        )
        .first()
    )
    if plan is None:
        raise PlanNotFound(f"No active plan '{plan_code}'")
    return plan


@router.post("/plans/{plan_code}/subscribe", response_model=SubscribeResponse)
def subscribe(
    plan_code: str,
    body: SubscribeRequest,
    db: Session = Depends(get_db),
    application: Application = Depends(get_application),
):
    """New subscription flow (spec section 19) up through payment
    initiation. Payment SUCCESS/FAILED is reported separately, via the
    gateway callback endpoint (POST /api/v1/payment/mock/callback for the
    mock gateway) - never based on this response alone."""
    plan = (
        db.query(Plan)
        .filter(
            Plan.application_id == application.id,
            Plan.plan_code == plan_code.upper(),
            Plan.active.is_(True),
        )
        .first()
    )
    if plan is None:
        raise PlanNotFound(f"No active plan '{plan_code}'")

    customer = customer_service.get_or_create_customer(db, email=body.email, mobile=body.mobile)
    subscription = subscription_service.create_pending_subscription(
        db, customer=customer, application=application, plan=plan
    )

    if body.registration_data:
        db.add(
            CustomerRegistrationData(
                customer_id=customer.id,
                application_id=application.id,
                subscription_id=subscription.id,
                data=body.registration_data,
            )
        )

    payment = payment_service.create_payment_transaction(
        db,
        customer=customer,
        subscription=subscription,
        plan=plan,
        payment_type=PaymentType.NEW.value,
        gateway_code=application.default_gateway,
    )
    db.commit()
    db.refresh(customer)
    db.refresh(subscription)
    db.refresh(payment)

    return SubscribeResponse(customer=customer, subscription=subscription, payment=payment)
