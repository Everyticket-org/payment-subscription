"""
Everyticket SSO (spec section 47).

Covers the full handoff: an admin generates a test SSO link (the
TEST_MODE-gated stand-in for what would, in production, be Everyticket
itself calling app.sso.service.create_sso_token()), the resulting token
is redeemed via POST /public/sso/consume for a normal customer portal
session token, and that token actually works against a customer-only
endpoint. Also covers the two things a signed-token-with-DB-backed-nonce
design exists specifically to prevent: replay (redeeming the same token
twice) and use after expiry - plus the TEST_MODE/permission gates on the
admin link-generation endpoint itself.
"""
from app.core.config import get_settings
from app.core.seed import DEV_ADMIN_EMAIL, DEV_ADMIN_PASSWORD

from tests.test_admin_api import _admin_headers, _new_active_subscription


def test_sso_happy_path_redeem(client, seeded_db):
    _new_active_subscription(client, "basic", "sso-happy@example.com", "9800000101")
    headers = _admin_headers(client)

    customers = client.get("/api/v1/admin/customers", params={"q": "sso-happy@example.com"}, headers=headers)
    customer_id = customers.json()["items"][0]["customer_id"]

    link = client.post(f"/api/v1/admin/customers/{customer_id}/sso-link", headers=headers)
    assert link.status_code == 200, link.text
    body = link.json()
    assert body["sso_token"]
    assert "/sso/consume?token=" in body["consume_url"]

    consume = client.post("/api/v1/public/sso/consume", json={"token": body["sso_token"]})
    assert consume.status_code == 200, consume.text
    consumed = consume.json()
    assert consumed["customer"]["customer_id"] == customer_id
    access_token = consumed["access_token"]

    portal = client.get("/api/v1/customer/me", headers={"Authorization": f"Bearer {access_token}"})
    assert portal.status_code == 200, portal.text
    assert portal.json()["customer"]["customer_id"] == customer_id


def test_sso_token_cannot_be_replayed(client, seeded_db):
    _new_active_subscription(client, "basic", "sso-replay@example.com", "9800000102")
    headers = _admin_headers(client)
    customer_id = client.get(
        "/api/v1/admin/customers", params={"q": "sso-replay@example.com"}, headers=headers
    ).json()["items"][0]["customer_id"]

    token = client.post(f"/api/v1/admin/customers/{customer_id}/sso-link", headers=headers).json()["sso_token"]

    first = client.post("/api/v1/public/sso/consume", json={"token": token})
    assert first.status_code == 200, first.text

    second = client.post("/api/v1/public/sso/consume", json={"token": token})
    assert second.status_code == 401
    assert second.json()["error_code"] == "SSO_TOKEN_ALREADY_USED"


def test_sso_token_rejected_once_expired(client, seeded_db, db_session):
    from app.auth.models import SsoSession
    from datetime import datetime, timedelta, timezone

    _new_active_subscription(client, "basic", "sso-expired@example.com", "9800000103")
    headers = _admin_headers(client)
    customer_id = client.get(
        "/api/v1/admin/customers", params={"q": "sso-expired@example.com"}, headers=headers
    ).json()["items"][0]["customer_id"]

    token = client.post(f"/api/v1/admin/customers/{customer_id}/sso-link", headers=headers).json()["sso_token"]

    # Force the DB-backed session row into the past rather than sleeping
    # past the real TTL - the row's expires_at is what redeem_sso_token()
    # actually checks, independent of the JWT's own exp claim.
    session = db_session.query(SsoSession).filter(SsoSession.customer_id == customer_id).order_by(SsoSession.id.desc()).first()
    assert session is not None
    session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.add(session)
    db_session.commit()

    resp = client.post("/api/v1/public/sso/consume", json={"token": token})
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "SSO_TOKEN_EXPIRED"


def test_sso_consume_rejects_unknown_token(client, seeded_db):
    resp = client.post("/api/v1/public/sso/consume", json={"token": "not-a-real-token"})
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "SSO_TOKEN_INVALID"


def test_sso_link_generation_requires_test_mode(client, seeded_db, monkeypatch):
    _new_active_subscription(client, "basic", "sso-gate@example.com", "9800000104")
    headers = _admin_headers(client)
    customer_id = client.get(
        "/api/v1/admin/customers", params={"q": "sso-gate@example.com"}, headers=headers
    ).json()["items"][0]["customer_id"]

    monkeypatch.setenv("TEST_MODE", "false")
    get_settings.cache_clear()
    try:
        resp = client.post(f"/api/v1/admin/customers/{customer_id}/sso-link", headers=headers)
        assert resp.status_code == 403
        assert resp.json()["error_code"] == "FORBIDDEN"
    finally:
        get_settings.cache_clear()


def test_sso_link_generation_requires_permission(client, seeded_db, db_session):
    from app.auth import service as auth_service

    _new_active_subscription(client, "basic", "sso-perm@example.com", "9800000105")
    admin_headers = _admin_headers(client)
    customer_id = client.get(
        "/api/v1/admin/customers", params={"q": "sso-perm@example.com"}, headers=admin_headers
    ).json()["items"][0]["customer_id"]

    auth_service.create_admin_user(
        db_session, email="limited-sso@example.com", full_name="Limited Admin", password="LimitedPass123!", mfa_enabled=False
    )
    db_session.commit()
    login = client.post(
        "/api/v1/admin/auth/login", json={"email": "limited-sso@example.com", "password": "LimitedPass123!"}
    )
    limited_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = client.post(f"/api/v1/admin/customers/{customer_id}/sso-link", headers=limited_headers)
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "FORBIDDEN"
