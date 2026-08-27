"""
Development seed data (spec section 70).

Creates the single V1 application (EVERYTICKET) with Basic/Professional/
Enterprise plans, a small dynamic registration form, and the allowed
upgrade/downgrade plan transitions. Safe to run more than once - it
upserts by natural key (application code / plan code) rather than
duplicating rows.

Usage:
    python -m app.core.seed
"""
from sqlalchemy.orm import Session

from app.applications.models import Application
from app.auth import service as auth_service
from app.auth.models import AdminUser, Role
from app.core.database import SessionLocal
from app.core import models_registry  # noqa: F401
from app.forms.models import RegistrationFormField
from app.plans.models import Plan, PlanTransition

DEV_ADMIN_EMAIL = "admin@example.com"
DEV_ADMIN_PASSWORD = "ChangeMe123!"  # dev/local only - never a production credential


def _get_or_create_application(db: Session) -> Application:
    app_row = db.query(Application).filter(Application.code == "EVERYTICKET").first()
    if app_row is not None:
        return app_row

    app_row = Application(
        code="EVERYTICKET",
        name="Everyticket",
        application_url="http://localhost:9000",
        support_email="support@example.com",
        timezone="Asia/Kolkata",
        currency="INR",
        default_gateway="mock",
        gateway_mode="test",
        test_mode=True,
        otp_bypass_enabled=True,
        mfa_bypass_enabled=True,
        payment_simulation_enabled=True,
    )
    db.add(app_row)
    db.flush()
    return app_row


def _get_or_create_plan(db: Session, application: Application, **kwargs) -> Plan:
    plan = (
        db.query(Plan)
        .filter(Plan.application_id == application.id, Plan.plan_code == kwargs["plan_code"])
        .first()
    )
    if plan is not None:
        return plan
    plan = Plan(application_id=application.id, **kwargs)
    db.add(plan)
    db.flush()
    return plan


def _get_or_create_transition(db: Session, application: Application, from_plan: Plan, to_plan: Plan, transition_type: str) -> None:
    existing = (
        db.query(PlanTransition)
        .filter(PlanTransition.from_plan_id == from_plan.id, PlanTransition.to_plan_id == to_plan.id)
        .first()
    )
    if existing is not None:
        return
    db.add(
        PlanTransition(
            application_id=application.id,
            from_plan_id=from_plan.id,
            to_plan_id=to_plan.id,
            transition_type=transition_type,
        )
    )


def _get_or_create_field(db: Session, application: Application, **kwargs) -> None:
    existing = (
        db.query(RegistrationFormField)
        .filter(RegistrationFormField.application_id == application.id, RegistrationFormField.field_key == kwargs["field_key"])
        .first()
    )
    if existing is not None:
        return
    db.add(RegistrationFormField(application_id=application.id, **kwargs))


def _get_or_create_admin(db: Session) -> AdminUser:
    """Dev-only seed admin (spec section 70). Credentials are printed by
    main() and documented in README.md - they are NOT meant for
    production use; production admin accounts should be created through a
    proper (not-yet-built) admin-user-management flow."""
    existing = db.query(AdminUser).filter(AdminUser.email == DEV_ADMIN_EMAIL).first()
    if existing is not None:
        return existing

    role = db.query(Role).filter(Role.code == "SUPERADMIN").first()
    if role is None:
        role = Role(code="SUPERADMIN", name="Super Admin")
        db.add(role)
        db.flush()

    user = auth_service.create_admin_user(
        db, email=DEV_ADMIN_EMAIL, full_name="Dev Admin", password=DEV_ADMIN_PASSWORD, mfa_enabled=True
    )
    user.roles.append(role)
    db.add(user)
    db.flush()
    return user


def seed(db: Session) -> AdminUser:
    application = _get_or_create_application(db)

    basic = _get_or_create_plan(
        db, application, plan_code="BASIC", name="Basic", description="Entry-level plan",
        price=2000, currency="INR", billing_interval="month", billing_frequency=1, display_order=1,
    )
    professional = _get_or_create_plan(
        db, application, plan_code="PROFESSIONAL", name="Professional", description="For growing museums",
        price=5000, currency="INR", billing_interval="month", billing_frequency=1, display_order=2,
    )
    enterprise = _get_or_create_plan(
        db, application, plan_code="ENTERPRISE", name="Enterprise", description="Full feature set",
        price=15000, currency="INR", billing_interval="month", billing_frequency=1, display_order=3,
    )

    _get_or_create_transition(db, application, basic, professional, "UPGRADE")
    _get_or_create_transition(db, application, basic, enterprise, "UPGRADE")
    _get_or_create_transition(db, application, professional, enterprise, "UPGRADE")
    _get_or_create_transition(db, application, professional, basic, "DOWNGRADE")
    _get_or_create_transition(db, application, enterprise, professional, "DOWNGRADE")
    _get_or_create_transition(db, application, enterprise, basic, "DOWNGRADE")

    _get_or_create_field(db, application, field_key="museum_name", label="Museum Name", field_type="text", required=True, display_order=1)
    _get_or_create_field(db, application, field_key="contact_person", label="Contact Person", field_type="text", required=True, display_order=2)
    _get_or_create_field(db, application, field_key="gstin", label="GSTIN", field_type="text", required=False, display_order=3)
    _get_or_create_field(db, application, field_key="address", label="Address", field_type="textarea", required=False, display_order=4)

    admin_user = _get_or_create_admin(db)

    db.commit()
    return admin_user


def main() -> None:
    db = SessionLocal()
    try:
        admin_user = seed(db)
        print("Seed data applied.")
        print(f"Dev admin login: {DEV_ADMIN_EMAIL} / {DEV_ADMIN_PASSWORD}")
        if admin_user.mfa_secret:
            import pyotp

            uri = pyotp.TOTP(admin_user.mfa_secret).provisioning_uri(
                name=DEV_ADMIN_EMAIL, issuer_name="Everyticket Subscriptions (dev)"
            )
            print(f"Dev admin MFA secret: {admin_user.mfa_secret}")
            print(f"Dev admin MFA provisioning URI (scan in an authenticator app): {uri}")
            print('Or skip MFA entirely in dev/staging by submitting code "BYPASS" to /admin/auth/mfa/verify.')
    finally:
        db.close()


if __name__ == "__main__":
    main()
