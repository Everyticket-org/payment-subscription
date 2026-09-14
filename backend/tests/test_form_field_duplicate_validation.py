"""
Duplicate-value validation for registration-form fields (spec section 18
follow-up - Vishal: "Add one more checkbox to validate duplication (it
means any record have similar value then it will not allow user to enter
same name) & Validation message for that duplication also should be
configured.").

Covers:
  1. Admin API boundary: check_duplicate/duplicate_message are saved and
     returned on both create and update, and visible on the public
     dynamic-form endpoint (same pattern as validation_pattern/
     validation_message).
  2. Public submission enforcement
     (app.forms.validation.check_duplicate_registration_data, wired into
     POST /subscribe): a value that already exists on ANOTHER customer's
     registration data for the same field is rejected with 422 and the
     field's custom duplicate_message (or a generic fallback); matching
     is case-insensitive and whitespace-trimmed ("similar value", not a
     byte-exact comparison); a field with check_duplicate off never
     blocks a repeated value; and - the key regression this feature could
     easily introduce - the SAME customer re-submitting their own
     existing value (e.g. an upgrade/downgrade that resends the same
     registration_data) is never flagged as a duplicate of itself.
"""
from app.core.seed import DEV_ADMIN_EMAIL, DEV_ADMIN_PASSWORD


def _admin_headers(client) -> dict:
    login = client.post("/api/v1/admin/auth/login", json={"email": DEV_ADMIN_EMAIL, "password": DEV_ADMIN_PASSWORD})
    assert login.status_code == 200, login.text
    pre_mfa_token = login.json()["pre_mfa_token"]
    verify = client.post("/api/v1/admin/auth/mfa/verify", json={"pre_mfa_token": pre_mfa_token, "code": "BYPASS"})
    assert verify.status_code == 200, verify.text
    return {"Authorization": f"Bearer {verify.json()['access_token']}"}


def _create_field(client, headers, **overrides):
    payload = {
        "field_key": "organization_name",
        "label": "Organization Name",
        "field_type": "text",
        "required": False,
        "display_order": 60,
    }
    payload.update(overrides)
    return client.post("/api/v1/admin/registration-form", json=payload, headers=headers)


def _customer_token(client, email, mobile):
    identify = client.post("/api/v1/public/identify", json={"email": email, "mobile": mobile})
    otp_session_id = identify.json()["otp_session_id"]
    verify = client.post("/api/v1/public/otp/verify", json={"otp_session_id": otp_session_id, "code": "BYPASS"})
    return verify.json()["access_token"]


_subscribe_counter = [0]


def _subscribe(client, registration_data, plan_code="BASIC", headers=None):
    # Each unauthenticated call uses a fresh email/mobile pair - re-using
    # one would hit the *unrelated* "account already exists, verify via
    # OTP" branch instead of exercising the duplicate-value check itself.
    _subscribe_counter[0] += 1
    n = _subscribe_counter[0]
    payload = {"registration_data": registration_data}
    if headers is None:
        payload["email"] = f"dupcheck{n}@example.com"
        payload["mobile"] = f"97456{n:05d}"
    return client.post(f"/api/v1/public/plans/{plan_code}/subscribe", json=payload, headers=headers)


# --- 1. Admin API boundary -------------------------------------------------


def test_check_duplicate_and_message_saved_and_returned(client, seeded_db):
    headers = _admin_headers(client)
    created = _create_field(
        client,
        headers,
        check_duplicate=True,
        duplicate_message="This organization is already registered",
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["check_duplicate"] is True
    assert body["duplicate_message"] == "This organization is already registered"

    public = client.get("/api/v1/public/registration-form")
    assert public.status_code == 200
    field = next(f for f in public.json() if f["field_key"] == "organization_name")
    assert field["check_duplicate"] is True
    assert field["duplicate_message"] == "This organization is already registered"


def test_check_duplicate_defaults_false_and_is_updatable(client, seeded_db):
    headers = _admin_headers(client)
    created = _create_field(client, headers)
    assert created.status_code == 201, created.text
    assert created.json()["check_duplicate"] is False
    field_id = created.json()["id"]

    update = client.put(
        f"/api/v1/admin/registration-form/{field_id}",
        json={"check_duplicate": True, "duplicate_message": "Already taken"},
        headers=headers,
    )
    assert update.status_code == 200, update.text
    assert update.json()["check_duplicate"] is True
    assert update.json()["duplicate_message"] == "Already taken"


# --- 2. Public submission enforcement --------------------------------------


def test_duplicate_value_rejected_with_custom_message(client, seeded_db):
    headers = _admin_headers(client)
    created = _create_field(
        client,
        headers,
        check_duplicate=True,
        duplicate_message="This organization is already registered",
    )
    assert created.status_code == 201, created.text

    first = _subscribe(client, {"organization_name": "Unique Museum Trust"})
    assert first.status_code == 200, first.text

    second = _subscribe(client, {"organization_name": "Unique Museum Trust"})
    assert second.status_code == 422, second.text
    body = second.json()
    assert body["error_code"] == "REGISTRATION_DATA_INVALID"
    assert body["message"] == "This organization is already registered"


def test_duplicate_check_is_case_insensitive_and_trims_whitespace(client, seeded_db):
    headers = _admin_headers(client)
    created = _create_field(client, headers, check_duplicate=True)
    assert created.status_code == 201, created.text

    first = _subscribe(client, {"organization_name": "Heritage Foundation"})
    assert first.status_code == 200, first.text

    second = _subscribe(client, {"organization_name": "  heritage FOUNDATION  "})
    assert second.status_code == 422, second.text


def test_duplicate_value_with_no_custom_message_gets_generic_fallback(client, seeded_db):
    headers = _admin_headers(client)
    created = _create_field(client, headers, check_duplicate=True)
    assert created.status_code == 201, created.text

    first = _subscribe(client, {"organization_name": "Some Org"})
    assert first.status_code == 200, first.text

    second = _subscribe(client, {"organization_name": "Some Org"})
    assert second.status_code == 422, second.text
    assert "Organization Name" in second.json()["message"]


def test_field_without_check_duplicate_allows_repeated_values(client, seeded_db):
    headers = _admin_headers(client)
    created = _create_field(client, headers, check_duplicate=False)
    assert created.status_code == 201, created.text

    first = _subscribe(client, {"organization_name": "Repeatable Org"})
    assert first.status_code == 200, first.text

    second = _subscribe(client, {"organization_name": "Repeatable Org"})
    assert second.status_code == 200, second.text


def test_blank_value_for_a_duplicate_checked_field_is_not_checked(client, seeded_db):
    headers = _admin_headers(client)
    created = _create_field(client, headers, check_duplicate=True)
    assert created.status_code == 201, created.text

    first = _subscribe(client, {"organization_name": "Filled In"})
    assert first.status_code == 200, first.text

    second = _subscribe(client, {})
    assert second.status_code == 200, second.text


def test_same_customer_resubmitting_own_value_is_not_flagged_as_duplicate(client, seeded_db):
    """The key regression risk: an existing customer upgrading their plan
    re-sends the same registration_data - that must never be rejected as
    a duplicate of their own prior submission."""
    headers = _admin_headers(client)
    created = _create_field(client, headers, check_duplicate=True)
    assert created.status_code == 201, created.text

    email, mobile = "selfresubmit@example.com", "9745500001"

    # Subscribe with a fixed, known email/mobile (rather than
    # _subscribe()'s auto-generated identity) so _customer_token can look
    # this exact customer back up below.
    known = client.post(
        "/api/v1/public/plans/BASIC/subscribe",
        json={"email": email, "mobile": mobile, "registration_data": {"organization_name": "Known Museum"}},
    )
    assert known.status_code == 200, known.text
    txn = known.json()["payment"]["transaction_id"]
    client.post("/api/v1/payment/mock/callback", json={"transaction_id": txn, "scenario": "SUCCESS"})

    token = _customer_token(client, email, mobile)
    auth_headers = {"Authorization": f"Bearer {token}"}

    # Upgrading while resending the SAME value this customer already has
    # on file must succeed - it's excluded as their own prior row.
    upgrade = _subscribe(
        client, {"organization_name": "Known Museum"}, plan_code="PROFESSIONAL", headers=auth_headers
    )
    assert upgrade.status_code == 200, upgrade.text

    # A genuinely different customer using that same value must still be rejected.
    other = _subscribe(client, {"organization_name": "Known Museum"}, plan_code="BASIC")
    assert other.status_code == 422, other.text
