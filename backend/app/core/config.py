"""
Central application configuration.

All secrets/sensitive values are read from environment variables (see
.env.example). Non-secret business configuration (allowed plan transitions,
webhook retry schedule, etc.) also has sane defaults here but is intended to
be overridable via the `system_settings` table / Application config model at
runtime - this Settings object covers process-level / infra-level config only.
"""
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- General ---
    ENVIRONMENT: str = "development"  # development | staging | production
    APP_NAME: str = "Everyticket Subscription Platform"
    APP_URL: str = "http://localhost:8000"
    TIMEZONE: str = "Asia/Kolkata"
    CURRENCY: str = "INR"

    # --- Database ---
    DATABASE_URL: str = "postgresql+psycopg2://subscription:subscription@localhost:5432/subscription"

    # --- Redis / Celery ---
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # --- Auth / Security ---
    JWT_SECRET: str = "change-me-dev-only-do-not-use-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # --- SSO ---
    SSO_SECRET: str = "change-me-dev-only-sso-secret"
    SSO_TOKEN_TTL_SECONDS: int = 120

    # --- OTP ---
    OTP_LENGTH: int = 6
    OTP_EXPIRY_SECONDS: int = 300
    OTP_MAX_ATTEMPTS: int = 5
    OTP_RESEND_COOLDOWN_SECONDS: int = 60

    # --- Test-mode safety switches ---
    ALLOW_OTP_BYPASS: bool = False
    ALLOW_ADMIN_MFA_BYPASS: bool = False
    TEST_MODE: bool = False

    # --- Email ---
    EMAIL_PROVIDER: str = "smtp"
    SMTP_HOST: str = "localhost"
    SMTP_PORT: int = 1025
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_TLS: bool = False
    EMAIL_SENDER_NAME: str = "Everyticket Subscriptions"
    EMAIL_SENDER_ADDRESS: str = "no-reply@example.com"
    EMAIL_REPLY_TO: str = "support@example.com"

    # --- Payments ---
    DEFAULT_PAYMENT_GATEWAY: str = "mock"
    PAYMENT_GATEWAY_MODE: str = "test"

    PAYU_MERCHANT_KEY: str = ""
    PAYU_MERCHANT_SALT: str = ""
    PAYU_BASE_URL: str = "https://test.payu.in"
    PAYU_SUCCESS_URL: str = "http://localhost:8000/api/v1/payment/payu/callback/success"
    PAYU_FAILURE_URL: str = "http://localhost:8000/api/v1/payment/payu/callback/failure"

    # --- Everyticket ---
    EVERYTICKET_API_URL: str = "http://localhost:9000/api"
    EVERYTICKET_API_KEY: str = "change-me-everyticket-api-key"
    EVERYTICKET_WEBHOOK_URL: str = "http://localhost:9000/webhooks/subscription"
    EVERYTICKET_WEBHOOK_SECRET: str = "change-me-everyticket-webhook-secret"

    # --- Webhook delivery ---
    WEBHOOK_RETRY_SCHEDULE_MINUTES: str = "5,15,60,360,1440"

    # --- Renewal reminders (spec section 49) ---
    RENEWAL_REMINDER_DAYS_BEFORE: int = 3

    # --- Frontend ---
    FRONTEND_URL: str = "http://localhost:5173"  # Vite dev server default
    # Comma-separated list of origins allowed to call the API from a
    # browser (spec section 77's React frontend, run separately via
    # `npm run dev`, is a different origin from the backend - without
    # this, every browser request gets blocked by CORS before it even
    # reaches app code). Bearer-token auth means no cookies cross origins,
    # so allow_credentials stays off - see main.py's CORSMiddleware setup.
    # Both "localhost" and "127.0.0.1" are listed because browsers treat
    # them as different origins even though they resolve to the same
    # machine - whichever one you happen to open the frontend at needs to
    # be in this list.
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000,http://127.0.0.1:3000"

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() == "production"

    @property
    def webhook_retry_schedule(self) -> List[int]:
        return [int(x) for x in self.WEBHOOK_RETRY_SCHEDULE_MINUTES.split(",") if x.strip()]

    def enforce_test_mode_restrictions(self) -> None:
        """
        Backend-enforced safety net (spec sections 11, 12, 55): even if
        someone mis-sets ALLOW_OTP_BYPASS / ALLOW_ADMIN_MFA_BYPASS / TEST_MODE
        via a stray env var, production can never honor them.
        """
        if self.is_production:
            self.ALLOW_OTP_BYPASS = False
            self.ALLOW_ADMIN_MFA_BYPASS = False
            self.TEST_MODE = False


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.enforce_test_mode_restrictions()
    return settings
