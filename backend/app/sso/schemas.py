"""Pydantic schemas for Everyticket SSO (spec section 47)."""
from datetime import datetime

from pydantic import BaseModel


class SsoConsumeRequest(BaseModel):
    """Body for POST /public/sso/consume - the signed token Everyticket
    (or, in TEST_MODE, the admin test-link endpoint) handed to the browser
    as a query param / redirect target."""

    token: str


class SsoLinkOut(BaseModel):
    """A freshly issued SSO token plus a ready-to-open consume URL.

    Returned from two call sites that both end up calling the same
    app.sso.service.create_sso_token(): the TEST_MODE-only admin action
    (app.api.v1.admin_customers's /customers/{id}/sso-link, for
    exercising the handoff without a real Everyticket instance) and, as
    of the 2026-09-13 follow-up 3 ("need to give API to everyticket
    Platform to call that which generates token and return a link"), the
    real production endpoint Everyticket's own backend calls directly:
    app.api.v1.integration's POST /integration/sso/generate-link."""

    sso_token: str
    consume_url: str
    expires_at: datetime


class SsoLinkGenerateRequest(BaseModel):
    """Body for POST /api/v1/integration/sso/generate-link (API-key/secret
    authenticated - see app.api.v1.integration). external_customer_id is
    the identity Everyticket itself already holds for this customer,
    assigned back to it in the subscription.activated webhook's response
    (spec section 32) - by the time a customer clicks "Manage
    Subscription" inside Everyticket, this mapping is guaranteed to
    already exist, so it's the natural (and only) key Everyticket needs
    to pass. user_identifier is optional, free-form context Everyticket
    can attach (e.g. which of its own admin users triggered this) - it's
    stored on the SsoSession row for audit/troubleshooting only, never
    interpreted by this app."""

    external_customer_id: str
    user_identifier: str | None = None
