"""
Structured domain exceptions (spec section 63).

These are caught by FastAPI exception handlers (see app/main.py) and turned
into a consistent JSON error response. Never let a raw exception/stack trace
reach the client.
"""


class AppError(Exception):
    """Base class for all domain errors. http_status is the default status
    code a FastAPI exception handler should map this to."""

    http_status: int = 400
    error_code: str = "APP_ERROR"

    def __init__(self, message: str | None = None):
        super().__init__(message or self.error_code)
        self.message = message or self.error_code


class CustomerNotFound(AppError):
    http_status = 404
    error_code = "CUSTOMER_NOT_FOUND"


class SubscriptionNotFound(AppError):
    http_status = 404
    error_code = "SUBSCRIPTION_NOT_FOUND"


class PlanNotFound(AppError):
    http_status = 404
    error_code = "PLAN_NOT_FOUND"


class PaymentTransactionNotFound(AppError):
    http_status = 404
    error_code = "PAYMENT_TRANSACTION_NOT_FOUND"


class PaymentFailed(AppError):
    http_status = 402
    error_code = "PAYMENT_FAILED"


class PaymentVerificationFailed(AppError):
    http_status = 402
    error_code = "PAYMENT_VERIFICATION_FAILED"


class DuplicatePayment(AppError):
    http_status = 409
    error_code = "DUPLICATE_PAYMENT"


class InvalidWebhook(AppError):
    http_status = 400
    error_code = "INVALID_WEBHOOK"


class UnauthorizedWebhook(AppError):
    http_status = 401
    error_code = "UNAUTHORIZED_WEBHOOK"


class ProvisioningFailed(AppError):
    http_status = 502
    error_code = "PROVISIONING_FAILED"


class InvalidPlanTransition(AppError):
    http_status = 409
    error_code = "INVALID_PLAN_TRANSITION"


class CustomerAlreadySubscribed(AppError):
    http_status = 409
    error_code = "CUSTOMER_ALREADY_SUBSCRIBED"


class OtpInvalidOrExpired(AppError):
    http_status = 401
    error_code = "OTP_INVALID_OR_EXPIRED"


class OtpRateLimited(AppError):
    http_status = 429
    error_code = "OTP_RATE_LIMITED"


class OtpVerificationRequired(AppError):
    http_status = 403
    error_code = "OTP_VERIFICATION_REQUIRED"


class ConflictingCustomerIdentity(AppError):
    http_status = 409
    error_code = "CONFLICTING_CUSTOMER_IDENTITY"


class NotPermittedInProduction(AppError):
    http_status = 403
    error_code = "NOT_PERMITTED_IN_PRODUCTION"


class Unauthorized(AppError):
    http_status = 401
    error_code = "UNAUTHORIZED"


class Forbidden(AppError):
    http_status = 403
    error_code = "FORBIDDEN"


class ActionNotAllowed(AppError):
    """A subscription action (upgrade/downgrade/cancel/renew) that this
    Application's own admin-configured rules currently disable (spec
    section 13's "Subscription" config group / section 51's System
    Configuration screen) - distinct from Forbidden, which is about WHO is
    calling, not whether the action itself is currently allowed at all."""

    http_status = 403
    error_code = "ACTION_NOT_ALLOWED"


class TrialAlreadyUsed(AppError):
    """This customer has already used a free trial for this application, in
    any subscription status (PENDING_PAYMENT/ACTIVE/EXPIRED/CANCELLED all
    count) - "one credentials can take only one trial lifetime". Raised
    both from an application-level pre-check and from an IntegrityError
    caught around the DB-level partial unique index
    (uq_one_trial_subscription_per_customer_application), so a race between
    two concurrent trial-signup requests for the same customer can only
    ever result in one created subscription, never a raw 500."""

    http_status = 409
    error_code = "TRIAL_ALREADY_USED"


class InvalidPlanConfiguration(AppError):
    """A trial plan (is_trial=True) without a positive trial_period_days,
    a trial plan with a non-zero price, or a non-trial plan with a
    non-positive price (spec follow-up: free trial as a separate,
    configurable-duration plan)."""

    http_status = 422
    error_code = "INVALID_PLAN_CONFIGURATION"


class WebhookAlreadyDelivered(AppError):
    """An admin tried to manually retry a webhook delivery that has
    already SUCCEEDED (spec section 32: "Do not create duplicate
    instances if the activation event is retried") - resending a
    successfully-delivered subscription.activated event risks Everyticket
    provisioning a second museum/instance for the same customer, so this
    is refused rather than silently resetting an already-good delivery
    back to PENDING."""

    http_status = 409
    error_code = "WEBHOOK_ALREADY_DELIVERED"
