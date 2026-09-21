"""Email templates + send log (spec sections 49-50)."""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, TimestampMixin
from app.core.enums import NotificationChannel


class NotificationTemplate(Base, TimestampMixin):
    __tablename__ = "notification_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(20), default=NotificationChannel.EMAIL.value, nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    # 2026-09-13 follow-up ("change database to mysql"): plain String
    # (unbounded VARCHAR) is valid on Postgres/SQLite but MySQL requires
    # every VARCHAR to have an explicit length - Text is the correct type
    # here regardless of dialect anyway (this holds arbitrarily long
    # rendered HTML/plain-text email bodies, not a short bounded field).
    body_html: Mapped[str] = mapped_column(Text, nullable=False)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class NotificationLog(Base, TimestampMixin):
    __tablename__ = "notification_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    recipient: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # NotificationStatus value
    provider_response: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    related_entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    related_entity_id: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)

    # --- Retry bookkeeping (mirrors WebhookDelivery's attempt_count/
    # next_retry_at) - only ever populated for a plain (no-attachment)
    # templated send; see app.notifications.email.service.
    # send_templated_email()/retry_pending_emails(). application_id/
    # context/bcc are what a later retry needs to reconstruct and resend
    # the exact same email without the original caller's context still
    # being in scope. ---
    application_id: Mapped[int | None] = mapped_column(ForeignKey("applications.id"), nullable=True, index=True)
    context: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # Jinja2 render context used for this send
    bcc: Mapped[list | None] = mapped_column(JSON, nullable=True)  # per-send bcc list (global bcc is re-merged fresh on retry)
    attempt_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # None = no retry scheduled (SENT, SKIPPED, a non-transient FAILED, or
    # EXHAUSTED) - only set on a transient SMTP failure for a retryable
    # send. Indexed: this is the column retry_pending_emails() sweeps on.
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
