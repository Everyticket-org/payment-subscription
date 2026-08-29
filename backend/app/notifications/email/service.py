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

from app.core.config import get_settings
from app.core.enums import NotificationStatus
from app.notifications.email.providers.smtp import provider as smtp_provider
from app.notifications.email.providers.smtp.provider import SMTPSendError
from app.notifications.models import NotificationLog, NotificationTemplate

logger = logging.getLogger("subscription")


def send_templated_email(
    db: Session,
    *,
    template_code: str,
    to: str | None,
    context: dict,
    related_entity_type: str | None = None,
    related_entity_id: str | None = None,
) -> bool:
    """Looks up an active NotificationTemplate by code, renders it with
    Jinja2 against `context`, sends it via the configured provider, and
    always writes+commits a NotificationLog row (SENT or FAILED). Returns
    True iff it actually sent. Never raises."""
    settings = get_settings()

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
        smtp_provider.send(settings, to=to, subject=subject, html_body=html_body, text_body=text_body)
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
