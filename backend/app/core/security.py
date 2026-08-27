"""
Password hashing + JWT helpers.

Never log raw passwords, OTPs, JWTs, or gateway/webhook secrets - see spec
section 68. Callers are responsible for keeping these values out of logs;
this module never logs its inputs/outputs.

Hashing uses the `bcrypt` library directly rather than passlib. passlib
1.7.4 (its last release, unmaintained since 2020) runs an internal
self-test on first use that assumes bcrypt still silently truncates
secrets over 72 bytes; bcrypt>=4.1 removed that silent truncation and
raises ValueError instead, which broke passlib's backend detection
entirely regardless of which bcrypt version was installed (see
https://github.com/pyca/bcrypt/issues/684). Calling bcrypt directly
avoids that broken self-test and lets this project track current bcrypt
releases (needed for prebuilt wheels on new Python versions) without
fighting passlib's compatibility assumptions. The 72-byte truncation
below reproduces bcrypt's own documented, algorithmic limit - not a
security regression, since that limit has always applied.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import bcrypt
from jose import jwt, JWTError

from app.core.config import get_settings

settings = get_settings()

_BCRYPT_MAX_BYTES = 72  # bcrypt's own algorithmic limit on secret length


def hash_password(raw_password: str) -> str:
    encoded = raw_password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")


def verify_password(raw_password: str, hashed_password: str) -> bool:
    encoded = raw_password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    try:
        return bcrypt.checkpw(encoded, hashed_password.encode("utf-8"))
    except ValueError:
        # Malformed/foreign hash format - never a match, never a 500.
        return False


def create_access_token(subject: str, extra_claims: Optional[dict[str, Any]] = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
        "type": "access",
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(subject: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
        "type": "refresh",
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    """Raises jose.JWTError on invalid/expired token - callers translate to 401."""
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])


__all__ = [
    "hash_password",
    "verify_password",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "JWTError",
]
