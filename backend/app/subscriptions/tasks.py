"""
Celery task wiring for subscription expiry (spec section 40, 59). The
task is a thin wrapper - the real logic lives in
app/subscriptions/service.py's expire_due_subscriptions().
"""
import logging

from app.core.celery_app import celery_app
from app.core.database import SessionLocal
from app.subscriptions import service as subscription_service

logger = logging.getLogger("subscription")


@celery_app.task(name="subscriptions.expire_due")
def expire_due_subscriptions() -> int:
    """Runs periodically (see celery_app.py's beat_schedule) and flips
    every ACTIVE subscription whose expires_at has passed to EXPIRED,
    queuing a subscription.expired webhook event for each."""
    db = SessionLocal()
    try:
        expired = subscription_service.expire_due_subscriptions(db)
        if expired:
            logger.info("Expired %d subscriptions past their expiry date", expired)
        return expired
    finally:
        db.close()


@celery_app.task(name="subscriptions.send_renewal_reminders")
def send_renewal_reminders() -> int:
    """Runs periodically (see celery_app.py's beat_schedule) and emails
    every ACTIVE subscription expiring soon (spec section 49)."""
    db = SessionLocal()
    try:
        sent = subscription_service.send_renewal_reminders(db)
        if sent:
            logger.info("Sent %d renewal reminder emails", sent)
        return sent
    finally:
        db.close()


@celery_app.task(name="subscriptions.archive_stale")
def archive_stale_subscriptions() -> int:
    """Runs periodically (see celery_app.py's beat_schedule) and flips
    every EXPIRED subscription past its application's admin-configured
    archive_after_days into ARCHIVED, queuing a subscription.archived
    webhook event for each (2026-09 follow-up: "delete/archive when user
    do not renew for x days")."""
    db = SessionLocal()
    try:
        archived = subscription_service.archive_stale_subscriptions(db)
        if archived:
            logger.info("Archived %d subscriptions past their application's archive_after_days", archived)
        return archived
    finally:
        db.close()
