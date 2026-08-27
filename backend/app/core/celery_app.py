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
        # "app.webhooks.tasks",
        # "app.notifications.email.tasks",
        # "app.subscriptions.tasks",
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
)
