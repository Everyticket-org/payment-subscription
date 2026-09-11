"""
Regex validation + custom validation message for registration-form fields
(spec section 18 follow-up - Vishal: "For forms - give one more option
for validation by Regex and validation message fields to be set.").

Covers three layers:
  1. Admin API boundary (app.forms.schemas): an invalid regex is rejected
     with 422 the moment it's saved, on both create and update - never
     stored bad.
  2. Public submission enforcement (app.forms.validation.
     validate_registration_data, wired into POST /subscribe): a value
     that doesn't match a configured pattern is rejected with 422 and
     the field's custom validation_message (or a generic fallback when
     none was set); a value that matches, or a field with no pattern
     configured at all, passes through unaffected.
  3. Regression coverage for the fix that resolved the 62-test failure
     this feature briefly introduced: fields with no validation_pattern
     configured (i.e. every pre-existing seeded field) must never be
     newly enforced as "required" by this code path - that flag remains
     deliberately unenforced server-side (see app.forms.validation's
     module docstring).
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
        "field_key": "gst_number",
        "label": "GST Number",
        "field_type": "text",
        "required": False,
        "display_order": 50,
    }
    payload.update(overrides)
    return client.post("/api/v1/admin/registration-form", json=payload, headers=headers)


# --- 1. Admin API boundary: invalid regex rejected at create/update -------


def test_invalid_regex_rejected_on_create(client, seeded_db):
    headers = _admin_headers(client)
    resp = _create_field(client, headers, validation_pattern="[unclosed")
    assert resp.status_code == 422, resp.text


def test_invalid_regex_rejected_on_update(client, seeded_db):
    headers = _admin_headers(client)
    created = _create_field(client, headers)
    assert created.status_code == 201, created.text
    field_id = created.json()["id"]

    update = client.put(
        f"/api/v1/admin/registration-form/{field_id}",
        json={"validation_pattern": "("},
        headers=headers,
    )
    assert update.status_code == 422, update.text


def test_valid_regex_and_message_saved_and_returned(client, seeded_db):
    headers = _admin_headers(client)
    created = _create_field(
        client,
        headers,
        validation_pattern=r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$",
        validation_message="Enter a valid 15-character GSTIN",
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["validation_pattern"] == r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$"
    assert body["validation_message"] == "Enter a valid 15-character GSTIN"

    # Also visible on the public dynamic-form endpoint, so the client can
    # validate the same rule before ever submitting.
    public = client.get("/api/v1/public/registration-form")
    assert public.status_code == 200
    field = next(f for f in public.json() if f["field_key"] == "gst_number")
    assert field["validation_pattern"] == r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$"
    assert field["validation_message"] == "Enter a valid 15-character GSTIN"


# --- 2. Public submission enforcement --------------------------------------


_subscribe_counter = [0]


def _subscribe(client, registration_data):
    # Each call uses a fresh email/mobile pair - re-using one across calls
    # in the same test would hit the *unrelated* "account already exists,
    # verify via OTP" branch (a different feature entirely) instead of
    # exercising the registration_data validation this test is about.
    _subscribe_counter[0] += 1
    n = _subscribe_counter[0]
    return client.post(
        "/api/v1/public/plans/BASIC/subscribe",
        json={
            "email": f"regexcheck{n}@example.com",
            "mobile": f"98123{n:05d}",
            "registration_data": registration_data,
        },
    )


def test_submission_violating_pattern_rejected_with_custom_message(client, seeded_db):
    headers = _admin_headers(client)
    created = _create_field(
        client,
        headers,
        field_key="pincode",
        label="PIN Code",
        validation_pattern=r"^[0-9]{6}$",
        validation_message="PIN code must be exactly 6 digits",
    )
    assert created.status_code == 201, created.text

    resp = _subscribe(client, {"museum_name": "Test Museum", "contact_person": "A", "pincode": "12AB"})
    assert resp.status_code == 422, resp.text
    body = resp.json()
    assert body["error_code"] == "REGISTRATION_DATA_INVALID"
    assert body["message"] == "PIN code must be exactly 6 digits"


def test_submission_violating_pattern_with_no_custom_message_gets_generic_fallback(client, seeded_db):
    headers = _admin_headers(client)
    created = _create_field(
        client,
        headers,
        field_key="pincode2",
        label="PIN Code 2",
        validation_pattern=r"^[0-9]{6}$",
    )
    assert created.status_code == 201, created.text

    resp = _subscribe(client, {"museum_name": "Test Museum", "contact_person": "A", "pincode2": "abc"})
    assert resp.status_code == 422, resp.text
    assert "PIN Code 2" in resp.json()["message"]


def test_submission_matching_pattern_is_accepted(client, seeded_db):
    headers = _admin_headers(client)
    created = _create_field(
        client,
        headers,
        field_key="pincode3",
        label="PIN Code 3",
        validation_pattern=r"^[0-9]{6}$",
        validation_message="PIN code must be exactly 6 digits",
    )
    assert created.status_code == 201, created.text

    resp = _subscribe(client, {"museum_name": "Test Museum", "contact_person": "A", "pincode3": "560001"})
    assert resp.status_code == 200, resp.text


def test_field_with_no_pattern_configured_is_never_checked(client, seeded_db):
    # Every seeded field (museum_name, contact_person, gstin, address) has
    # no validation_pattern - submitting any value, or omitting fields
    # entirely, must never be rejected by this new code path.
    resp = _subscribe(client, {})
    assert resp.status_code == 200, resp.text

    resp2 = _subscribe(client, {"museum_name": "Anything Goes Here !! 123"})
    assert resp2.status_code == 200, resp2.text


def test_blank_value_for_a_patterned_field_is_not_pattern_checked(client, seeded_db):
    # Deliberate scope limit (see app.forms.validation docstring): an
    # unfilled field is left to whatever "required" enforcement already
    # exists (none, server-side) rather than newly rejected here.
    headers = _admin_headers(client)
    created = _create_field(
        client,
        headers,
        field_key="pincode4",
        label="PIN Code 4",
        validation_pattern=r"^[0-9]{6}$",
    )
    assert created.status_code == 201, created.text

    resp = _subscribe(client, {"museum_name": "Test Museum", "contact_person": "A"})
    assert resp.status_code == 200, resp.text


def test_first_violation_reported_in_display_order(client, seeded_db):
    headers = _admin_headers(client)
    _create_field(
        client,
        headers,
        field_key="field_a",
        label="Field A",
        validation_pattern=r"^[0-9]+$",
        validation_message="Field A must be numeric",
        display_order=10,
    )
    _create_field(
        client,
        headers,
        field_key="field_b",
        label="Field B",
        validation_pattern=r"^[0-9]+$",
        validation_message="Field B must be numeric",
        display_order=20,
    )

    resp = _subscribe(
        client,
        {"museum_name": "Test Museum", "contact_person": "A", "field_a": "not-a-number", "field_b": "also-not"},
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["message"] == "Field A must be numeric"
