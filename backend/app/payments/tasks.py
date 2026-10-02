"""
Celery task wiring for payment background jobs. Thin wrappers - the real
logic lives in app.payments.reconcile and app.payments.events, which are
unit-testable without Celery or a broker.
"""
import logging

from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.payments import events as payment_events
from app.payments import reconcile

logger = logging.getLogger("subscription")


@celery_app.task(name="payments.reconcile_pending")
def reconcile_pending_payments() -> dict[str, int]:
    """Checks stuck PENDING PayU payments against PayU's Verify Payment API
    (see app.payments.reconcile). Idempotent."""
    db = SessionLocal()
    try:
        counts = reconcile.reconcile_pending(db)
        if any(k != "skipped" for k in counts):
            logger.info("Payment reconciliation sweep: %s", counts)
        return counts
    finally:
        db.close()


@celery_app.task(name="payments.purge_old_events")
def purge_old_payment_events() -> int:
    """Deletes payment_events rows past PAYMENT_EVENT_RETENTION_DAYS."""
    db = SessionLocal()
    try:
        deleted = payment_events.purge_old_events(db)
        if deleted:
            logger.info("Purged %d payment events past the retention period", deleted)
        return deleted
    finally:
        db.close()
