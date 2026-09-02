"""Admin configuration screens, restructured 2026-09 into 4 sections
(spec sections 13, 51, 81): Application, Payment Gateway, Everyticket
Integration, Notifications. "Subscription rules" and "Security"
configuration keep their own existing endpoints/enforcement, unchanged -
see app.applications.config_schemas' module docstring for the full
rationale. Every mutation is audit-logged, secrets are masked on read.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.deps import get_application, get_db
from app.applications.config_schemas import (
    ApplicationConfigOut,
    ApplicationGeneralOut,
    ApplicationGeneralUpdate,
    ApplicationSubscriptionRulesOut,
    ApplicationSubscriptionRulesUpdate,
    EveryticketIntegrationOut,
    EveryticketIntegrationUpdate,
    EveryticketWebhookSampleOut,
    NotificationConfigOut,
    NotificationConfigUpdate,
    PaymentGatewayConfigOut,
    PaymentGatewayConfigUpdate,
)
from app.applications.models import Application
from app.audit import service as audit_service
from app.auth.deps import require_permission
from app.auth.models import AdminUser
from app.auth.security_config import SecurityConfigOut, SecurityConfigUpdate, get_security_config, set_security_config
from app.core.config import get_settings
from app.forms.models import RegistrationFormField
from app.payments.gateway_config import get_payu_credentials_status, set_payu_credentials
from app.payments.gateways.registry import list_gateway_codes
from app.plans.models import Plan
from app.plans.sanitize import sanitize_description as _sanitize_html
from app.webhooks.payloads import (
    archive_payload,
    cancelled_payload,
    expiry_payload,
    onboarding_payload,
    renewed_payload,
)
from app.webhooks.service import build_wire_body

router = APIRouter(prefix="/config", tags=["admin-config"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _payment_gateway_out(db: Session, application: Application) -> PaymentGatewayConfigOut:
    status = get_payu_credentials_status(db)
    return PaymentGatewayConfigOut(
        default_gateway=application.default_gateway,
        available_gateways=list_gateway_codes(),
        payu_test=status["test"],
        payu_live=status["live"],
        return_url=application.return_url,
        payu_webhook_base_url=application.payu_webhook_base_url,
    )


def _sample_value_for_field(field: RegistrationFormField) -> object:
    """Illustrative, obviously-fake example value for one registration
    field, type-appropriate so the onboarding sample below reads as real
    data rather than a wall of "string" placeholders."""
    if field.options:
        first = field.options[0]
        return first.get("value", first) if isinstance(first, dict) else first
    if field.field_type in ("number", "integer"):
        return 42
    if field.field_type in ("checkbox", "boolean"):
        return True
    if field.field_type == "email":
        return "sample@example.com"
    if field.placeholder:
        return field.placeholder
    return f"Sample {field.label}"


def _build_webhook_samples(db: Session, application: Application) -> list[EveryticketWebhookSampleOut]:
    """Read-only preview of the exact JSON each of the five real
    outbound webhook events sends (2026-09 follow-up: "Webhook for
    everyticket app are as below: 1) onboarding... 2) status inactive
    when plan expires... 3) delete/archive when user do not renew for x
    days"; follow-up 3: "Add one more webhook for renew"). Built from
    app.webhooks.payloads - the SAME functions that shape a real
    delivery - so this documentation can never quietly drift from what's
    actually sent. Registration-field keys are pulled from this
    application's real, currently-configured form (falling back to two
    generic example fields if none are configured yet), and plan_code/
    name/price come from a real active plan when one exists, so the
    onboarding sample reflects this application's actual setup rather
    than being entirely made up. The other four events are trimmed to
    just subscription_id (2026-09 follow-up 3), so there is nothing
    application-specific left to reflect for them."""
    now = datetime.now(timezone.utc)
    fields = (
        db.query(RegistrationFormField)
        .filter(RegistrationFormField.application_id == application.id, RegistrationFormField.active.is_(True))
        .order_by(RegistrationFormField.display_order)
        .all()
    )
    registration_data = (
        {f.field_key: _sample_value_for_field(f) for f in fields}
        if fields
        else {"organization_name": "Sample Museum", "contact_person": "Jane Doe"}
    )

    plan = (
        db.query(Plan)
        .filter(Plan.application_id == application.id, Plan.active.is_(True), Plan.is_trial.is_(False))
        .order_by(Plan.price)
        .first()
    )
    plan_code = plan.plan_code if plan else "PRO"
    plan_name = plan.name if plan else "Pro Plan"
    price = float(plan.price) if plan else 999.0

    sample_subscription_id = "SUB-000123"

    onboarding = onboarding_payload(
        subscription_id=sample_subscription_id,
        plan_code=plan_code,
        plan_name=plan_name,
        price=price,
        is_trial=False,
        expires_at=(now + timedelta(days=30)).isoformat(),
        registration_data=registration_data,
    )
    renewed = renewed_payload(subscription_id=sample_subscription_id)
    expired = expiry_payload(subscription_id=sample_subscription_id)
    cancelled = cancelled_payload(subscription_id=sample_subscription_id)
    archived = archive_payload(subscription_id=sample_subscription_id)

    # Wrapped via the SAME build_wire_body() a real delivery uses (see
    # app.webhooks.service._attempt_one) - just {event_type, payload}, so
    # the preview below is the literal JSON body Everyticket's endpoint
    # would receive, not just the inner event data.
    events = [
        ("subscription.activated", onboarding, "Onboarding: fires once, the first time a new customer's payment succeeds."),
        ("subscription.renewed", renewed, "Renew: fires once an existing subscription's renewal payment succeeds."),
        ("subscription.expired", expired, "Status inactive: fires once when an active subscription's plan expires unrenewed."),
        ("subscription.cancelled", cancelled, "Cancel: fires once a customer cancels their subscription immediately."),
        (
            "subscription.archived",
            archived,
            "Delete/archive: fires once an expired subscription has stayed unrenewed past the Archive after "
            "threshold below (disabled until that field is set).",
        ),
    ]
    return [
        EveryticketWebhookSampleOut(
            event=event_type,
            trigger=trigger,
            payload=build_wire_body(event_type=event_type, payload=event_payload),
        )
        for event_type, event_payload, trigger in events
    ]


def _integration_out(db: Session, application: Application) -> EveryticketIntegrationOut:
    return EveryticketIntegrationOut(
        secret_key_is_set=bool(application.webhook_secret),
        webhook_url=application.webhook_url,
        retry_limit=application.webhook_retry_limit,
        default_retry_limit=len(get_settings().webhook_retry_schedule),
        escalation_emails=application.webhook_escalation_emails,
        escalation_email_subject=application.webhook_escalation_email_subject,
        escalation_email_body=application.webhook_escalation_email_body,
        archive_after_days=application.archive_after_days,
        webhook_samples=_build_webhook_samples(db, application),
    )


def _notification_out(application: Application) -> NotificationConfigOut:
    return NotificationConfigOut(
        smtp_host=application.smtp_host,
        smtp_port=application.smtp_port,
        smtp_username=application.smtp_username,
        smtp_password_is_set=bool(application.smtp_password),
        smtp_use_tls=application.smtp_use_tls,
        email_sender_name=application.email_sender_name,
        email_sender_address=application.email_sender_address,
        email_reply_to=application.email_reply_to,
    )


@router.get("/application", response_model=ApplicationConfigOut)
def get_application_config(
    db: Session = Depends(get_db),
    application: Application = Depends(get_application),
    _admin: AdminUser = Depends(require_permission("SYSTEM_CONFIG_VIEW")),
):
    return ApplicationConfigOut(
        general=ApplicationGeneralOut.model_validate(application),
        payment_gateway=_payment_gateway_out(db, application),
        integration=_integration_out(db, application),
        notification=_notification_out(application),
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


@router.put("/application/payment-gateway", response_model=PaymentGatewayConfigOut)
def update_payment_gateway_config(
    body: PaymentGatewayConfigUpdate,
    request: Request,
    db: Session = Depends(get_db),
    application: Application = Depends(get_application),
    admin: AdminUser = Depends(require_permission("SYSTEM_CONFIG_MANAGE")),
):
    """`default_gateway` takes effect on the very next payment this
    application creates. PayU test/live credentials are stored via
    app.payments.gateway_config (system_settings), keyed by mode - which
    mode is actually used for a real payment is decided by
    Application.gateway_mode ("Live/Test Mode", edited on the Application
    screen, not here)."""
    application.default_gateway = body.default_gateway
    application.return_url = body.return_url or None
    application.payu_webhook_base_url = body.payu_webhook_base_url or None
    db.add(application)

    if body.payu_test is not None:
        set_payu_credentials(
            db, mode="test", merchant_key=body.payu_test.merchant_key, merchant_salt=body.payu_test.merchant_salt
        )
    if body.payu_live is not None:
        set_payu_credentials(
            db, mode="live", merchant_key=body.payu_live.merchant_key, merchant_salt=body.payu_live.merchant_salt
        )

    audit_service.record(
        db, actor=admin.email, action="APPLICATION_CONFIG_UPDATED", entity_type="application",
        entity_id=application.code,
        new_value={
            "group": "payment_gateway", "default_gateway": body.default_gateway,
            "payu_test_changed": body.payu_test is not None, "payu_live_changed": body.payu_live is not None,
            "return_url": body.return_url, "payu_webhook_base_url": body.payu_webhook_base_url,
        },
        ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(application)
    return _payment_gateway_out(db, application)


@router.put("/application/integration", response_model=EveryticketIntegrationOut)
def update_integration_config(
    body: EveryticketIntegrationUpdate,
    request: Request,
    db: Session = Depends(get_db),
    application: Application = Depends(get_application),
    admin: AdminUser = Depends(require_permission("SYSTEM_CONFIG_MANAGE")),
):
    """webhook_url/retry_limit/escalation_* all take effect on the very
    next webhook delivery attempt (app.webhooks.service). None on a
    field = leave the currently-stored value unchanged (so the frontend
    never has to round-trip the secret key) - pass "" to explicitly
    clear secret_key/webhook_url; retry_limit/escalation_* are replaced
    outright when given (they aren't secrets). The custom key/value
    extra-parameters editor that used to live on this endpoint was
    removed (2026-09 follow-up 3: "Remove feature for parameters
    (key,value) from this section") - webhook_extra_params is no longer
    read from or written by this endpoint."""
    application.webhook_url = body.webhook_url
    if body.secret_key is not None:
        application.webhook_secret = body.secret_key or None
    application.webhook_retry_limit = body.retry_limit
    application.webhook_escalation_emails = body.escalation_emails or None
    application.webhook_escalation_email_subject = body.escalation_email_subject or None
    application.webhook_escalation_email_body = _sanitize_html(body.escalation_email_body)
    application.archive_after_days = body.archive_after_days
    db.add(application)
    audit_service.record(
        db, actor=admin.email, action="APPLICATION_CONFIG_UPDATED", entity_type="application",
        entity_id=application.code,
        new_value={
            "group": "integration", "webhook_url": body.webhook_url,
            "secret_key_changed": body.secret_key is not None,
            "retry_limit": body.retry_limit, "escalation_emails": body.escalation_emails,
            "archive_after_days": body.archive_after_days,
        },
        ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(application)
    return _integration_out(db, application)


@router.put("/application/notification", response_model=NotificationConfigOut)
def update_notification_config(
    body: NotificationConfigUpdate,
    request: Request,
    db: Session = Depends(get_db),
    application: Application = Depends(get_application),
    admin: AdminUser = Depends(require_permission("SYSTEM_CONFIG_MANAGE")),
):
    """Every field here overrides the global SMTP_*/EMAIL_* env settings
    for THIS application's outbound email only, falling back to the
    global defaults for any field left unset - see
    app.notifications.email.service._resolve_settings()."""
    application.smtp_host = body.smtp_host or None
    application.smtp_port = body.smtp_port
    application.smtp_username = body.smtp_username or None
    if body.smtp_password is not None:
        application.smtp_password = body.smtp_password or None
    application.smtp_use_tls = body.smtp_use_tls
    application.email_provider = body.email_provider
    application.email_sender_name = body.email_sender_name
    application.email_sender_address = body.email_sender_address
    application.email_reply_to = body.email_reply_to
    db.add(application)
    audit_service.record(
        db, actor=admin.email, action="APPLICATION_CONFIG_UPDATED", entity_type="application",
        entity_id=application.code,
        new_value={
            "group": "notification", "smtp_host": body.smtp_host, "smtp_port": body.smtp_port,
            "smtp_password_changed": body.smtp_password is not None,
            "email_sender_name": body.email_sender_name, "email_sender_address": body.email_sender_address,
        },
        ip_address=_client_ip(request),
    )
    db.commit()
    db.refresh(application)
    return _notification_out(application)


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
    after expiry/cancellation (spec section 41). Not currently surfaced
    on the restructured admin Configuration page - kept here unchanged
    for anything that already calls this endpoint directly."""
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
