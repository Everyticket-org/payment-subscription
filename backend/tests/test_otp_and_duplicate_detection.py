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


def test_identify_resend_within_cooldown_is_rate_limited(client, seeded_db):
    """Spec section 11's 'resend rate limiting': calling /identify again
    for the same email+mobile right away must not issue (and email) a
    second OTP code."""
    client.post(
        "/api/v1/public/plans/basic/subscribe",
        json={"email": "resend@example.com", "mobile": "9777777777", "registration_data": {}},
    )
    first = client.post("/api/v1/public/identify", json={"email": "resend@example.com", "mobile": "9777777777"})
    assert first.status_code == 200
    assert first.json()["otp_session_id"] is not None

    second = client.post("/api/v1/public/identify", json={"email": "resend@example.com", "mobile": "9777777777"})
    assert second.status_code == 429
    assert second.json()["error_code"] == "OTP_RATE_LIMITED"


def test_identify_resend_allowed_once_cooldown_elapses(client, seeded_db, db_session):
    """Once OTP_RESEND_COOLDOWN_SECONDS has genuinely passed, a fresh
    /identify call issues a brand new OTP session rather than staying
    rate-limited forever."""
    from datetime import datetime, timedelta, timezone

    from app.auth.models import OtpSession

    client.post(
        "/api/v1/public/plans/basic/subscribe",
        json={"email": "resend-ok@example.com", "mobile": "9788888888", "registration_data": {}},
    )
    first = client.post("/api/v1/public/identify", json={"email": "resend-ok@example.com", "mobile": "9788888888"})
    assert first.status_code == 200
    first_session_id = first.json()["otp_session_id"]

    # Force the cooldown window closed rather than sleeping for real in
    # a test - identical technique to test_sso.py's expiry test.
    session = db_session.query(OtpSession).filter(OtpSession.otp_session_id == first_session_id).first()
    session.created_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db_session.add(session)
    db_session.commit()

    second = client.post("/api/v1/public/identify", json={"email": "resend-ok@example.com", "mobile": "9788888888"})
    assert second.status_code == 200
    assert second.json()["otp_session_id"] is not None
    assert second.json()["otp_session_id"] != first_session_id
