"""
Admin API (spec sections 12, 51-54, 61: /api/v1/admin/).

Only authentication is implemented in this pass (login + MFA verify + a
protected /me). Plan/form management, customer/subscription/payment/
invoice views, webhook/email/audit logs, and the Testing module are not
yet built - see docs/implementation-status.md. The router is wired up now
so the URL namespace exists and get_current_admin is ready for those
endpoints to depend on.
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
