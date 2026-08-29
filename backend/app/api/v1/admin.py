"""
Admin API (spec sections 12, 51-54, 61: /api/v1/admin/).

Auth (login + MFA verify + /me) lives in this module; every other admin
module - dashboard, plans, customers, subscriptions, payments, invoices,
webhook logs, notification templates/logs, audit logs - is a sibling
app.api.v1.admin_*.py router included below, each gated by
app.auth.deps.require_permission (spec section 12's role/permission
model, seeded onto SUPERADMIN in app.core.seed) - including
admin_testing.py, the Testing/Developer Tools module (spec section 54),
additionally gated by app.auth.deps.require_test_mode.
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.auth import service as auth_service
from app.auth.deps import get_current_admin
from app.auth.models import AdminUser
from app.auth.schemas import AdminLoginRequest, AdminLoginResponse, AdminMfaVerifyRequest, AdminUserOut, TokenResponse

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/auth/login", response_model=AdminLoginResponse)
def login(body: AdminLoginRequest, db: Session = Depends(get_db)):
    user = auth_service.authenticate_password(db, email=body.email, password=body.password)

    if not user.mfa_enabled:
        access_token, refresh_token = auth_service.issue_tokens(user)
        return AdminLoginResponse(mfa_required=False, access_token=access_token, refresh_token=refresh_token)

    pre_mfa_token = auth_service.create_pre_mfa_token(user)
    return AdminLoginResponse(mfa_required=True, pre_mfa_token=pre_mfa_token)


@router.post("/auth/mfa/verify", response_model=TokenResponse)
def verify_mfa(body: AdminMfaVerifyRequest, request: Request, db: Session = Depends(get_db)):
    user = auth_service.resolve_pre_mfa_token(db, pre_mfa_token=body.pre_mfa_token)
    auth_service.verify_mfa_code(db, user=user, code=body.code, ip_address=request.client.host if request.client else None)
    access_token, refresh_token = auth_service.issue_tokens(user)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.get("/me", response_model=AdminUserOut)
def me(current: AdminUser = Depends(get_current_admin)):
    return AdminUserOut(
        email=current.email,
        full_name=current.full_name,
        is_active=current.is_active,
        mfa_enabled=current.mfa_enabled,
        roles=[r.code for r in current.roles],
    )


# --- Sibling admin modules (spec sections 51-56) - each defines its own
# APIRouter with a resource-specific prefix (e.g. "/plans"), included here
# under this module's "/admin" prefix so every admin endpoint still lives
# under /api/v1/admin/*. Kept as separate files rather than one giant
# admin.py for the same reason app/api/v1/*.py is already split by
# resource (public.py, customer.py, payment.py, ...). ---
from app.api.v1.admin_audit import router as admin_audit_router
from app.api.v1.admin_customers import router as admin_customers_router
from app.api.v1.admin_dashboard import router as admin_dashboard_router
from app.api.v1.admin_forms import router as admin_forms_router
from app.api.v1.admin_invoices import router as admin_invoices_router
from app.api.v1.admin_notifications import router as admin_notifications_router
from app.api.v1.admin_payments import router as admin_payments_router
from app.api.v1.admin_plans import router as admin_plans_router
from app.api.v1.admin_subscriptions import router as admin_subscriptions_router
from app.api.v1.admin_webhooks import router as admin_webhooks_router
from app.api.v1.admin_testing import router as admin_testing_router
from app.api.v1.admin_config import router as admin_config_router

router.include_router(admin_dashboard_router)
router.include_router(admin_plans_router)
router.include_router(admin_forms_router)
router.include_router(admin_customers_router)
router.include_router(admin_subscriptions_router)
router.include_router(admin_payments_router)
router.include_router(admin_invoices_router)
router.include_router(admin_webhooks_router)
router.include_router(admin_notifications_router)
router.include_router(admin_audit_router)
router.include_router(admin_testing_router)
router.include_router(admin_config_router)
