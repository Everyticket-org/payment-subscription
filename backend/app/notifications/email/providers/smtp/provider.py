"""
SMTP email provider (spec sections 49-50) - the one EMAIL_PROVIDER value
this app implements today ("smtp"); a future provider (SES, SendGrid...)
would live alongside this as a sibling module behind the same send()
signature, selected in app/notifications/email/service.py by
settings.EMAIL_PROVIDER.

Uses Python's stdlib smtplib/email - no extra dependency needed. Works
against any real SMTP server, and just as well against a local dev
catch-all like MailHog/Mailpit (SMTP_HOST=localhost, SMTP_PORT=1025,
matching this app's existing SMTP_* defaults) so email can be seen
without ever sending anything real in development.

2026-09-13 bugfix ("Test email not going even after configured correctly
SMTP" -> provider_response came back "timed out"): this previously always
opened a plaintext smtplib.SMTP connection and, only if smtp_use_tls was
on, upgraded it with STARTTLS - the port-587-style flow. Port 465 (used
by Gmail, Office365, and most hosting-provider SMTP-over-SSL setups) is
a DIFFERENT convention: the server expects a TLS handshake immediately
on connect ("implicit SSL"), and speaks nothing in plaintext first - so
smtplib.SMTP against port 465 just sits waiting for a plaintext banner
that never comes, until it times out. That is almost certainly what
"timed out" means here if SMTP_PORT is 465. Now: port 465 always goes
through smtplib.SMTP_SSL (implicit SSL) regardless of the use_tls
toggle; every other port keeps the existing plain-then-optional-STARTTLS
behavior unchanged.
"""
import logging
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import Settings

# Implicit-SSL SMTP port (Gmail, Office365, and most hosting providers'
# "SSL" mode) - the client must open a TLS connection immediately, unlike
# STARTTLS ports (587, 25) where the conversation starts in plaintext and
# upgrades in-band. Not configurable today; matches the near-universal
# real-world convention (mirrors Django's/other frameworks' EMAIL_USE_SSL
# port-465 default) rather than adding a second admin-facing toggle for a
# single well-known port.
SMTP_SSL_PORT = 465

logger = logging.getLogger("subscription")


class SMTPSendError(RuntimeError):
    """Raised when the SMTP conversation itself fails (connection
    refused, auth failure, etc.) - distinct from "no template configured"
    or other application-level email errors."""


def send(
    settings: Settings,
    *,
    to: str,
    subject: str,
    html_body: str,
    text_body: str | None = None,
    attachments: list[tuple[str, bytes, str]] | None = None,
) -> None:
    """`attachments` is a list of (filename, content_bytes, mime_subtype)
    tuples, e.g. ("invoice.pdf", pdf_bytes, "pdf") - used for the invoice
    PDF email (spec section 45). Optional; most templates send none."""
    message = MIMEMultipart("mixed" if attachments else "alternative")
    message["Subject"] = subject
    message["From"] = f"{settings.EMAIL_SENDER_NAME} <{settings.EMAIL_SENDER_ADDRESS}>"
    message["To"] = to
    if settings.EMAIL_REPLY_TO:
        message["Reply-To"] = settings.EMAIL_REPLY_TO

    if attachments:
        # A "mixed" root with an "alternative" body part is the standard
        # shape for a plain/html body plus one or more attachments.
        body_part = MIMEMultipart("alternative")
        if text_body:
            body_part.attach(MIMEText(text_body, "plain"))
        body_part.attach(MIMEText(html_body, "html"))
        message.attach(body_part)
        for filename, content, subtype in attachments:
            part = MIMEApplication(content, _subtype=subtype)
            part.add_header("Content-Disposition", "attachment", filename=filename)
            message.attach(part)
    else:
        if text_body:
            message.attach(MIMEText(text_body, "plain"))
        message.attach(MIMEText(html_body, "html"))

    try:
        if settings.SMTP_PORT == SMTP_SSL_PORT:
            with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as smtp:
                if settings.SMTP_USER:
                    smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                smtp.sendmail(settings.EMAIL_SENDER_ADDRESS, [to], message.as_string())
        else:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as smtp:
                if settings.SMTP_USE_TLS:
                    smtp.starttls()
                if settings.SMTP_USER:
                    smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                smtp.sendmail(settings.EMAIL_SENDER_ADDRESS, [to], message.as_string())
    except (smtplib.SMTPException, OSError, TimeoutError) as exc:
        raise SMTPSendError(str(exc)) from exc
