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


class NotPermittedInProduction(AppError):
    http_status = 403
    error_code = "NOT_PERMITTED_IN_PRODUCTION"


class Unauthorized(AppError):
    http_status = 401
    error_code = "UNAUTHORIZED"


class Forbidden(AppError):
    http_status = 403
    error_code = "FORBIDDEN"
