"""
Admin Registration Form fields (spec sections 8, 18, 51).

Mirrors the admin_plans.py pattern: fields are never hard-deleted (a
field_key may already be referenced by existing CustomerRegistrationData
rows) - only deactivated, which also removes it from the public
GET /public/registration-form the dynamic form renderer reads.
field_key is immutable once created (code/data already key on it).

plan_codes ("Show only for plans") turns a field into a plan-specific
question - e.g. the Custom plan's expected monthly tickets / average
ticket price - see app.forms.models.RegistrationFormField.plan_codes.
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_application, get_db
from app.applications.models import Application
from app.audit import service as audit_service
from app.auth.deps import require_permission
from app.auth.models import AdminUser
from app.core.exceptions import AppError
from app.forms.models import RegistrationFormField
from app.forms.schemas import RegistrationFormFieldAdminOut, RegistrationFormFieldCreate, RegistrationFormFieldUpdate
from app.plans.models import Plan

router = APIRouter(prefix="/registration-form", tags=["admin-forms"])


class FormFieldNotFoundError(AppError):
    http_status = 404
    error_code = "FORM_FIELD_NOT_FOUND"


class FormFieldKeyInUse(AppError):
    http_status = 409
    error_code = "FORM_FIELD_KEY_IN_USE"


class UnknownPlanCodes(AppError):
    http_status = 422
    error_code = "UNKNOWN_PLAN_CODES"


def _assert_plan_codes_exist(db: Session, application: Application, plan_codes: list[str] | None) -> None:
    """Every "Show only for plans" code must be a plan of this application
    (active or not - an admin may set up a plan's questions before
    activating the plan). Codes are already upper-cased by the schema."""
    if not plan_codes:
        return
    known = {
        code
        for (code,) in db.query(Plan.plan_code).filter(
            Plan.application_id == application.id, Plan.plan_code.in_(plan_codes)
        )
    }
    missing = [code for code in plan_codes if code not in known]
    if missing:
        raise UnknownPlanCodes(f"Unknown plan code(s): {', '.join(missing)}")


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("", response_model=list[RegistrationFormFieldAdminOut])
def list_fields(
    db: Session = Depends(get_db),
    application: Application = Depends(get_application),
    _admin: AdminUser = Depends(require_permission("FORMS_MANAGE")),
):
    fields = (
        db.query(RegistrationFormField)
        .filter(RegistrationFormField.application_id == application.id)
        .order_by(RegistrationFormField.display_order)
        .all()
    )
    return [RegistrationFormFieldAdminOut.model_validate(f) for f in fields]


@router.post("", response_model=RegistrationFormFieldAdminOut, status_code=201)
def create_field(
    body: RegistrationFormFieldCreate,
    request: Request,
    db: Session = Depends(get_db),
    application: Application = Depends(get_application),
    admin: AdminUser = Depends(require_permission("FORMS_MANAGE")),
):
    existing = (
        db.query(RegistrationFormField)
        .filter(
            RegistrationFormField.application_id == application.id,
            RegistrationFormField.field_key == body.field_key,
        )
        .first()
    )
    if existing is not None:
        raise FormFieldKeyInUse(f"Field key '{body.field_key}' already exists")
    _assert_plan_codes_exist(db, application, body.plan_codes)

    field = RegistrationFormField(application_id=application.id, active=True, **body.model_dump())
    db.add(field)
    db.flush()

    audit_service.record(
        db,
        actor=admin.email,
        action="FORM_FIELD_CREATED",
        entity_type="registration_form_field",
        entity_id=field.field_key,
        new_value=body.model_dump(),
        ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(field)
    return RegistrationFormFieldAdminOut.model_validate(field)


@router.put("/{field_id}", response_model=RegistrationFormFieldAdminOut)
def update_field(
    field_id: int,
    body: RegistrationFormFieldUpdate,
    request: Request,
    db: Session = Depends(get_db),
    application: Application = Depends(get_application),
    admin: AdminUser = Depends(require_permission("FORMS_MANAGE")),
):
    field = (
        db.query(RegistrationFormField)
        .filter(RegistrationFormField.id == field_id, RegistrationFormField.application_id == application.id)
        .first()
    )
    if field is None:
        raise FormFieldNotFoundError(f"Unknown registration form field {field_id}")

    updates = body.model_dump(exclude_unset=True)
    if "plan_codes" in updates:
        _assert_plan_codes_exist(db, application, updates["plan_codes"])
    for key, value in updates.items():
        setattr(field, key, value)
    db.add(field)
    db.flush()

    audit_service.record(
        db,
        actor=admin.email,
        action="FORM_FIELD_UPDATED",
        entity_type="registration_form_field",
        entity_id=field.field_key,
        new_value=updates,
        ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(field)
    return RegistrationFormFieldAdminOut.model_validate(field)
