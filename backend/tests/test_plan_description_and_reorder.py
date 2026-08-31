"""
Plan description rich-text sanitization + bulk display-order reorder
(spec section 51's Plans admin module - "make description an editor with
bullet points" and "allow sorting of plans").

Covers: sanitize_description() strips everything outside its allowlist
(no attributes survive at all, including a script-bearing one, which is
the actual XSS-relevant case since this HTML is later rendered unescaped
on the public plan listing page), the create/update endpoints apply it,
and PUT /admin/plans/reorder actually changes display_order (and therefore
the order GET /public/plans returns), rejects an incomplete/unknown list,
and is permission-gated.
"""
from app.plans.sanitize import sanitize_description

from tests.test_admin_api import _admin_headers


def test_sanitize_description_keeps_allowed_formatting():
    html = "<p>Great for <strong>small</strong> teams.</p><ul><li>Feature one</li><li>Feature two</li></ul>"
    assert sanitize_description(html) == html


def test_sanitize_description_strips_scripts_and_all_attributes():
    html = '<p onclick="alert(1)">Hi <script>alert(1)</script></p><img src=x onerror=alert(1)>'
    cleaned = sanitize_description(html)
    assert "<script" not in cleaned
    assert "onclick" not in cleaned
    assert "onerror" not in cleaned
    assert "<img" not in cleaned  # img isn't in the allowlist at all
    assert "Hi" in cleaned


def test_sanitize_description_none_and_empty():
    assert sanitize_description(None) is None
    assert sanitize_description("   ") is None


def test_create_and_update_plan_sanitize_description(client, seeded_db):
    headers = _admin_headers(client)
    create = client.post(
        "/api/v1/admin/plans",
        json={
            "plan_code": "RICHTEXT",
            "name": "Rich Text Plan",
            "price": 500,
            "description": '<p>Nice plan</p><script>alert(1)</script><ul><li onclick="x()">Bullet</li></ul>',
        },
        headers=headers,
    )
    assert create.status_code == 201, create.text
    assert "<script" not in create.json()["description"]
    assert "onclick" not in create.json()["description"]
    assert "<li>Bullet</li>" in create.json()["description"]

    update = client.put(
        "/api/v1/admin/plans/richtext",
        json={"description": '<p onmouseover="x()">Updated</p>'},
        headers=headers,
    )
    assert update.status_code == 200, update.text
    assert update.json()["description"] == "<p>Updated</p>"


def test_reorder_plans_changes_display_order_and_public_listing_order(client, seeded_db):
    headers = _admin_headers(client)

    # New order: ENTERPRISE, BASIC, PROFESSIONAL.
    reorder = client.put(
        "/api/v1/admin/plans/reorder",
        json={"plan_codes": ["ENTERPRISE", "BASIC", "PROFESSIONAL"]},
        headers=headers,
    )
    assert reorder.status_code == 200, reorder.text
    codes_in_order = [p["plan_code"] for p in reorder.json()]
    assert codes_in_order == ["ENTERPRISE", "BASIC", "PROFESSIONAL"]

    public = client.get("/api/v1/public/plans")
    assert [p["plan_code"] for p in public.json()] == ["ENTERPRISE", "BASIC", "PROFESSIONAL"]


def test_reorder_plans_rejects_incomplete_list(client, seeded_db):
    headers = _admin_headers(client)
    resp = client.put("/api/v1/admin/plans/reorder", json={"plan_codes": ["BASIC", "PROFESSIONAL"]}, headers=headers)
    assert resp.status_code == 404, resp.text
    assert resp.json()["error_code"] == "PLAN_NOT_FOUND"


def test_reorder_plans_rejects_unknown_code(client, seeded_db):
    headers = _admin_headers(client)
    resp = client.put(
        "/api/v1/admin/plans/reorder",
        json={"plan_codes": ["BASIC", "PROFESSIONAL", "ENTERPRISE", "NOPE"]},
        headers=headers,
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["error_code"] == "PLAN_NOT_FOUND"


def test_reorder_plans_requires_permission(client, seeded_db, db_session):
    from app.auth import service as auth_service

    auth_service.create_admin_user(
        db_session, email="noplanperm@example.com", full_name="No Perm", password="LimitedPass123!", mfa_enabled=False
    )
    db_session.commit()
    login = client.post("/api/v1/admin/auth/login", json={"email": "noplanperm@example.com", "password": "LimitedPass123!"})
    limited_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = client.put(
        "/api/v1/admin/plans/reorder",
        json={"plan_codes": ["BASIC", "PROFESSIONAL", "ENTERPRISE"]},
        headers=limited_headers,
    )
    assert resp.status_code == 403
