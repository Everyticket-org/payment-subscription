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
"""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import Settings

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
) -> None:
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = f"{settings.EMAIL_SENDER_NAME} <{settings.EMAIL_SENDER_ADDRESS}>"
    message["To"] = to
    if settings.EMAIL_REPLY_TO:
        message["Reply-To"] = settings.EMAIL_REPLY_TO

    if text_body:
        message.attach(MIMEText(text_body, "plain"))
    message.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as smtp:
            if settings.SMTP_USE_TLS:
                smtp.starttls()
            if settings.SMTP_USER:
                smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            smtp.sendmail(settings.EMAIL_SENDER_ADDRESS, [to], message.as_string())
    except (smtplib.SMTPException, OSError) as exc:
        raise SMTPSendError(str(exc)) from exc
