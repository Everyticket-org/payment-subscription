"""
Email orchestration (spec sections 49-50): template lookup + Jinja2
rendering + provider dispatch + NotificationLog write.

Every call here is best-effort and NEVER raises - a broken/unreachable
SMTP server must never break the customer-facing action that triggered
the email (OTP issuance, payment confirmation, cancellation, ...); it
just shows up as a FAILED row in notification_logs for an admin to
notice (a future admin Testing/log-viewing module, or direct DB
inspection today - see docs/implementation-status.md).

Callers should invoke this AFTER their own primary transaction commits,
never inside it (spec section 58: no external call - and an SMTP send is
exactly that - held open inside a financial-transaction commit). This
module commits its own NotificationLog row independently for that reason.
"""
import logging

from jinja2 import Template
from sqlalchemy.orm import Session

from app.applications.models import Application
from app.core.config import get_settings
from app.core.enums import NotificationStatus
from app.notifications.email.providers.smtp import provider as smtp_provider
from app.notifications.email.providers.smtp.provider import SMTPSendError
from app.notifications.models import NotificationLog, NotificationTemplate

logger = logging.getLogger("subscription")


def _resolve_settings(application: Application | None):
    """EMAIL_PROVIDER/EMAIL_SENDER_NAME/EMAIL_SENDER_ADDRESS/EMAIL_REPLY_TO,
    plus (2026-09 admin config restructure) SMTP_HOST/PORT/USER/PASSWORD/
    USE_TLS, all overridden per-application when that Application row has
    them set, falling back to the global Settings otherwise - built via
    settings.model_copy(), never by mutating the process-wide cached
    Settings singleton. Shared by send_templated_email() and
    send_direct_email() below."""
    settings = get_settings()
    if application is None:
        return settings

    overrides = {
        key: value
        for key, value in (
            ("EMAIL_PROVIDER", application.email_provider),
            ("EMAIL_SENDER_NAME", application.email_sender_name),
            ("EMAIL_SENDER_ADDRESS", application.email_sender_address),
            ("EMAIL_REPLY_TO", application.email_reply_to),
            ("SMTP_HOST", application.smtp_host),
            ("SMTP_PORT", application.smtp_port),
            ("SMTP_USER", application.smtp_username),
            ("SMTP_PASSWORD", application.smtp_password),
        )
        if value
    }
    # Boolean override needs its own check - `if value` above would skip
    # an explicit `False` (e.g. an admin turning TLS off).
    if application.smtp_use_tls is not None:
        overrides["SMTP_USE_TLS"] = application.smtp_use_tls

    return settings.model_copy(update=overrides) if overrides else settings


def send_direct_email(
    db: Session,
    *,
    to: str,
    subject: str,
    body_html: str,
    text_body: str | None = None,
    template_code: str = "direct",
    related_entity_type: str | None = None,
    related_entity_id: str | None = None,
    application: Application | None = None,
) -> bool:
    """Same SMTP-send + NotificationLog bookkeeping as send_templated_email()
    below, but for admin-composed content that is not a NotificationTemplate
    DB row - e.g. the webhook-delivery-exhausted escalation email (2026-09
    admin config restructure), whose subject/body are edited directly on
    the Everyticket Integration config screen ("Email content as editor")
    rather than managed as a template on the separate Notifications page.
    `template_code` here is just a label for the NotificationLog row (for
    visibility on the admin Notifications/logs page), not a lookup key -
    never raises, same as send_templated_email()."""
    settings = _resolve_settings(application)

    if not to:
        logger.info("send_direct_email(%s): no recipient address, skipping", template_code)
        return False

    if settings.EMAIL_PROVIDER != "smtp":
        logger.warning(
            "send_direct_email(%s): unsupported EMAIL_PROVIDER=%r, skipping", template_code, settings.EMAIL_PROVIDER
        )
        _log(
            db, template_code=template_code, to=to, status=NotificationStatus.FAILED.value,
            provider_response=f"Unsupported EMAIL_PROVIDER: {settings.EMAIL_PROVIDER}",
            related_entity_type=related_entity_type, related_entity_id=related_entity_id,
        )
        return False

    try:
        smtp_provider.send(settings, to=to, subject=subject, html_body=body_html, text_body=text_body)
    except SMTPSendError as exc:
        logger.warning("send_direct_email(%s) to %s failed: %s", template_code, to, exc)
        _log(
            db, template_code=template_code, to=to, status=NotificationStatus.FAILED.value,
            provider_response=str(exc)[:2000],
            related_entity_type=related_entity_type, related_entity_id=related_entity_id,
        )
        return False

    _log(
        db, template_code=template_code, to=to, status=NotificationStatus.SENT.value,
        provider_response=None,
        related_entity_type=related_entity_type, related_entity_id=related_entity_id,
    )
    return True


def send_templated_email(
    db: Session,
    *,
    template_code: str,
    to: str | None,
    context: dict,
    related_entity_type: str | None = None,
    related_entity_id: str | None = None,
    attachments: list[tuple[str, bytes, str]] | None = None,
    application: Application | None = None,
) -> bool:
    """Looks up an active NotificationTemplate by code, renders it with
    Jinja2 against `context`, sends it via the configured provider, and
    always writes+commits a NotificationLog row (SENT or FAILED). Returns
    True iff it actually sent. Never raises.

    `attachments`, if given, is a list of (filename, content_bytes,
    mime_subtype) tuples - e.g. the invoice PDF (spec section 45). Only
    the smtp provider path uses it today.

    `application`, if given, overrides EMAIL_PROVIDER/EMAIL_SENDER_NAME/
    EMAIL_SENDER_ADDRESS/EMAIL_REPLY_TO from that Application row's own
    config (spec section 51's Notification Configuration screen) for any
    field it has actually set, falling back to the global Settings
    otherwise - same per-application-override-else-global-default
    pattern app.sso.service and app.webhooks.service already use for
    sso_secret/webhook_secret. Built via settings.model_copy(), never by
    mutating the process-wide cached Settings singleton."""
    settings = _resolve_settings(application)

    if not to:
        logger.info("send_templated_email(%s): no recipient address, skipping", template_code)
        return False

    template = (
        db.query(NotificationTemplate)
        .filter(NotificationTemplate.template_code == template_code, NotificationTemplate.active.is_(True))
        .first()
    )
    if template is None:
        logger.warning("send_templated_email(%s): no active template configured, skipping", template_code)
        _log(
            db, template_code=template_code, to=to, status=NotificationStatus.FAILED.value,
            provider_response="No active NotificationTemplate configured for this code",
            related_entity_type=related_entity_type, related_entity_id=related_entity_id,
        )
        return False

    try:
        subject = Template(template.subject).render(**context)
        html_body = Template(template.body_html).render(**context)
        text_body = Template(template.body_text).render(**context) if template.body_text else None
    except Exception as exc:  # pragma: no cover - defensive: a malformed template must not 500 the caller
        logger.exception("send_templated_email(%s): template render failed", template_code)
        _log(
            db, template_code=template_code, to=to, status=NotificationStatus.FAILED.value,
            provider_response=f"Template render error: {exc}",
            related_entity_type=related_entity_type, related_entity_id=related_entity_id,
        )
        return False

    if settings.EMAIL_PROVIDER != "smtp":
        logger.warning(
            "send_templated_email(%s): unsupported EMAIL_PROVIDER=%r, skipping", template_code, settings.EMAIL_PROVIDER
        )
        _log(
            db, template_code=template_code, to=to, status=NotificationStatus.FAILED.value,
            provider_response=f"Unsupported EMAIL_PROVIDER: {settings.EMAIL_PROVIDER}",
            related_entity_type=related_entity_type, related_entity_id=related_entity_id,
        )
        return False

    try:
        smtp_provider.send(
            settings, to=to, subject=subject, html_body=html_body, text_body=text_body, attachments=attachments
        )
    except SMTPSendError as exc:
        logger.warning("send_templated_email(%s) to %s failed: %s", template_code, to, exc)
        _log(
            db, template_code=template_code, to=to, status=NotificationStatus.FAILED.value,
            provider_response=str(exc)[:2000],
            related_entity_type=related_entity_type, related_entity_id=related_entity_id,
        )
        return False

    _log(
        db, template_code=template_code, to=to, status=NotificationStatus.SENT.value,
        provider_response=None,
        related_entity_type=related_entity_type, related_entity_id=related_entity_id,
    )
    return True


def _log(
    db: Session, *, template_code: str, to: str, status: str, provider_response: str | None,
    related_entity_type: str | None, related_entity_id: str | None,
) -> None:
    db.add(
        NotificationLog(
            template_code=template_code,
            channel="email",
            recipient=to,
            status=status,
            provider_response=provider_response,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
        )
    )
    db.commit()
