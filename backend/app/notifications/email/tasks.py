"""
Celery task wiring for outbound-email retry, mirroring
app/webhooks/tasks.py exactly. The task itself is a thin wrapper - all
the real logic (finding due rows, re-rendering, re-sending, backoff
bookkeeping) lives in app.notifications.email.service.retry_pending_emails(),
which is what's actually unit-testable without Celery or a real broker.
"""
import logging

from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.notifications.email import service as email_service

logger = logging.getLogger("subscription")


@celery_app.task(name="notifications.email.retry_pending")
def retry_pending_emails() -> int:
    """Runs on a short interval (see celery_app.py's beat_schedule) and
    re-attempts every NotificationLog row that's currently due - FAILED
    with next_retry_at in the past. Idempotent per attempt: a row already
    SENT/SKIPPED/EXHAUSTED is simply not selected again."""
    db = SessionLocal()
    try:
        attempted = email_service.retry_pending_emails(db)
        if attempted:
            logger.info("Retried %d pending email(s)", attempted)
        return attempted
    finally:
        db.close()
