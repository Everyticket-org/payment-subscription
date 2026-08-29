"""
Celery task wiring for outbound webhook delivery (spec sections 34-37,
59). The task itself is a thin wrapper - all the real logic (HTTP call,
signing, retry bookkeeping) lives in app/webhooks/service.py's
dispatch_pending(), which is what's actually unit-testable without Celery
or a real broker (see that module's docstring).
"""
import logging

from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.webhooks import service as webhook_service

logger = logging.getLogger("subscription")


@celery_app.task(name="webhooks.dispatch_pending")
def dispatch_pending_webhooks() -> int:
    """Runs on a short interval (see celery_app.py's beat_schedule) and
    attempts every WebhookDelivery that's currently due - either freshly
    PENDING or FAILED with next_retry_at in the past. Idempotent per
    attempt: a delivery already SUCCESS/EXHAUSTED is simply not selected
    again (spec section 28-style idempotency, applied to deliveries)."""
    db = SessionLocal()
    try:
        attempted = webhook_service.dispatch_pending(db)
        if attempted:
            logger.info("Attempted %d pending webhook deliveries", attempted)
        return attempted
    finally:
        db.close()
