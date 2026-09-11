"""
Admin Webhook Logs "Verify connectivity" button (spec sections 34-37, 51;
added per Vishal: "Webhook API is not getting reached or logging headers,
statuscode, etc.. from API... please give button as well near log to
click and verify that its calling properly or not..").

POST /api/v1/admin/webhooks/verify is deliberately NOT gated by
require_test_mode() - unlike every tool in the admin Testing module
(tests/test_admin_testing.py::test_testing_endpoints_require_test_mode) -
because an admin needs to check real, live webhook connectivity in
production too. It IS gated by the existing WEBHOOKS_MANAGE permission,
same as the delivery Retry action.
"""
from app.core.config import get_settings

from tests.test_admin_api import _admin_headers


def test_verify_connectivity_is_not_blocked_by_test_mode_false(client, seeded_db):
    """Contrast with test_admin_testing.py's
    test_testing_endpoints_require_test_mode: the Testing module 403s
    under TEST_MODE=false, but this endpoint must not."""
    headers = _admin_headers(client)
    import os

    previous = os.environ.get("TEST_MODE")
    os.environ["TEST_MODE"] = "false"
    get_settings.cache_clear()
    try:
        resp = client.post("/api/v1/admin/webhooks/verify", headers=headers)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "sent" in body
        assert isinstance(body["sent"], bool)
    finally:
        if previous is None:
            os.environ.pop("TEST_MODE", None)
        else:
            os.environ["TEST_MODE"] = previous
        get_settings.cache_clear()


def test_verify_connectivity_requires_webhooks_manage_permission(client, seeded_db, db_session):
    from app.auth import service as auth_service

    auth_service.create_admin_user(
        db_session, email="limited-webhooks@example.com", full_name="Limited Admin", password="LimitedPass123!", mfa_enabled=False
    )
    db_session.commit()
    login = client.post(
        "/api/v1/admin/auth/login", json={"email": "limited-webhooks@example.com", "password": "LimitedPass123!"}
    )
    limited_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = client.post("/api/v1/admin/webhooks/verify", headers=limited_headers)
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "FORBIDDEN"


def test_verify_connectivity_records_a_visible_event_and_delivery(client, seeded_db):
    headers = _admin_headers(client)

    resp = client.post("/api/v1/admin/webhooks/verify", headers=headers)
    assert resp.status_code == 200, resp.text
    live_result = resp.json()
    assert "sent" in live_result

    events = client.get(
        "/api/v1/admin/webhooks/events", params={"event_type": "webhook.connectivity_check"}, headers=headers
    )
    assert events.status_code == 200, events.text
    matching = [e for e in events.json()["items"] if e["payload"] == {"ping": True, "source": "admin_webhook_logs_verify"}]
    assert len(matching) >= 1
    event = matching[-1]
    assert len(event["deliveries"]) == 1
    delivery = event["deliveries"][0]

    # The request was always built (and its headers captured) even if
    # nothing answered back - only response_headers depends on an actual
    # reply having come back from the destination.
    assert delivery["request_headers"] is not None
    assert "request_headers" in delivery
    assert "response_headers" in delivery


def test_verify_connectivity_audit_logs_the_attempt(client, seeded_db):
    headers = _admin_headers(client)

    resp = client.post("/api/v1/admin/webhooks/verify", headers=headers)
    assert resp.status_code == 200, resp.text

    logs = client.get(
        "/api/v1/admin/audit-logs", params={"action": "WEBHOOK_CONNECTIVITY_VERIFIED"}, headers=headers
    )
    assert logs.status_code == 200, logs.text
    assert len(logs.json()["items"]) >= 1
