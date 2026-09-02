"""
Admin Plans / Plan Features / Plan Transitions (spec sections 14-16, 51).

Every mutating endpoint here requires PLANS_MANAGE and writes an audit log
entry (spec section 56). Plans are never hard-deleted - they may already
be referenced by live subscriptions/payment history via FK, so the only
"removal" operation is deactivate (active=False), which just hides a plan
from the public catalog (app.api.v1.public already filters on Plan.active).
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_application, get_db
from app.applications.models import Application
from app.audit import service as audit_service
from app.auth.deps import require_permission
from app.auth.models import AdminUser
from app.core.exceptions import AppError, InvalidPlanConfiguration
from app.plans.models import Plan, PlanFeature, PlanTransition
from app.plans.sanitize import sanitize_description
from app.plans.schemas import (
    PlanAdminOut,
    PlanCreate,
    PlanFeatureAdminOut,
    PlanFeatureCreate,
    PlanFeatureUpdate,
    PlanReorderRequest,
    PlanTransitionCreate,
    PlanTransitionOut,
    PlanUpdate,
)

router = APIRouter(prefix="/plans", tags=["admin-plans"])


class PlanNotFoundError(AppError):
    http_status = 404
    error_code = "PLAN_NOT_FOUND"


class PlanCodeInUse(AppError):
    http_status = 409
    error_code = "PLAN_CODE_IN_USE"


class PlanFeatureNotFoundError(AppError):
    http_status = 404
    error_code = "PLAN_FEATURE_NOT_FOUND"


class PlanTransitionNotFoundError(AppError):
    http_status = 404
    error_code = "PLAN_TRANSITION_NOT_FOUND"


def _get_plan(db: Session, *, application: Application, plan_code: str) -> Plan:
    plan = (
        db.query(Plan)
        .filter(Plan.application_id == application.id, Plan.plan_code == plan_code.upper())
        .first()
    )
    if plan is None:
        raise PlanNotFoundError(f"Unknown plan '{plan_code}'")
    return plan


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _validate_trial_configuration(*, is_trial: bool, price: float, trial_period_days: int | None) -> None:
    """Cross-field validation for a plan's trial configuration (free trial
    is its own distinct, configurable-duration plan - spec follow-up).
    Called with the FULL body on create, and with the MERGED effective
    state (existing plan values overridden by whatever fields a partial
    PUT actually supplied) on update, so a PUT that only touches one of
    these three fields can never leave the plan in an inconsistent state
    (e.g. is_trial=True with price left at some old non-zero value)."""
    if is_trial:
        if not trial_period_days or trial_period_days <= 0:
            raise InvalidPlanConfiguration("A trial plan requires trial_period_days > 0")
        if price != 0:
            raise InvalidPlanConfiguration("A trial plan must be priced at 0")
    else:
        if price <= 0:
            raise InvalidPlanConfiguration("A non-trial plan requires price > 0")


@router.get("", response_model=list[PlanAdminOut])
def list_plans(
    db: Session = Depends(get_db),
    application: Application = Depends(get_application),
    _admin: AdminUser = Depends(require_permission("PLANS_MANAGE")),
):
    plans = (
        db.query(Plan)
        .filter(Plan.application_id == application.id)
        .order_by(Plan.display_order)
        .all()
    )
    return [PlanAdminOut.model_validate(p) for p in plans]


@router.post("", response_model=PlanAdminOut, status_code=201)
def create_plan(
    body: PlanCreate,
    request: Request,
    db: Session = Depends(get_db),
    application: Application = Depends(get_application),
    admin: AdminUser = Depends(require_permission("PLANS_MANAGE")),
):
    existing = (
        db.query(Plan)
        .filter(Plan.application_id == application.id, Plan.plan_code == body.plan_code.upper())
        .first()
    )
    if existing is not None:
        raise PlanCodeInUse(f"Plan code '{body.plan_code}' already exists")

    _validate_trial_configuration(is_trial=body.is_trial, price=body.price, trial_period_days=body.trial_period_days)

    plan = Plan(
        application_id=application.id,
        plan_code=body.plan_code.upper(),
        name=body.name,
        description=sanitize_description(body.description),
        price=body.price,
        currency=body.currency,
        billing_interval=body.billing_interval,
        billing_frequency=body.billing_frequency,
        display_order=body.display_order,
        active=True,
        is_trial=body.is_trial,
        trial_period_days=body.trial_period_days,
    )
    db.add(plan)
    db.flush()

    audit_service.record(
        db,
        actor=admin.email,
        action="PLAN_CREATED",
        entity_type="plan",
        entity_id=plan.plan_code,
        new_value=body.model_dump(),
        ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(plan)
    return PlanAdminOut.model_validate(plan)


@router.put("/reorder", response_model=list[PlanAdminOut])
def reorder_plans(
    body: PlanReorderRequest,
    request: Request,
    db: Session = Depends(get_db),
    application: Application = Depends(get_application),
    admin: AdminUser = Depends(require_permission("PLANS_MANAGE")),
):
    """Registered before /{plan_code} (same reason as /transitions below)
    so "reorder" is never matched as a plan_code path param. Sets
    display_order = index in the given list for every plan named - the
    request must name every one of this application's plans (not just a
    changed subset) so a stale/partial client can't silently strand some
    plans at their old display_order relative to the rest."""
    plans_by_code = {
        p.plan_code: p
        for p in db.query(Plan).filter(Plan.application_id == application.id).all()
    }
    requested_codes = [code.upper() for code in body.plan_codes]

    unknown = [code for code in requested_codes if code not in plans_by_code]
    if unknown:
        raise PlanNotFoundError(f"Unknown plan code(s): {', '.join(unknown)}")
    if set(requested_codes) != set(plans_by_code.keys()):
        missing = set(plans_by_code.keys()) - set(requested_codes)
        raise PlanNotFoundError(
            f"Reorder must include every plan for this application - missing: {', '.join(sorted(missing))}"
        )

    old_value = {code: plan.display_order for code, plan in plans_by_code.items()}
    for index, code in enumerate(requested_codes):
        plans_by_code[code].display_order = index
        db.add(plans_by_code[code])
    db.flush()

    audit_service.record(
        db,
        actor=admin.email,
        action="PLANS_REORDERED",
        entity_type="plan",
        entity_id=application.code,
        old_value=old_value,
        new_value={code: index for index, code in enumerate(requested_codes)},
        ip_address=_client_ip(request),
    )
    db.commit()

    plans = (
        db.query(Plan)
        .filter(Plan.application_id == application.id)
        .order_by(Plan.display_order)
        .all()
    )
    return [PlanAdminOut.model_validate(p) for p in plans]


@router.get("/transitions", response_model=list[PlanTransitionOut])
def list_transitions(
    db: Session = Depends(get_db),
    application: Application = Depends(get_application),
    _admin: AdminUser = Depends(require_permission("PLANS_MANAGE")),
):
    transitions = db.query(PlanTransition).filter(PlanTransition.application_id == application.id).all()
    return [
        PlanTransitionOut(
            id=t.id, from_plan_code=t.from_plan.plan_code, to_plan_code=t.to_plan.plan_code, transition_type=t.transition_type
        )
        for t in transitions
    ]


@router.post("/transitions", response_model=PlanTransitionOut, status_code=201)
def create_transition(
    body: PlanTransitionCreate,
    request: Request,
    db: Session = Depends(get_db),
    application: Application = Depends(get_application),
    admin: AdminUser = Depends(require_permission("PLANS_MANAGE")),
):
    from_plan = _get_plan(db, application=application, plan_code=body.from_plan_code)
    to_plan = _get_plan(db, application=application, plan_code=body.to_plan_code)

    existing = (
        db.query(PlanTransition)
        .filter(PlanTransition.from_plan_id == from_plan.id, PlanTransition.to_plan_id == to_plan.id)
        .first()
    )
    if existing is not None:
        raise PlanCodeInUse(f"Transition {body.from_plan_code} -> {body.to_plan_code} already exists")

    transition = PlanTransition(
        application_id=application.id,
        from_plan_id=from_plan.id,
        to_plan_id=to_plan.id,
        transition_type=body.transition_type,
    )
    db.add(transition)
    db.flush()

    audit_service.record(
        db,
        actor=admin.email,
        action="PLAN_TRANSITION_CREATED",
        entity_type="plan_transition",
        entity_id=str(transition.id),
        new_value=body.model_dump(),
        ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(transition)
    return PlanTransitionOut(
        id=transition.id, from_plan_code=from_plan.plan_code, to_plan_code=to_plan.plan_code, transition_type=transition.transition_type
    )


@router.delete("/transitions/{transition_id}", status_code=204)
def delete_transition(
    transition_id: int,
    request: Request,
    db: Session = Depends(get_db),
    application: Application = Depends(get_application),
    admin: AdminUser = Depends(require_permission("PLANS_MANAGE")),
):
    transition = (
        db.query(PlanTransition)
        .filter(PlanTransition.id == transition_id, PlanTransition.application_id == application.id)
        .first()
    )
    if transition is None:
        raise PlanTransitionNotFoundError(f"Unknown plan transition {transition_id}")

    old_value = {
        "from_plan_code": transition.from_plan.plan_code,
        "to_plan_code": transition.to_plan.plan_code,
        "transition_type": transition.transition_type,
    }
    db.delete(transition)
    audit_service.record(
        db,
        actor=admin.email,
        action="PLAN_TRANSITION_DELETED",
        entity_type="plan_transition",
        entity_id=str(transition_id),
        old_value=old_value,
        ip_address=_client_ip(request),
    )
    db.commit()
    return None


@router.get("/{plan_code}", response_model=PlanAdminOut)
def get_plan(
    plan_code: str,
    db: Session = Depends(get_db),
    application: Application = Depends(get_application),
    _admin: AdminUser = Depends(require_permission("PLANS_MANAGE")),
):
    plan = _get_plan(db, application=application, plan_code=plan_code)
    return PlanAdminOut.model_validate(plan)


@router.put("/{plan_code}", response_model=PlanAdminOut)
def update_plan(
    plan_code: str,
    body: PlanUpdate,
    request: Request,
    db: Session = Depends(get_db),
    application: Application = Depends(get_application),
    admin: AdminUser = Depends(require_permission("PLANS_MANAGE")),
):
    plan = _get_plan(db, application=application, plan_code=plan_code)
    old_value = PlanAdminOut.model_validate(plan).model_dump(exclude={"features"})

    updates = body.model_dump(exclude_unset=True)
    if "description" in updates:
        updates["description"] = sanitize_description(updates["description"])

    effective_is_trial = updates.get("is_trial", plan.is_trial)
    effective_price = updates.get("price", float(plan.price))
    effective_trial_period_days = updates.get("trial_period_days", plan.trial_period_days)
    _validate_trial_configuration(
        is_trial=effective_is_trial, price=float(effective_price), trial_period_days=effective_trial_period_days
    )

    for field, value in updates.items():
        setattr(plan, field, value)
    db.add(plan)
    db.flush()

    audit_service.record(
        db,
        actor=admin.email,
        action="PLAN_UPDATED",
        entity_type="plan",
        entity_id=plan.plan_code,
        old_value=old_value,
        new_value=updates,
        ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(plan)
    return PlanAdminOut.model_validate(plan)


@router.post("/{plan_code}/features", response_model=PlanFeatureAdminOut, status_code=201)
def add_feature(
    plan_code: str,
    body: PlanFeatureCreate,
    request: Request,
    db: Session = Depends(get_db),
    application: Application = Depends(get_application),
    admin: AdminUser = Depends(require_permission("PLANS_MANAGE")),
):
    plan = _get_plan(db, application=application, plan_code=plan_code)
    feature = PlanFeature(
        plan_id=plan.id,
        feature_key=body.feature_key,
        feature_label=body.feature_label,
        feature_value=body.feature_value,
        display_order=body.display_order,
    )
    db.add(feature)
    db.flush()

    audit_service.record(
        db,
        actor=admin.email,
        action="PLAN_FEATURE_CREATED",
        entity_type="plan_feature",
        entity_id=str(feature.id),
        new_value={"plan_code": plan.plan_code, **body.model_dump()},
        ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(feature)
    return PlanFeatureAdminOut.model_validate(feature)


@router.put("/{plan_code}/features/{feature_id}", response_model=PlanFeatureAdminOut)
def update_feature(
    plan_code: str,
    feature_id: int,
    body: PlanFeatureUpdate,
    request: Request,
    db: Session = Depends(get_db),
    application: Application = Depends(get_application),
    admin: AdminUser = Depends(require_permission("PLANS_MANAGE")),
):
    plan = _get_plan(db, application=application, plan_code=plan_code)
    feature = db.query(PlanFeature).filter(PlanFeature.id == feature_id, PlanFeature.plan_id == plan.id).first()
    if feature is None:
        raise PlanFeatureNotFoundError(f"Unknown feature {feature_id} on plan {plan_code}")

    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(feature, field, value)
    db.add(feature)
    db.flush()

    audit_service.record(
        db,
        actor=admin.email,
        action="PLAN_FEATURE_UPDATED",
        entity_type="plan_feature",
        entity_id=str(feature.id),
        new_value=updates,
        ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(feature)
    return PlanFeatureAdminOut.model_validate(feature)


@router.delete("/{plan_code}/features/{feature_id}", status_code=204)
def delete_feature(
    plan_code: str,
    feature_id: int,
    request: Request,
    db: Session = Depends(get_db),
    application: Application = Depends(get_application),
    admin: AdminUser = Depends(require_permission("PLANS_MANAGE")),
):
    plan = _get_plan(db, application=application, plan_code=plan_code)
    feature = db.query(PlanFeature).filter(PlanFeature.id == feature_id, PlanFeature.plan_id == plan.id).first()
    if feature is None:
        raise PlanFeatureNotFoundError(f"Unknown feature {feature_id} on plan {plan_code}")

    old_value = {"feature_key": feature.feature_key, "feature_label": feature.feature_label}
    db.delete(feature)
    audit_service.record(
        db,
        actor=admin.email,
        action="PLAN_FEATURE_DELETED",
        entity_type="plan_feature",
        entity_id=str(feature_id),
        old_value=old_value,
        ip_address=_client_ip(request),
    )
    db.commit()
    return None
