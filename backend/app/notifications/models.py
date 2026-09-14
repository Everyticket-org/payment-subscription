"""Email templates + send log (spec sections 49-50)."""
from sqlalchemy import Boolean, Integer, String, Text
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
