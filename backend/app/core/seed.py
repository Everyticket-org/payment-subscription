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
from app.auth.models import AdminUser, Permission, Role
from app.auth.permissions import PERMISSIONS
from app.core.database import SessionLocal
from app.core import models_registry  # noqa: F401
from app.forms.models import RegistrationFormField
from app.notifications.models import NotificationTemplate
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


_EMAIL_WRAPPER_OPEN = (
    "<div style=\"font-family:sans-serif;max-width:480px;margin:0 auto;\">"
    "<div style=\"background:#d50355;color:#fff;padding:16px 20px;border-radius:8px 8px 0 0;\">"
    "<strong>Everyticket Subscriptions</strong></div>"
    "<div style=\"background:#f1e2de;padding:20px;border-radius:0 0 8px 8px;color:#2a1512;\">"
)
_EMAIL_WRAPPER_CLOSE = "</div></div>"


def _get_or_create_template(db: Session, *, template_code: str, subject: str, body_html: str, body_text: str) -> None:
    """Dev-seeded default templates (spec sections 49-50). Wrapped in a
    minimal branded shell so even the un-customized default doesn't look
    like plain unstyled text. An admin will eventually be able to edit
    these via the (not-yet-built) admin CRUD API - see
    docs/implementation-status.md."""
    existing = db.query(NotificationTemplate).filter(NotificationTemplate.template_code == template_code).first()
    if existing is not None:
        return
    db.add(
        NotificationTemplate(
            template_code=template_code,
            channel="email",
            subject=subject,
            body_html=_EMAIL_WRAPPER_OPEN + body_html + _EMAIL_WRAPPER_CLOSE,
            body_text=body_text,
            active=True,
        )
    )


def _get_or_create_permission(db: Session, *, code: str, name: str) -> Permission:
    existing = db.query(Permission).filter(Permission.code == code).first()
    if existing is not None:
        return existing
    permission = Permission(code=code, name=name)
    db.add(permission)
    db.flush()
    return permission


def _sync_superadmin_role(db: Session) -> Role:
    """SUPERADMIN always carries every known permission (spec section 12).
    Re-synced on every seed() call (not just at role creation) so a
    PERMISSIONS catalog entry added later is retroactively granted to an
    already-seeded dev database without a manual migration/backfill step."""
    role = db.query(Role).filter(Role.code == "SUPERADMIN").first()
    if role is None:
        role = Role(code="SUPERADMIN", name="Super Admin")
        db.add(role)
        db.flush()

    existing_codes = {permission.code for permission in role.permissions}
    for code, name in PERMISSIONS:
        permission = _get_or_create_permission(db, code=code, name=name)
        if code not in existing_codes:
            role.permissions.append(permission)
    db.add(role)
    db.flush()
    return role


def _get_or_create_admin(db: Session) -> AdminUser:
    """Dev-only seed admin (spec section 70). Credentials are printed by
    main() and documented in README.md - they are NOT meant for
    production use; production admin accounts should be created through a
    proper (not-yet-built) admin-user-management flow."""
    role = _sync_superadmin_role(db)

    existing = db.query(AdminUser).filter(AdminUser.email == DEV_ADMIN_EMAIL).first()
    if existing is not None:
        return existing

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
    # Free trial (spec follow-up): its own distinct plan, price=0, with a
    # configurable trial_period_days rather than an attribute bolted onto
    # one of the paid plans above - "process will be the same" per the
    # feature request, so it goes through the exact same subscribe/
    # activate/expire flow as any other plan, just with is_trial=True.
    _get_or_create_plan(
        db, application, plan_code="FREE_TRIAL", name="Free Trial", description="Try Everyticket free for 14 days",
        price=0, currency="INR", billing_interval="month", billing_frequency=1, display_order=0,
        is_trial=True, trial_period_days=14,
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

    _get_or_create_template(
        db, template_code="otp_verification",
        subject="Your Everyticket Subscriptions verification code",
        body_html="<p>Your verification code is:</p><p style=\"font-size:28px;font-weight:700;letter-spacing:4px;\">{{ code }}</p><p>This code expires in a few minutes. If you didn't request this, you can ignore this email.</p>",
        body_text="Your verification code is: {{ code }}\n\nThis code expires in a few minutes. If you didn't request this, you can ignore this email.",
    )
    _get_or_create_template(
        db, template_code="payment_success",
        subject="Payment received - {{ plan_name }} subscription active",
        body_html="<p>Hi,</p><p>Your payment of {{ currency }} {{ amount }} for the <strong>{{ plan_name }}</strong> plan was successful, and your subscription is now active.</p><p>Transaction: {{ transaction_id }}</p>",
        body_text="Your payment of {{ currency }} {{ amount }} for the {{ plan_name }} plan was successful. Your subscription is now active. Transaction: {{ transaction_id }}",
    )
    _get_or_create_template(
        db, template_code="payment_failed",
        subject="Payment unsuccessful for your {{ plan_name }} subscription",
        body_html="<p>Hi,</p><p>Your payment of {{ currency }} {{ amount }} for the <strong>{{ plan_name }}</strong> plan was not successful{% if failure_reason %} ({{ failure_reason }}){% endif %}. Your subscription has not changed - you can try again any time.</p>",
        body_text="Your payment of {{ currency }} {{ amount }} for the {{ plan_name }} plan was not successful{% if failure_reason %} ({{ failure_reason }}){% endif %}. Your subscription has not changed.",
    )
    _get_or_create_template(
        db, template_code="subscription_cancelled",
        subject="Your {{ plan_name }} subscription has been cancelled",
        body_html="<p>Hi,</p><p>Your <strong>{{ plan_name }}</strong> subscription has been cancelled, effective immediately. No further charges will be made.</p>",
        body_text="Your {{ plan_name }} subscription has been cancelled, effective immediately. No further charges will be made.",
    )
    _get_or_create_template(
        db, template_code="renewal_reminder",
        subject="Your {{ plan_name }} subscription expires soon",
        body_html="<p>Hi,</p><p>Your <strong>{{ plan_name }}</strong> subscription expires on {{ expires_at }}. Renew any time from your account portal to keep it active.</p>",
        body_text="Your {{ plan_name }} subscription expires on {{ expires_at }}. Renew any time from your account portal to keep it active.",
    )
    _get_or_create_template(
        db, template_code="trial_ending",
        subject="Your free trial ends soon",
        body_html="<p>Hi,</p><p>Your <strong>{{ plan_name }}</strong> free trial ends on {{ expires_at }}. Subscribe to a paid plan from your account portal before then to keep access without interruption.</p>",
        body_text="Your {{ plan_name }} free trial ends on {{ expires_at }}. Subscribe to a paid plan from your account portal before then to keep access without interruption.",
    )
    _get_or_create_template(
        db, template_code="invoice_generated",
        subject="Your invoice {{ invoice_id }}",
        body_html="<p>Hi,</p><p>Your invoice for the <strong>{{ plan_name }}</strong> plan is attached to this email as a PDF.</p><p>Invoice: {{ invoice_id }}<br/>Amount: {{ currency }} {{ amount }}<br/>Tax: {{ currency }} {{ tax_amount }}<br/>Total: {{ currency }} {{ total_amount }}</p>",
        body_text="Your invoice for the {{ plan_name }} plan is attached as a PDF. Invoice: {{ invoice_id }}. Amount: {{ currency }} {{ amount }}. Tax: {{ currency }} {{ tax_amount }}. Total: {{ currency }} {{ total_amount }}.",
    )
    _get_or_create_template(
        db, template_code="provisioning_issue",
        subject="Setting up your {{ plan_name }} subscription",
        body_html="<p>Hi,</p><p>Your <strong>{{ plan_name }}</strong> subscription ({{ subscription_id }}) is active and your payment is confirmed. We're having a temporary issue finishing setup with our integration partner, and we're retrying automatically - there's nothing you need to do. We'll follow up if we need anything further from you.</p>",
        body_text="Your {{ plan_name }} subscription ({{ subscription_id }}) is active and your payment is confirmed. We're having a temporary issue finishing setup with our integration partner and are retrying automatically - no action is needed from you.",
    )

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
