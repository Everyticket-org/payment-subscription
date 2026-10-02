"""Shared status/type enums (spec sections 20, 27, 33, 35, 42)."""
import enum


class SubscriptionStatus(str, enum.Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ACTIVE = "ACTIVE"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    # Terminal state past EXPIRED: the customer never renewed within the
    # application's admin-configured archive_after_days window (2026-09
    # follow-up: "delete/archive when user do not renew for x days"). No
    # DB-level enum constraint on the `status` column (plain String(20),
    # see Subscription model), so adding this needed no migration.
    ARCHIVED = "ARCHIVED"


class ProvisioningStatus(str, enum.Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class PaymentStatus(str, enum.Enum):
    INITIATED = "INITIATED"
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class PaymentEventType(str, enum.Enum):
    """app.payments.models.PaymentEvent.event_type - how the event reached us."""
    INITIATED = "INITIATED"  # we built the PayU form (surl/furl recorded)
    BROWSER_RETURN = "BROWSER_RETURN"  # PayU redirected the customer's browser to surl/furl
    WEBHOOK = "WEBHOOK"  # PayU's server-to-server webhook
    STATUS_CHECK = "STATUS_CHECK"  # result page asked for status (only rejected tokens are logged)
    RECONCILE = "RECONCILE"  # our sweep asked PayU's Verify Payment API


class PaymentEventResult(str, enum.Enum):
    """app.payments.models.PaymentEvent.result - what we did with the event."""
    CREATED = "CREATED"
    PROCESSED = "PROCESSED"
    DUPLICATE_IGNORED = "DUPLICATE_IGNORED"
    # A verified SUCCESS for a transaction already FAILED/CANCELLED - money
    # may have been taken with no activation; needs a person to look at it.
    LATE_SUCCESS_IGNORED = "LATE_SUCCESS_IGNORED"
    HASH_FAILED = "HASH_FAILED"
    UNKNOWN_TXN = "UNKNOWN_TXN"
    MISSING_TXNID = "MISSING_TXNID"
    AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
    STILL_PENDING = "STILL_PENDING"
    EXPIRED = "EXPIRED"
    TOKEN_REJECTED = "TOKEN_REJECTED"
    ERROR = "ERROR"


class PaymentType(str, enum.Enum):
    NEW = "NEW"
    RENEWAL = "RENEWAL"
    UPGRADE = "UPGRADE"
    DOWNGRADE = "DOWNGRADE"


class PlanTransitionType(str, enum.Enum):
    UPGRADE = "UPGRADE"
    DOWNGRADE = "DOWNGRADE"


class SubscriptionEventType(str, enum.Enum):
    ACTIVATED = "activated"
    RENEWED = "renewed"
    UPGRADED = "upgraded"
    DOWNGRADED = "downgraded"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    PAYMENT_FAILED = "payment_failed"
    ARCHIVED = "archived"


class WebhookDeliveryStatus(str, enum.Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    EXHAUSTED = "EXHAUSTED"


class FormFieldType(str, enum.Enum):
    TEXT = "text"
    EMAIL = "email"
    PHONE = "phone"
    NUMBER = "number"
    DROPDOWN = "dropdown"
    RADIO = "radio"
    CHECKBOX = "checkbox"
    TEXTAREA = "textarea"
    DATE = "date"
    URL = "url"
    FILE = "file"


class CustomerStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class NotificationChannel(str, enum.Enum):
    EMAIL = "email"


class NotificationStatus(str, enum.Enum):
    SENT = "SENT"
    # Transient send failure that may still be retried automatically -
    # see NotificationLog.next_retry_at and
    # app.notifications.email.service.retry_pending_emails(). Still FAILED
    # once retries are exhausted only if the retry schedule is somehow
    # empty; the normal terminal-after-retries state is EXHAUSTED below.
    FAILED = "FAILED"
    # 2026-09-13 follow-up ("Enable Notifications?" toggle under SMTP
    # configuration): distinct from FAILED - this is never a delivery
    # error, it's the admin having deliberately turned notifications off
    # for this application, so it shouldn't read as something broken.
    SKIPPED = "SKIPPED"
    # Every scheduled retry attempt failed (mirrors WebhookDeliveryStatus.
    # EXHAUSTED) - terminal, next_retry_at is left None, never picked up
    # by retry_pending_emails() again.
    EXHAUSTED = "EXHAUSTED"
