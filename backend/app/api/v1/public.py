"""
Public subscription API (spec sections 9-11, 17, 19, 61: /api/v1/public/).

No auth required except where a customer bearer token (issued by
POST /otp/verify) is explicitly accepted. Flow for a RETURNING customer:

    POST /identify {email, mobile}
        -> match_status "exact"  -> otp_session_id issued, OTP "sent"
        -> match_status "conflict" -> 409, directs to manual support
        -> match_status "none"   -> caller proceeds straight to /subscribe
                                     with email+mobile in the body (no OTP
                                     needed for a genuinely new customer)
    POST /otp/verify {otp_session_id, code}
        -> returns a customer-scoped bearer token
    POST /plans/{code}/subscribe  (Authorization: Bearer <token>)
        -> identifies the customer from the token instead of the body;
           create_pending_subscription() then routes SAME/HIGHER/LOWER
           plan-while-ACTIVE to a 409 (use the dedicated
           upgrade/downgrade endpoints instead), or creates a fresh
           PENDING_PAYMENT subscription for EXPIRED/CANCELLED/no-existing-
           subscription cases (repurchase, spec section 41 - reuses the
           same customer_id).

A brand-new customer (POST /identify said "none") may skip straight to
/subscribe with email+mobile in the body - no OTP required, since there is
no existing account to protect (spec section 9's "NO_EXISTING_CUSTOMER"
case). If a client calls /subscribe with email+mobile that DO match an
existing account without going through /identify + OTP first, the backend
itself refuses (OTP_VERIFICATION_REQUIRED) rather than silently
identifying them - the OTP gate is enforced server-side, not just by
frontend convention.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_application, get_db
from app.applications.models import Application
from app.auth import otp_service
from app.auth.deps import get_current_customer_id_optional
from app.core.config import get_settings
from app.core.enums import PaymentType
from app.core.exceptions import ConflictingCustomerIdentity, OtpVerificationRequired, PlanNotFound, Unauthorized
from app.customers import service as customer_service
from app.customers.models import Customer, CustomerRegistrationData
from app.notifications.email import service as email_service
from app.customers.schemas import (
    CustomerOut,
    IdentifyRequest,
    IdentifyResponse,
    OtpVerifyRequest,
    OtpVerifyResponse,
    SubscribeRequest,
)
from app.payments import service as payment_service
from app.plans.models import Plan
from app.plans.schemas import PlanOut
from app.subscriptions import service as subscription_service
from app.subscriptions.schemas import SubscribeResponse

router = APIRouter(prefix="/public", tags=["public"])
settings = get_settings()


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


@router.post("/identify", response_model=IdentifyResponse)
def identify(body: IdentifyRequest, db: Session = Depends(get_db)):
    """Spec section 9: call this before registration so a returning
    customer doesn't accidentally create a duplicate account/subscription."""
    match_status, existing = customer_service.find_match_status(db, email=body.email, mobile=body.mobile)

    if match_status == "none":
        return IdentifyResponse(match_status="none", message="No existing account found - proceed to registration.")

    if match_status == "conflict":
        return IdentifyResponse(
            match_status="conflict",
            message="Email and mobile match different existing accounts. Please contact support to resolve this.",
        )

    # match_status == "exact"
    otp_session, code = otp_service.create_otp_session(
        db, email=body.email, mobile=body.mobile, customer_id=existing.customer_id, purpose="IDENTIFY"
    )
    db.commit()

    # Real delivery (spec section 11) - best-effort, after the OTP
    # session itself is already committed so a broken SMTP server never
    # blocks issuing the session. debug_otp_code below is a TEST_MODE-only
    # convenience for local development, not the delivery mechanism.
    if body.email:
        email_service.send_templated_email(
            db,
            template_code="otp_verification",
            to=body.email,
            context={"code": code},
            related_entity_type="otp_session",
            related_entity_id=otp_session.otp_session_id,
        )

    return IdentifyResponse(
        match_status="exact",
        otp_session_id=otp_session.otp_session_id,
        debug_otp_code=code if settings.TEST_MODE else None,
        message="An account already exists. Enter the OTP sent to your email/mobile to continue.",
    )


@router.post("/otp/verify", response_model=OtpVerifyResponse)
def verify_otp(body: OtpVerifyRequest, db: Session = Depends(get_db)):
    session = otp_service.verify_otp(db, otp_session_id=body.otp_session_id, code=body.code)
    db.commit()

    if not session.customer_id:
        raise Unauthorized("OTP session is not linked to a customer")

    customer = db.query(Customer).filter(Customer.customer_id == session.customer_id).first()
    if customer is None:
        raise Unauthorized("Customer not found")

    token = customer_service.issue_customer_token(customer)
    return OtpVerifyResponse(customer=CustomerOut.model_validate(customer), access_token=token)


@router.post("/plans/{plan_code}/subscribe", response_model=SubscribeResponse)
def subscribe(
    plan_code: str,
    body: SubscribeRequest,
    db: Session = Depends(get_db),
    application: Application = Depends(get_application),
    customer_id_from_token: str | None = Depends(get_current_customer_id_optional),
):
    """New subscription / repurchase flow (spec sections 19, 41). Payment
    SUCCESS/FAILED is reported separately via the gateway callback
    endpoint - never based on this response alone."""
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

    if customer_id_from_token:
        customer = db.query(Customer).filter(Customer.customer_id == customer_id_from_token).first()
        if customer is None:
            raise Unauthorized("Invalid customer session")
    else:
        if not body.email or not body.mobile:
            raise HTTPException(status_code=422, detail="email and mobile are required when not authenticated")

        match_status, existing = customer_service.find_match_status(db, email=body.email, mobile=body.mobile)
        if match_status == "conflict":
            raise ConflictingCustomerIdentity(
                "Email and mobile match different existing accounts. Please contact support to resolve this."
            )
        if match_status == "exact":
            raise OtpVerificationRequired(
                "An account already exists for this email/mobile. "
                "Call POST /public/identify and verify via OTP before subscribing."
            )
        customer = customer_service.create_customer(db, email=body.email, mobile=body.mobile)

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

    return SubscribeResponse(
        customer=customer, subscription=subscription, payment=payment_service.build_payment_out(payment)
    )
