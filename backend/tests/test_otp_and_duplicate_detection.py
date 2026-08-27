"""Duplicate customer detection + OTP (spec sections 9-11)."""


def test_identify_no_match_returns_none(client, seeded_db):
    resp = client.post("/api/v1/public/identify", json={"email": "brandnew@example.com", "mobile": "9111111111"})
    assert resp.status_code == 200
    assert resp.json()["match_status"] == "none"
    assert resp.json()["otp_session_id"] is None


def test_identify_conflict_email_only_match(client, seeded_db):
    client.post(
        "/api/v1/public/plans/basic/subscribe",
        json={"email": "conflict@example.com", "mobile": "9222222222", "registration_data": {}},
    )
    resp = client.post("/api/v1/public/identify", json={"email": "conflict@example.com", "mobile": "9333333333"})
    assert resp.status_code == 200
    assert resp.json()["match_status"] == "conflict"
    assert resp.json()["otp_session_id"] is None


def test_identify_exact_match_issues_otp_session(client, seeded_db):
    client.post(
        "/api/v1/public/plans/basic/subscribe",
        json={"email": "exact@example.com", "mobile": "9444444444", "registration_data": {}},
    )
    resp = client.post("/api/v1/public/identify", json={"email": "exact@example.com", "mobile": "9444444444"})
    assert resp.status_code == 200
    assert resp.json()["match_status"] == "exact"
    assert resp.json()["otp_session_id"] is not None
    # TEST_MODE is on in the seeded dev application, so the plaintext OTP
    # is surfaced for testability (see app.auth.otp_service docstring).
    assert resp.json()["debug_otp_code"] is not None


def test_otp_verify_wrong_code_then_bypass(client, seeded_db):
    client.post(
        "/api/v1/public/plans/basic/subscribe",
        json={"email": "otpflow@example.com", "mobile": "9555555555", "registration_data": {}},
    )
    identify = client.post("/api/v1/public/identify", json={"email": "otpflow@example.com", "mobile": "9555555555"})
    otp_session_id = identify.json()["otp_session_id"]

    wrong = client.post("/api/v1/public/otp/verify", json={"otp_session_id": otp_session_id, "code": "000000"})
    assert wrong.status_code == 401
    assert wrong.json()["error_code"] == "OTP_INVALID_OR_EXPIRED"

    ok = client.post("/api/v1/public/otp/verify", json={"otp_session_id": otp_session_id, "code": "BYPASS"})
    assert ok.status_code == 200
    assert ok.json()["access_token"]
    assert ok.json()["customer"]["email"] == "otpflow@example.com"


def test_otp_verify_correct_code_works_without_bypass(client, seeded_db):
    client.post(
        "/api/v1/public/plans/basic/subscribe",
        json={"email": "realcode@example.com", "mobile": "9666666666", "registration_data": {}},
    )
    identify = client.post("/api/v1/public/identify", json={"email": "realcode@example.com", "mobile": "9666666666"})
    otp_session_id = identify.json()["otp_session_id"]
    code = identify.json()["debug_otp_code"]
    assert code is not None

    resp = client.post("/api/v1/public/otp/verify", json={"otp_session_id": otp_session_id, "code": code})
    assert resp.status_code == 200
    assert resp.json()["access_token"]
