"""Pydantic schemas for Everyticket SSO (spec section 47)."""
from datetime import datetime

from pydantic import BaseModel


class SsoConsumeRequest(BaseModel):
    """Body for POST /public/sso/consume - the signed token Everyticket
    (or, in TEST_MODE, the admin test-link endpoint) handed to the browser
    as a query param / redirect target."""

    token: str


class SsoLinkOut(BaseModel):
    """TEST_MODE-only response: a freshly issued SSO token plus a
    ready-to-open consume URL, so the full Everyticket handoff can be
    exercised end-to-end without a real Everyticket instance ever issuing
    a token itself. Never returned outside TEST_MODE."""

    sso_token: str
    consume_url: str
    expires_at: datetime
