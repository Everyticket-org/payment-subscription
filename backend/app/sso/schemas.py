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
    authenticated - see app.api.v1.integration).

    2026-09-14 follow-up ("can we use subscription ID? as we are sending
    to everyticket"): external_customer_id is this app's OWN
    subscription_id - the same value already sent as a fixed field on
    every subscription.activated webhook payload (app.webhooks.payloads),
    which app.webhooks.service._handle_activation_outcome then stores as
    CustomerApplicationMapping.external_customer_id the moment that
    delivery succeeds. Everyticket's backend doesn't invent or manage its
    own identifier at all - it only has to remember the subscription_id
    it was given for a customer and echo that same value back here. By
    the time a customer clicks "Manage Subscription" inside Everyticket,
    that mapping is guaranteed to already exist, so it's the natural (and
    only) key Everyticket needs to pass. On a repurchase-after-expiry, a
    fresh subscription.activated event carries a NEW subscription_id, and
    the stored mapping is overwritten to match - Everyticket must use
    whichever subscription_id it was most recently given for that
    customer, not an older one from a prior subscription.

    user_identifier is optional, free-form context Everyticket can attach
    (e.g. which of its own admin users triggered this) - it's stored on
    the SsoSession row for audit/troubleshooting only, never interpreted
    by this app."""

    external_customer_id: str
    user_identifier: str | None = None
