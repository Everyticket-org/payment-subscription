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

Two follow-ups mirroring the existing webhook-delivery subsystem
(app.webhooks.service):

- Global BCC (`Application.notification_bcc_emails`, comma-separated) is
  merged with any per-send `bcc` a caller passes (e.g. the admin Testing
  "Test renewal reminder" tool) and applied to EVERY outgoing email, not
  just templated ones - see `_merged_bcc()`.
- A transient SMTP failure on a plain (no-attachment) templated send is
  now retried automatically on the same kind of backoff schedule webhook
  deliveries use (`EMAIL_RETRY_SCHEDULE_MINUTES`, default matching
  WEBHOOK_RETRY_SCHEDULE_MINUTES) - see `retry_pending_emails()`, wired to
  a Celery beat entry in app.notifications.email.tasks. The initial
  attempt is still made synchronously and inline exactly as before
  (callers' return value/response still reflects THAT first attempt);
  only what happens after a failure changes. Attachment-bearing sends
  (e.g. the invoice PDF) and send_direct_email's ad-hoc content are NOT
  retried - their bytes/content aren't persisted for a later resend - so
  those keep today's single-attempt behavior unchanged.
"""
import logging
from datetime import datetime, timedelta, timezone

from jinja2 import Template
from sqlalchemy.orm import Session

from app.applications.models import Application
from app.core.config import get_settings
from app.core.enums import NotificationStatus
from app.notifications.email.providers.smtp import provider as smtp_provider
from app.notifications.email.providers.smtp.provider import SMTPSendError
from app.notifications.models import NotificationLog, NotificationTemplate

logger = logging.getLogger("subscription")


def _merged_bcc(application: Application | None, extra_bcc: list[str] | None) -> list[str] | None:
    """This application's global notification_bcc_emails (Configuration ->
    Notifications) plus whatever one-off `bcc` the caller passed,
    deduplicated (order preserved, global addresses first). None when the
    combined list is empty, so callers/providers don't need to
    special-case an empty list vs. no bcc at all."""
    global_bcc: list[str] = []
    if application is not None and application.notification_bcc_emails:
        global_bcc = [addr.strip() for addr in application.notification_bcc_emails.split(",") if addr.strip()]
    merged = list(dict.fromkeys([*global_bcc, *(extra_bcc or [])]))
    return merged or None


def _next_retry_at(schedule: list[int], attempt_count: int) -> tuple[str, "datetime | None"]:
    """Same convention as app.webhooks.service._attempt_one's failure
    branch: `attempt_count` is 1 after the first attempt, so
    `schedule[attempt_count - 1]` is the delay before the NEXT attempt.
    Once attempt_count exceeds the schedule's length, every retry has
    been used up - terminal EXHAUSTED, next_retry_at cleared."""
    if attempt_count <= len(schedule):
        delay_minutes = schedule[attempt_count - 1]
        return NotificationStatus.FAILED.value, datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)
    return NotificationStatus.EXHAUSTED.value, None


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
    bcc: list[str] | None = None,
) -> bool:
    """Same SMTP-send + NotificationLog bookkeeping as send_templated_email()
    below, but for admin-composed content that is not a NotificationTemplate
    DB row - e.g. the webhook-delivery-exhausted escalation email (2026-09
    admin config restructure), whose subject/body are edited directly on
    the Everyticket Integration config screen ("Email content as editor")
    rather than managed as a template on the separate Notifications page.
    `template_code` here is just a label for the NotificationLog row (for
    visibility on the admin Notifications/logs page), not a lookup key -
    never raises, same as send_templated_email().

    `bcc` is merged with this application's global notification_bcc_emails
    the same way send_templated_email() does - see _merged_bcc(). Unlike
    send_templated_email(), a failure here is NEVER auto-retried: this
    content is ad-hoc (not a stored template + context this module could
    re-render later), so a failed direct email just stays FAILED, same as
    before this session's retry support was added."""
    settings = _resolve_settings(application)
    application_id = application.id if application is not None else None
    effective_bcc = _merged_bcc(application, bcc)

    if application is not None and not application.notifications_enabled:
        logger.info("send_direct_email(%s): notifications disabled for this application, skipping", template_code)
        _log(
            db, template_code=template_code, to=to, status=NotificationStatus.SKIPPED.value,
            provider_response="Notifications are disabled for this application (Configuration > Notifications)",
            related_entity_type=related_entity_type, related_entity_id=related_entity_id,
            application_id=application_id, bcc=effective_bcc,
        )
        return False

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
            application_id=application_id, bcc=effective_bcc,
        )
        return False

    try:
        smtp_provider.send(settings, to=to, subject=subject, html_body=body_html, text_body=text_body, bcc=effective_bcc)
    except SMTPSendError as exc:
        logger.warning("send_direct_email(%s) to %s failed: %s", template_code, to, exc)
        _log(
            db, template_code=template_code, to=to, status=NotificationStatus.FAILED.value,
            provider_response=str(exc)[:2000],
            related_entity_type=related_entity_type, related_entity_id=related_entity_id,
            application_id=application_id, bcc=effective_bcc,
        )
        return False

    _log(
        db, template_code=template_code, to=to, status=NotificationStatus.SENT.value,
        provider_response=None,
        related_entity_type=related_entity_type, related_entity_id=related_entity_id,
        application_id=application_id, bcc=effective_bcc,
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
    bcc: list[str] | None = None,
) -> bool:
    """Looks up an active NotificationTemplate by code, renders it with
    Jinja2 against `context`, sends it via the configured provider, and
    always writes+commits a NotificationLog row (SENT or FAILED). Returns
    True iff it actually sent. Never raises.

    `attachments`, if given, is a list of (filename, content_bytes,
    mime_subtype) tuples - e.g. the invoice PDF (spec section 45). Only
    the smtp provider path uses it today.

    `bcc`, if given, is a list of extra addresses (e.g. a plan's renewal
    reminder distribution list) blind-copied on the send, merged with this
    application's global notification_bcc_emails (Configuration ->
    Notifications) - see _merged_bcc(). See smtp_provider.send()'s
    docstring for why these go on the envelope recipient list rather than
    a `Bcc:` header.

    A transient SMTP failure (SMTPSendError) is automatically retried
    later, PROVIDED `attachments` is None - see module docstring and
    retry_pending_emails() below. Every other failure branch here (no
    active template, a template that fails to render, an unsupported
    EMAIL_PROVIDER, notifications disabled) is not a transient delivery
    problem retrying would fix, so those stay single-attempt as before.

    `application`, if given, overrides EMAIL_PROVIDER/EMAIL_SENDER_NAME/
    EMAIL_SENDER_ADDRESS/EMAIL_REPLY_TO from that Application row's own
    config (spec section 51's Notification Configuration screen) for any
    field it has actually set, falling back to the global Settings
    otherwise - same per-application-override-else-global-default
    pattern app.sso.service and app.webhooks.service already use for
    sso_secret/webhook_secret. Built via settings.model_copy(), never by
    mutating the process-wide cached Settings singleton.

    `application.notifications_enabled` (2026-09-13 follow-up: "Enable
    Notifications?" under SMTP configuration) is checked first and is a
    hard stop, not an override - when it's False, nothing below this
    (template lookup, rendering, the SMTP call itself) ever runs, and the
    NotificationLog row is written as SKIPPED, not FAILED, so an admin
    who deliberately turned this off doesn't see a wall of "failures" in
    the logs."""
    settings = _resolve_settings(application)
    application_id = application.id if application is not None else None
    effective_bcc = _merged_bcc(application, bcc)
    # Attachment bytes aren't persisted anywhere for a later retry to
    # reuse (unlike `context`, which is a small JSON-safe dict) - so an
    # attachment-bearing send never gets next_retry_at set, regardless of
    # attempt_count/schedule below.
    retryable = attachments is None

    if application is not None and not application.notifications_enabled:
        logger.info("send_templated_email(%s): notifications disabled for this application, skipping", template_code)
        _log(
            db, template_code=template_code, to=to or "", status=NotificationStatus.SKIPPED.value,
            provider_response="Notifications are disabled for this application (Configuration > Notifications)",
            related_entity_type=related_entity_type, related_entity_id=related_entity_id,
            application_id=application_id, context=context, bcc=effective_bcc,
        )
        return False

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
            application_id=application_id, context=context, bcc=effective_bcc,
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
            application_id=application_id, context=context, bcc=effective_bcc,
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
            application_id=application_id, context=context, bcc=effective_bcc,
        )
        return False

    try:
        smtp_provider.send(
            settings, to=to, subject=subject, html_body=html_body, text_body=text_body,
            attachments=attachments, bcc=effective_bcc,
        )
    except SMTPSendError as exc:
        logger.warning("send_templated_email(%s) to %s failed: %s", template_code, to, exc)
        status = NotificationStatus.FAILED.value
        next_retry_at = None
        if retryable:
            status, next_retry_at = _next_retry_at(settings.email_retry_schedule, attempt_count=1)
        _log(
            db, template_code=template_code, to=to, status=status,
            provider_response=str(exc)[:2000],
            related_entity_type=related_entity_type, related_entity_id=related_entity_id,
            application_id=application_id, context=context, bcc=effective_bcc, next_retry_at=next_retry_at,
        )
        return False

    _log(
        db, template_code=template_code, to=to, status=NotificationStatus.SENT.value,
        provider_response=None,
        related_entity_type=related_entity_type, related_entity_id=related_entity_id,
        application_id=application_id, context=context, bcc=effective_bcc,
    )
    return True


def retry_pending_emails(db: Session, *, limit: int = 50) -> int:
    """Mirrors app.webhooks.service.dispatch_pending(): finds every
    NotificationLog row that's FAILED with a due next_retry_at (only ever
    set by send_templated_email() above for a retryable, transient SMTP
    failure) and re-attempts it, recomputing settings/template/BCC fresh
    from CURRENT config rather than reusing anything from the original
    attempt other than the stored recipient/context. Called from a Celery
    beat entry (app.notifications.email.tasks) on the same short interval
    the webhook retry sweep uses. Returns how many rows were attempted -
    a SUCCESS/EXHAUSTED/SKIPPED row is simply never selected again."""
    now = datetime.now(timezone.utc)
    due = (
        db.query(NotificationLog)
        .filter(
            NotificationLog.status == NotificationStatus.FAILED.value,
            NotificationLog.next_retry_at.isnot(None),
            NotificationLog.next_retry_at <= now,
        )
        .order_by(NotificationLog.next_retry_at.asc())
        .limit(limit)
        .all()
    )
    for log in due:
        _retry_one(db, log)
    return len(due)


def _retry_one(db: Session, log: NotificationLog) -> None:
    application = db.get(Application, log.application_id) if log.application_id else None
    settings = _resolve_settings(application)

    if application is not None and not application.notifications_enabled:
        log.status = NotificationStatus.SKIPPED.value
        log.provider_response = "Notifications are disabled for this application (Configuration > Notifications)"
        log.next_retry_at = None
        db.commit()
        return

    template = (
        db.query(NotificationTemplate)
        .filter(NotificationTemplate.template_code == log.template_code, NotificationTemplate.active.is_(True))
        .first()
    )
    if template is None:
        logger.warning("retry_pending_emails(%s): no active template configured, giving up", log.template_code)
        log.status = NotificationStatus.FAILED.value
        log.provider_response = "No active NotificationTemplate configured for this code"
        log.next_retry_at = None
        db.commit()
        return

    context = log.context or {}
    try:
        subject = Template(template.subject).render(**context)
        html_body = Template(template.body_html).render(**context)
        text_body = Template(template.body_text).render(**context) if template.body_text else None
    except Exception as exc:  # pragma: no cover - defensive, same as the initial-send path above
        logger.exception("retry_pending_emails(%s): template render failed", log.template_code)
        log.status = NotificationStatus.FAILED.value
        log.provider_response = f"Template render error: {exc}"
        log.next_retry_at = None
        db.commit()
        return

    bcc = _merged_bcc(application, log.bcc)
    attempt_count = log.attempt_count + 1
    try:
        smtp_provider.send(settings, to=log.recipient, subject=subject, html_body=html_body, text_body=text_body, bcc=bcc)
    except SMTPSendError as exc:
        logger.warning("retry_pending_emails(%s) to %s: attempt %d failed: %s", log.template_code, log.recipient, attempt_count, exc)
        log.attempt_count = attempt_count
        log.status, log.next_retry_at = _next_retry_at(settings.email_retry_schedule, attempt_count)
        log.provider_response = str(exc)[:2000]
        db.commit()
        return

    log.attempt_count = attempt_count
    log.status = NotificationStatus.SENT.value
    log.provider_response = None
    log.next_retry_at = None
    db.commit()


def _log(
    db: Session, *, template_code: str, to: str, status: str, provider_response: str | None,
    related_entity_type: str | None, related_entity_id: str | None,
    application_id: int | None = None, context: dict | None = None, bcc: list[str] | None = None,
    next_retry_at: "datetime | None" = None,
) -> NotificationLog:
    log = NotificationLog(
        template_code=template_code,
        channel="email",
        recipient=to,
        status=status,
        provider_response=provider_response,
        related_entity_type=related_entity_type,
        related_entity_id=related_entity_id,
        application_id=application_id,
        context=context,
        bcc=bcc,
        attempt_count=1,
        next_retry_at=next_retry_at,
    )
    db.add(log)
    db.commit()
    return log
