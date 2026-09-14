"""Admin configuration screens, restructured 2026-09 into 4 sections
(spec sections 13, 51, 81): Application, Payment Gateway, Everyticket
Integration, Notifications. "Subscription rules" and "Security"
configuration keep their own existing endpoints/enforcement, unchanged -
see app.applications.config_schemas' module docstring for the full
rationale. Every mutation is audit-logged, secrets are masked on read.
"""
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
    EveryticketWebhookFieldCatalogEntry,
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
from app.payments.gateway_config import get_payu_credentials_status, set_payu_credentials
from app.payments.gateways.registry import list_gateway_codes
from app.plans.sanitize import sanitize_description as _sanitize_html
from app.webhooks.field_catalog import AVAILABLE_FIELDS, FIELD_LABELS, FIXED_FIELDS, sanitize_selection
from app.webhooks.payloads import build_webhook_samples

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


def _webhook_field_catalog_out() -> dict[str, list[EveryticketWebhookFieldCatalogEntry]]:
    """Every OPTIONAL field selectable per event, for the Configuration
    screen's per-event checklist (2026-09-14 follow-up) - straight from
    app.webhooks.field_catalog, so this can never drift from what the
    payload builders (app.webhooks.payloads) actually honor."""
    return {
        event_type: [EveryticketWebhookFieldCatalogEntry(field=f, label=FIELD_LABELS[f]) for f in fields]
        for event_type, fields in AVAILABLE_FIELDS.items()
    }


def _webhook_fixed_fields_out() -> dict[str, list[EveryticketWebhookFieldCatalogEntry]]:
    """Every field an event ALWAYS sends, display-only (2026-09-14
    follow-up 2: "activated does not have plan name, code, price... same
    for renewed event there is no plan code, please keep consistency") -
    shown alongside the optional catalog above so every event's full
    field picture is visible at a glance, not just its selectable
    extras."""
    return {
        event_type: [EveryticketWebhookFieldCatalogEntry(field=f, label=FIELD_LABELS[f]) for f in fields]
        for event_type, fields in FIXED_FIELDS.items()
    }


def _integration_out(db: Session, application: Application) -> EveryticketIntegrationOut:
    api_credentials = application.api_credentials or {}
    return EveryticketIntegrationOut(
        secret_key_is_set=bool(application.webhook_secret),
        webhook_url=application.webhook_url,
        retry_limit=application.webhook_retry_limit,
        default_retry_limit=len(get_settings().webhook_retry_schedule),
        escalation_emails=application.webhook_escalation_emails,
        escalation_email_subject=application.webhook_escalation_email_subject,
        escalation_email_body=application.webhook_escalation_email_body,
        archive_after_days=application.archive_after_days,
        # 2026-09-13: moved to app.webhooks.payloads.build_webhook_samples
        # so the admin Testing page's "Test Everyticket webhook" event
        # dropdown can reuse the exact same sample bodies.
        webhook_samples=build_webhook_samples(db, application),
        # 2026-09-14 follow-up 3: the same samples again, but as if every
        # optional field for every event were selected - the frontend
        # filters this down to whatever's currently ticked (even before
        # Save) for an instant live preview, see build_webhook_samples'
        # own docstring for why the frontend never computes a sample
        # VALUE itself, only which of these keys to show.
        webhook_samples_all_fields=build_webhook_samples(
            db, application, selection_override={event_type: fields for event_type, fields in AVAILABLE_FIELDS.items()}
        ),
        # 2026-09-14 follow-up: the full optional catalog (for rendering
        # the checklist) and this application's current, sanitized
        # selection; 2026-09-14 follow-up 2: the complementary always-
        # sent field list per event, so nothing looks "missing".
        webhook_field_catalog=_webhook_field_catalog_out(),
        webhook_fixed_fields=_webhook_fixed_fields_out(),
        webhook_field_selection=sanitize_selection(application.webhook_field_selection),
        # 2026-09-13 follow-up 3: real Everyticket -> this app API
        # credentials, see app.api.v1.integration.
        api_key=api_credentials.get("api_key"),
        api_secret_is_set=bool(api_credentials.get("api_secret")),
    )


def _notification_out(application: Application) -> NotificationConfigOut:
    return NotificationConfigOut(
        notifications_enabled=application.notifications_enabled,
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
    clear secret_key/webhook_url; retry_limit/escalation_*/
    webhook_field_selection are replaced outright when given (they
    aren't secrets - webhook_field_selection is sanitized against
    app.webhooks.field_catalog before being stored, so it can be trusted
    read back out without re-sanitizing again). The custom key/value
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
    # 2026-09-14 follow-up: sanitized before storage (not just on read) so
    # a request built against a stale/wrong catalog can never write an
    # event type or field name app.webhooks.payloads doesn't recognize -
    # see app.webhooks.field_catalog.sanitize_selection.
    application.webhook_field_selection = sanitize_selection(body.webhook_field_selection) or None

    # Everyticket -> this app API credentials (api_key/api_secret), same
    # None=unchanged/""=clear convention as secret_key above. Stored in
    # the existing api_credentials JSON column - reassigned as a new dict
    # rather than mutated in place so SQLAlchemy's change-tracking on a
    # JSON column actually sees the update.
    if body.api_key is not None or body.api_secret is not None:
        creds = dict(application.api_credentials or {})
        if body.api_key is not None:
            if body.api_key:
                creds["api_key"] = body.api_key
            else:
                creds.pop("api_key", None)
        if body.api_secret is not None:
            if body.api_secret:
                creds["api_secret"] = body.api_secret
            else:
                creds.pop("api_secret", None)
        application.api_credentials = creds or None

    db.add(application)
    audit_service.record(
        db, actor=admin.email, action="APPLICATION_CONFIG_UPDATED", entity_type="application",
        entity_id=application.code,
        new_value={
            "group": "integration", "webhook_url": body.webhook_url,
            "secret_key_changed": body.secret_key is not None,
            "retry_limit": body.retry_limit, "escalation_emails": body.escalation_emails,
            "archive_after_days": body.archive_after_days,
            "webhook_field_selection": application.webhook_field_selection,
            "api_key_changed": body.api_key is not None, "api_secret_changed": body.api_secret is not None,
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
    app.notifications.email.service._resolve_settings(). notifications_enabled
    is the one exception to that "override, else fall back" pattern: it's
    a hard stop checked directly in send_templated_email()/send_direct_email()
    before anything else, not a settings override."""
    application.notifications_enabled = body.notifications_enabled
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
            "group": "notification", "notifications_enabled": body.notifications_enabled,
            "smtp_host": body.smtp_host, "smtp_port": body.smtp_port,
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
