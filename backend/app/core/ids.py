"""
Secure public identifier generation.

Internal primary keys stay as surrogate integers/UUIDs; these human-readable,
prefixed IDs (CUS-, SUB-, TXN-, INV-, EVT-, CORR-, MSG-) are the identifiers
ever exposed via API/UI/webhooks (spec section 21, 65).

Format: PREFIX-<10 url-safe base32 chars derived from a secure random token>.
Collisions are astronomically unlikely (~50 bits of entropy) but callers
should still rely on the DB unique constraint on these columns as the source
of truth, and retry generation on the rare IntegrityError.
"""
import secrets
import string

_ALPHABET = string.ascii_uppercase + string.digits  # Crockford-ish, no lookalikes needed for internal use
_LENGTH = 10


def _random_suffix(length: int = _LENGTH) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def new_customer_id() -> str:
    return f"CUS-{_random_suffix()}"


def new_subscription_id() -> str:
    return f"SUB-{_random_suffix()}"


def new_transaction_id() -> str:
    return f"TXN-{_random_suffix()}"


def new_invoice_id() -> str:
    return f"INV-{_random_suffix()}"


def new_event_id() -> str:
    return f"EVT-{_random_suffix()}"


def new_correlation_id() -> str:
    return f"CORR-{_random_suffix()}"


def new_otp_session_id() -> str:
    return f"OTP-{_random_suffix()}"


def new_sso_session_id() -> str:
    return f"SSO-{_random_suffix()}"
