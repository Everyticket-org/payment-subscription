"""
Celery application instance for background jobs (spec section 59):
webhook retry, email sending, expiry processing, renewal processing, etc.

Individual task modules register themselves via `include=[...]` below as
they're implemented; each task must be idempotent.
"""
from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "subscription",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.webhooks.tasks",
        "app.subscriptions.tasks",
        # "app.notifications.email.tasks",  # lands with the email service
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone=settings.TIMEZONE,
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    # Both tasks below are cheap, idempotent sweeps over "what's due right
    # now" (see their own modules) - safe to run frequently and safe to
    # run more than once if a beat tick is ever missed or doubled.
    beat_schedule={
        "dispatch-pending-webhooks": {
            "task": "webhooks.dispatch_pending",
            "schedule": 60.0,  # seconds - matches the shortest WEBHOOK_RETRY_SCHEDULE_MINUTES step
        },
        "expire-due-subscriptions": {
            "task": "subscriptions.expire_due",
            "schedule": 300.0,  # seconds - expiry isn't time-critical to the minute
        },
    },
)
