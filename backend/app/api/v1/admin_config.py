"""Admin configuration screens (spec sections 13, 51, 81): Payment Gateway
Configuration, Everyticket Integration Configuration, Notification
Configuration, and System Configuration all read/write different field
groups of the single V1 Application row; Security Configuration covers
the admin-tunable OTP parameters in app.auth.security_config. Every
mutation is audit-logged, secrets are masked on read (see
app.applications.config_schemas' module docstring).
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_application, get_db
from app.applications.config_schemas import (
    ApplicationConfigOut,
    ApplicationGeneralOut,
    ApplicationGeneralUpdate,
    ApplicationIntegrationOut,
    ApplicationIntegrationUpdate,
    ApplicationNotificationOut,
    ApplicationNotificationUpdate,
    ApplicationPaymentOut,
    ApplicationPaymentUpdate,
    ApplicationSubscriptionRulesOut,
    ApplicationSubscriptionRulesUpdate,
)
from app.applications.models import Application
from app.audit import service as audit_service
from app.auth.deps import require_permission
from app.auth.models import AdminUser
from app.auth.security_config import SecurityConfigOut, SecurityConfigUpdate, get_security_config, set_security_config

router = APIRouter(prefix="/config", tags=["admin-config"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _integration_out(application: Application) -> ApplicationIntegrationOut:
    return ApplicationIntegrationOut(
        api_url=application.api_url,
        api_credentials_is_set=bool(application.api_credentials),
        webhook_url=application.webhook_url,
        webhook_secret_is_set=bool(application.webhook_secret),
        sso_secret_is_set=bool(application.sso_secret),
    )


@router.get("/application", response_model=ApplicationConfigOut)
def get_application_config(
    application: Application = Depends(get_application),
    _admin: AdminUser = Depends(require_permission("SYSTEM_CONFIG_VIEW")),
):
    return ApplicationConfigOut(
        general=ApplicationGeneralOut.model_validate(application),
        integration=_integration_out(application),
        payment=ApplicationPaymentOut.model_validate(application),
        notification=ApplicationNotificationOut.model_validate(application),
        subscription_rules=ApplicationSubscriptionRulesOut.model_validate(application),
    )


@router.put("/application/general", response_model=ApplicationGeneralOut)
def update_general_config(
    body: ApplicationGeneralUpdate,
    request: Request,
    db: Session = Depends(get_db),
    application: Application = Depends(get_application),
    admin: AdminUser = Depends(require_permission("SYSTEM_CONFIG_MANAGE")),
):
    for field, value in body.model_dump().items():
        setattr(application, field, value)
    db.add(application)
    audit_service.record(
        db, actor=admin.email, action="APPLICATION_CONFIG_UPDATED", entity_type="application",
        entity_id=application.code, new_value={"group": "general", **body.model_dump()}, ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(application)
    return ApplicationGeneralOut.model_validate(application)


@router.put("/application/integration", response_model=ApplicationIntegrationOut)
def update_integration_config(
    body: ApplicationIntegrationUpdate,
    request: Request,
    db: Session = Depends(get_db),
    application: Application = Depends(get_application),
    admin: AdminUser = Depends(require_permission("SYSTEM_CONFIG_MANAGE")),
):
    application.api_url = body.api_url
    if body.api_credentials is not None:
        application.api_credentials = body.api_credentials
    application.webhook_url = body.webhook_url
    # None = leave the currently-stored secret unchanged (so the frontend
    # never has to round-trip a secret it can't even see) - pass "" to
    # explicitly clear one.
    if body.webhook_secret is not None:
        application.webhook_secret = body.webhook_secret or None
    if body.sso_secret is not None:
        application.sso_secret = body.sso_secret or None
    db.add(application)
    audit_service.record(
        db, actor=admin.email, action="APPLICATION_CONFIG_UPDATED", entity_type="application",
        entity_id=application.code,
        new_value={
            "group": "integration", "api_url": body.api_url, "webhook_url": body.webhook_url,
            "api_credentials_changed": body.api_credentials is not None,
            "webhook_secret_changed": body.webhook_secret is not None,
            "sso_secret_changed": body.sso_secret is not None,
        },
        ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(application)
    return _integration_out(application)


@router.put("/application/payment", response_model=ApplicationPaymentOut)
def update_payment_config(
    body: ApplicationPaymentUpdate,
    request: Request,
    db: Session = Depends(get_db),
    application: Application = Depends(get_application),
    admin: AdminUser = Depends(require_permission("SYSTEM_CONFIG_MANAGE")),
):
    """`default_gateway` takes effect on the very next payment this
    application creates (every call site reads `application.default_gateway`
    directly). Gateway *credentials* (e.g. PayU's merchant key/salt) stay
    env-configured only (`backend/.env`) - deliberately not exposed here,
    since round-tripping raw payment-gateway secrets through a web form
    isn't worth the risk when an already-secure channel exists."""
    application.default_gateway = body.default_gateway
    application.gateway_mode = body.gateway_mode
    db.add(application)
    audit_service.record(
        db, actor=admin.email, action="APPLICATION_CONFIG_UPDATED", entity_type="application",
        entity_id=application.code, new_value={"group": "payment", **body.model_dump()}, ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(application)
    return ApplicationPaymentOut.model_validate(application)


@router.put("/application/notification", response_model=ApplicationNotificationOut)
def update_notification_config(
    body: ApplicationNotificationUpdate,
    request: Request,
    db: Session = Depends(get_db),
    application: Application = Depends(get_application),
    admin: AdminUser = Depends(require_permission("SYSTEM_CONFIG_MANAGE")),
):
    """Every field here overrides the global SMTP_*/EMAIL_* env settings
    for THIS application's outbound email only, falling back to the
    global defaults for any field left blank (see
    app.notifications.email.service.send_templated_email's `application`
    param) - the same per-application-override pattern already used for
    the SSO secret and the Everyticket webhook secret."""
    for field, value in body.model_dump().items():
        setattr(application, field, value)
    db.add(application)
    audit_service.record(
        db, actor=admin.email, action="APPLICATION_CONFIG_UPDATED", entity_type="application",
        entity_id=application.code, new_value={"group": "notification", **body.model_dump()}, ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(application)
    return ApplicationNotificationOut.model_validate(application)


@router.put("/application/subscription-rules", response_model=ApplicationSubscriptionRulesOut)
def update_subscription_rules_config(
    body: ApplicationSubscriptionRulesUpdate,
    request: Request,
    db: Session = Depends(get_db),
    application: Application = Depends(get_application),
    admin: AdminUser = Depends(require_permission("SYSTEM_CONFIG_MANAGE")),
):
    """allow_upgrade/allow_downgrade/allow_cancellation/renewal_enabled
    are enforced live (app.api.v1.customer's upgrade/downgrade/renew/
    cancel endpoints check them before creating a payment or mutating the
    subscription - spec section 403 `ACTION_NOT_ALLOWED` if disabled).
    `cancellation_behavior` and `repurchase_enabled` are stored for
    forward-compatibility but not yet enforced - V1 only implements
    IMMEDIATE cancellation (spec section 43) and always allows repurchase
    after expiry/cancellation (spec section 41)."""
    for field, value in body.model_dump().items():
        setattr(application, field, value)
    db.add(application)
    audit_service.record(
        db, actor=admin.email, action="APPLICATION_CONFIG_UPDATED", entity_type="application",
        entity_id=application.code, new_value={"group": "subscription_rules", **body.model_dump()}, ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(application)
    return ApplicationSubscriptionRulesOut.model_validate(application)


@router.get("/security", response_model=SecurityConfigOut)
def get_security_config_view(
    db: Session = Depends(get_db),
    _admin: AdminUser = Depends(require_permission("SYSTEM_CONFIG_VIEW")),
):
    return get_security_config(db)


@router.put("/security", response_model=SecurityConfigOut)
def update_security_config_view(
    body: SecurityConfigUpdate,
    request: Request,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_permission("SYSTEM_CONFIG_MANAGE")),
):
    updated = set_security_config(db, update=body)
    audit_service.record(
        db, actor=admin.email, action="SECURITY_CONFIG_UPDATED", entity_type="system_setting",
        entity_id="otp_security_config", new_value=body.model_dump(), ip_address=_client_ip(request),
    )
    db.commit()
    return updated
