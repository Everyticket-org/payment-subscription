"""
Admin Registration Form fields (spec sections 8, 18, 51).

Mirrors the admin_plans.py pattern: fields are never hard-deleted (a
field_key may already be referenced by existing CustomerRegistrationData
rows) - only deactivated, which also removes it from the public
GET /public/registration-form the dynamic form renderer reads.
field_key is immutable once created (code/data already key on it).
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

router = APIRouter(prefix="/registration-form", tags=["admin-forms"])


class FormFieldNotFoundError(AppError):
    http_status = 404
    error_code = "FORM_FIELD_NOT_FOUND"


class FormFieldKeyInUse(AppError):
    http_status = 409
    error_code = "FORM_FIELD_KEY_IN_USE"


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
