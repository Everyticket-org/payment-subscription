"""
SQLAlchemy engine/session setup + declarative base + created_at/updated_at mixin.
"""
from datetime import datetime, timezone

from sqlalchemy import create_engine, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.core.config import get_settings

settings = get_settings()

# pool_size/max_overflow explicit rather than SQLAlchemy's defaults
# (5 + 10 = 15 total): a handful of admin requests that each hold a
# connection open for several seconds - e.g. the Webhook Logs "Attempt"/
# "Verify connectivity" actions, which make a real synchronous outbound
# HTTP call before returning (app/webhooks/service.py) - can otherwise
# exhaust the default pool and make every OTHER concurrent request
# (including totally unrelated admin pages) block for up to
# pool_timeout waiting on a connection, which is what "all API get
# freezed in admin panel" (Vishal, 2026-09-11) turned out to mean. This
# raises the ceiling so a few slow outbound calls can't starve the rest
# of the app; app/webhooks/service.py's own tightened per-call HTTP
# timeout is what actually bounds how long each one can hold a
# connection for in the first place.
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    """created_at / updated_at, present on every business table (spec section 57)."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


def get_db():
    """FastAPI dependency - yields a DB session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
