"""
Admin configuration screens, restructured 2026-09 into 4 sections:
Application (name/currency/Live-Test-Mode only), Payment Gateway (gateway
dropdown + per-mode PayU credentials), Everyticket Integration (secret
key/webhook URL/extra POST params/retry limit/escalation email), and
Notifications (SMTP transport + sender overrides). "Subscription rules"
and "Security" configuration are unchanged - their own tests continue
below, verifying REAL effect not just storage, same as before this pass.
"""
from app.core.enums import NotificationStatus
from app.notifications.email.providers.smtp import provider as smtp_provider
from app.notifications.models import NotificationLog

from tests.test_admin_api import _admin_headers


class _FakeSMTP:
    def __init__(self, host, port, timeout=10):
        self.__class__.connected_to.append((host, port))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        self.__class__.logins.append((user, password))

    def sendmail(self, from_addr, to_addrs, message):
        self.__class__.sent.append(message)


_FakeSMTP.sent = []
_FakeSMTP.connected_to = []
_FakeSMTP.logins = []


def test_get_application_config_masks_secrets(client, seeded_db):
    headers = _admin_headers(client)
    resp = client.get("/api/v1/admin/config/application", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["general"]["code"] == "EVERYTICKET"
    assert body["general"]["gateway_mode"] == "test"
    assert "webhook_secret" not in body["integration"]
    assert "sso_secret" not in body["integration"]
    assert body["integration"]["secret_key_is_set"] is False
    assert body["payment_gateway"]["default_gateway"] == "mock"
    assert set(body["payment_gateway"]["available_gateways"]) == {"mock", "payu"}
    assert body["payment_gateway"]["payu_test"]["merchant_key_is_set"] is False
    assert "smtp_password" not in body["notification"]
    assert body["notification"]["smtp_password_is_set"] is False


def test_config_endpoints_require_permission(client, seeded_db, db_session):
    from app.auth import service as auth_service

    auth_service.create_admin_user(
        db_session, email="noconfigperm@example.com", full_name="No Perm", password="LimitedPass123!", mfa_enabled=False
    )
    db_session.commit()
    login = client.post("/api/v1/admin/auth/login", json={"email": "noconfigperm@example.com", "password": "LimitedPass123!"})
    limited_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    assert client.get("/api/v1/admin/config/application", headers=limited_headers).status_code == 403
    assert client.put(
        "/api/v1/admin/config/application/general", json={"name": "x", "currency": "INR", "gateway_mode": "test"},
        headers=limited_headers,
    ).status_code == 403
    assert client.get("/api/v1/admin/config/security", headers=limited_headers).status_code == 403


def test_update_general_config_round_trips(client, seeded_db):
    headers = _admin_headers(client)
    resp = client.put(
        "/api/v1/admin/config/application/general",
        json={"name": "Everyticket Subscriptions (Staging)", "currency": "USD", "gateway_mode": "live"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Everyticket Subscriptions (Staging)"
    assert resp.json()["currency"] == "USD"
    assert resp.json()["gateway_mode"] == "live"

    refetched = client.get("/api/v1/admin/config/application", headers=headers)
    assert refetched.json()["general"]["name"] == "Everyticket Subscriptions (Staging)"

    # Restore defaults so later tests (e.g. the payment-gateway test below,
    # which relies on gateway_mode="test") aren't affected by this one.
    client.put(
        "/api/v1/admin/config/application/general",
        json={"name": "Everyticket Subscriptions", "currency": "INR", "gateway_mode": "test"},
        headers=headers,
    )


def test_post_subscription_message_configurable_and_saved(client, seeded_db):
    """2026-09-13 follow-up: "show message '...you will get your
    credentials in sometime' for first time subscription... This message
    also should be configurable." """
    headers = _admin_headers(client)
    resp = client.put(
        "/api/v1/admin/config/application/general",
        json={
            "name": "Everyticket Subscriptions",
            "currency": "INR",
            "gateway_mode": "test",
            "post_subscription_message": "Thanks! Your Everyticket login will arrive by email shortly.",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["post_subscription_message"] == "Thanks! Your Everyticket login will arrive by email shortly."

    refetched = client.get("/api/v1/admin/config/application", headers=headers)
    assert (
        refetched.json()["general"]["post_subscription_message"]
        == "Thanks! Your Everyticket login will arrive by email shortly."
    )

    public = client.get("/api/v1/public/messages")
    assert public.status_code == 200
    assert public.json()["post_subscription_message"] == "Thanks! Your Everyticket login will arrive by email shortly."

    # Restore the seeded default so other tests (and the dedicated
    # fallback test in test_end_to_end.py) see the app's normal state.
    from app.applications.config_schemas import DEFAULT_POST_SUBSCRIPTION_MESSAGE

    client.put(
        "/api/v1/admin/config/application/general",
        json={
            "name": "Everyticket Subscriptions",
            "currency": "INR",
            "gateway_mode": "test",
            "post_subscription_message": DEFAULT_POST_SUBSCRIPTION_MESSAGE,
        },
        headers=headers,
    )


def test_post_subscription_message_falls_back_to_default_text_when_unset(client, seeded_db):
    """An admin clearing the field (or an application that never set it)
    must not leave the public thank-you screen blank - falls back to
    DEFAULT_POST_SUBSCRIPTION_MESSAGE, same convention as validation_
    message/duplicate_message on registration form fields."""
    from app.applications.config_schemas import DEFAULT_POST_SUBSCRIPTION_MESSAGE

    headers = _admin_headers(client)
    client.put(
        "/api/v1/admin/config/application/general",
        json={"name": "Everyticket Subscriptions", "currency": "INR", "gateway_mode": "test", "post_subscription_message": None},
        headers=headers,
    )
    refetched = client.get("/api/v1/admin/config/application", headers=headers)
    assert refetched.json()["general"]["post_subscription_message"] is None

    public = client.get("/api/v1/public/messages")
    assert public.status_code == 200
    assert public.json()["post_subscription_message"] == DEFAULT_POST_SUBSCRIPTION_MESSAGE

    # Restore the seeded default as a real stored value for other tests.
    client.put(
        "/api/v1/admin/config/application/general",
        json={
            "name": "Everyticket Subscriptions",
            "currency": "INR",
            "gateway_mode": "test",
            "post_subscription_message": DEFAULT_POST_SUBSCRIPTION_MESSAGE,
        },
        headers=headers,
    )


def test_update_integration_config_secret_never_echoed_back(client, seeded_db):
    headers = _admin_headers(client)
    resp = client.put(
        "/api/v1/admin/config/application/integration",
        json={
            "webhook_url": "https://everyticket.example.com/hooks",
            "secret_key": "s3cr3t",
            "retry_limit": 3,
            "escalation_emails": "ops@example.com, billing@example.com",
            "escalation_email_subject": "Webhook down",
            "escalation_email_body": '<p onclick="x()">Please check <strong>Everyticket</strong>.</p>',
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "secret_key" not in body
    assert "extra_params" not in body  # feature removed, 2026-09 follow-up 3
    assert body["secret_key_is_set"] is True
    assert body["retry_limit"] == 3
    assert body["escalation_emails"] == "ops@example.com, billing@example.com"
    # sanitized the same way Plan.description is - onclick/attributes stripped.
    assert "onclick" not in body["escalation_email_body"]
    assert "<strong>Everyticket</strong>" in body["escalation_email_body"]


def test_update_integration_config_api_credentials_round_trip_and_clear(client, seeded_db):
    """2026-09-13 follow-up 3: Everyticket -> this app API key/secret
    (authenticates POST /api/v1/integration/sso/generate-link, see
    tests/test_integration_sso.py) - same None=unchanged/""=clear
    convention, stored in the same api_credentials JSON column that
    already existed but was previously unused."""
    headers = _admin_headers(client)

    resp = client.put(
        "/api/v1/admin/config/application/integration",
        json={"webhook_url": None, "api_key": "et-key-123", "api_secret": "et-secret-456"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["api_key"] == "et-key-123"  # key is an identifier, not itself masked
    assert "api_secret" not in body
    assert body["api_secret_is_set"] is True

    # Omitted entirely on a later PUT (webhook_url only) -> unchanged.
    resp2 = client.put(
        "/api/v1/admin/config/application/integration",
        json={"webhook_url": "https://everyticket.example.com/hooks"},
        headers=headers,
    )
    assert resp2.status_code == 200, resp2.text
    assert resp2.json()["api_key"] == "et-key-123"
    assert resp2.json()["api_secret_is_set"] is True

    # Explicit "" clears both.
    resp3 = client.put(
        "/api/v1/admin/config/application/integration",
        json={"webhook_url": None, "api_key": "", "api_secret": ""},
        headers=headers,
    )
    assert resp3.status_code == 200, resp3.text
    assert resp3.json()["api_key"] is None
    assert resp3.json()["api_secret_is_set"] is False


def test_update_payment_gateway_config_changes_gateway_for_new_payments_and_stores_credentials(client, seeded_db, monkeypatch):
    from app.core.config import get_settings

    # No env creds at all - forces the payment to actually use the
    # DB-stored (admin-configured) credentials below, not an env fallback.
    monkeypatch.setenv("PAYU_MERCHANT_KEY", "")
    monkeypatch.setenv("PAYU_MERCHANT_SALT", "")
    get_settings.cache_clear()

    headers = _admin_headers(client)
    try:
        resp = client.put(
            "/api/v1/admin/config/application/payment-gateway",
            json={
                "default_gateway": "payu",
                "payu_test": {"merchant_key": "dbkey123", "merchant_salt": "dbsalt456"},
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["default_gateway"] == "payu"
        assert resp.json()["payu_test"]["merchant_key_is_set"] is True

        subscribe = client.post(
            "/api/v1/public/plans/basic/subscribe",
            json={"email": "gatewayswitch@example.com", "mobile": "9833300001", "registration_data": {}},
        )
        assert subscribe.status_code == 200, subscribe.text
        assert subscribe.json()["payment"]["gateway"] == "payu"
        checkout = subscribe.json()["payment"]["checkout"]
        assert checkout is not None  # PayU is redirect-based - mock never sets this
        assert checkout["fields"]["key"] == "dbkey123"  # proves the DB-stored credential was actually used
    finally:
        client.put(
            "/api/v1/admin/config/application/payment-gateway", json={"default_gateway": "mock"}, headers=headers
        )
        get_settings.cache_clear()


def test_update_payment_gateway_config_stores_return_url_and_payu_webhook_base_url_and_used_in_checkout(client, seeded_db, monkeypatch):
    """2026-09 follow-up: 'PayU redirect back to localhost:4200 which is
    wrong. instead allow to configure return URL and PayU webhook URL' -
    both round-trip through the admin API, and payu_webhook_base_url
    actually changes the surl/furl PayU is told to redirect the
    customer's browser to on the very next payment."""
    from app.core.config import get_settings

    monkeypatch.setenv("PAYU_MERCHANT_KEY", "envkey")
    monkeypatch.setenv("PAYU_MERCHANT_SALT", "envsalt")
    get_settings.cache_clear()

    headers = _admin_headers(client)
    try:
        resp = client.put(
            "/api/v1/admin/config/application/payment-gateway",
            json={
                "default_gateway": "payu",
                "return_url": "https://subscribe.everyticket.example.com",
                "payu_webhook_base_url": "https://api.everyticket.example.com",
            },
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["return_url"] == "https://subscribe.everyticket.example.com"
        assert resp.json()["payu_webhook_base_url"] == "https://api.everyticket.example.com"

        refetched = client.get("/api/v1/admin/config/application", headers=headers)
        assert refetched.json()["payment_gateway"]["return_url"] == "https://subscribe.everyticket.example.com"
        assert refetched.json()["payment_gateway"]["payu_webhook_base_url"] == "https://api.everyticket.example.com"

        subscribe = client.post(
            "/api/v1/public/plans/basic/subscribe",
            json={"email": "payu-urls@example.com", "mobile": "9833300003", "registration_data": {}},
        )
        assert subscribe.status_code == 200, subscribe.text
        checkout_fields = subscribe.json()["payment"]["checkout"]["fields"]
        assert checkout_fields["surl"] == "https://api.everyticket.example.com/api/v1/payment/payu/callback/success"
        assert checkout_fields["furl"] == "https://api.everyticket.example.com/api/v1/payment/payu/callback/failure"
    finally:
        client.put(
            "/api/v1/admin/config/application/payment-gateway",
            json={"default_gateway": "mock", "return_url": None, "payu_webhook_base_url": None},
            headers=headers,
        )
        get_settings.cache_clear()


def test_update_integration_config_stores_archive_after_days(client, seeded_db):
    headers = _admin_headers(client)
    resp = client.put(
        "/api/v1/admin/config/application/integration",
        json={"webhook_url": None, "archive_after_days": 45},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["archive_after_days"] == 45

    refetched = client.get("/api/v1/admin/config/application", headers=headers)
    assert refetched.json()["integration"]["archive_after_days"] == 45

    # None disables it again (opt-in, per app.subscriptions.service.archive_stale_subscriptions).
    cleared = client.put(
        "/api/v1/admin/config/application/integration",
        json={"webhook_url": None, "archive_after_days": None},
        headers=headers,
    )
    assert cleared.json()["archive_after_days"] is None


def test_integration_config_exposes_webhook_field_catalog_and_round_trips_selection(client, seeded_db):
    """2026-09-14 follow-up: "allow to configure, more data to be passed
    for webhook call like plan details including name, amount, expiry
    etc.. so if admin select those parameters then it will be passed to
    webhook". GET must expose the full selectable-field catalog (for the
    Configuration screen's checklist) and this application's current
    selection (empty by default); PUT must persist a new selection,
    sanitizing away anything the catalog doesn't recognize rather than
    rejecting the request outright."""
    headers = _admin_headers(client)

    initial = client.get("/api/v1/admin/config/application", headers=headers)
    catalog = initial.json()["integration"]["webhook_field_catalog"]
    assert initial.json()["integration"]["webhook_field_selection"] == {}
    # Every one of the seven events has its own catalog entry, each a
    # list of {field, label} objects.
    assert set(catalog) == {
        "subscription.activated", "subscription.renewed", "subscription.upgraded", "subscription.downgraded",
        "subscription.expired", "subscription.cancelled", "subscription.archived",
    }
    assert {"field": "currency", "label": "Currency"} in catalog["subscription.activated"]
    # No payment/invoice fields ever offered for expired/cancelled/archived
    # (nothing was actually charged at that moment).
    archived_fields = {entry["field"] for entry in catalog["subscription.archived"]}
    assert archived_fields.isdisjoint({"transaction_id", "amount", "invoice_id", "gateway", "payment_type", "total_amount", "tax_amount"})

    # 2026-09-14 follow-up 2: "activated does not have plan name, code,
    # price etc.. where it has to be, same for renewed event there is no
    # plan code, please keep consistency" - webhook_fixed_fields makes
    # every event's ALWAYS-sent fields visible too, so plan_code/
    # plan_name/price aren't just missing from activated's checklist
    # (they're fixed there, not optional) and renewed's plan_code is
    # clearly an optional extra (fixed there is subscription_id only) -
    # nothing looks inconsistent once both groups are shown together.
    fixed = initial.json()["integration"]["webhook_fixed_fields"]
    assert set(fixed) == set(catalog)
    activated_fixed = {entry["field"] for entry in fixed["subscription.activated"]}
    assert {"plan_code", "plan_name", "price", "subscription_id", "email", "phone_number"} <= activated_fixed
    # plan_code must not ALSO appear as a selectable optional field for
    # activated (it's always sent, ticking it would be meaningless).
    assert "plan_code" not in {entry["field"] for entry in catalog["subscription.activated"]}
    assert fixed["subscription.renewed"] == [{"field": "subscription_id", "label": "Subscription ID"}]
    # ...but IS a real selectable optional field for renewed (Vishal's
    # own follow-up 3: renewed's fixed shape is subscription_id only).
    assert "plan_code" in {entry["field"] for entry in catalog["subscription.renewed"]}

    resp = client.put(
        "/api/v1/admin/config/application/integration",
        json={
            "webhook_url": None,
            "webhook_field_selection": {
                "subscription.activated": ["currency", "customer_id"],
                # "amount" is real for renewed but "not_a_real_field" isn't -
                # must be silently dropped, not rejected.
                "subscription.renewed": ["amount", "not_a_real_field"],
                # Not a real event at all - the whole entry must be dropped.
                "subscription.not_a_real_event": ["plan_name"],
            },
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["webhook_field_selection"] == {
        "subscription.activated": ["currency", "customer_id"],
        "subscription.renewed": ["amount"],
    }

    refetched = client.get("/api/v1/admin/config/application", headers=headers)
    assert refetched.json()["integration"]["webhook_field_selection"] == {
        "subscription.activated": ["currency", "customer_id"],
        "subscription.renewed": ["amount"],
    }

    # Restore defaults so later tests aren't affected.
    client.put(
        "/api/v1/admin/config/application/integration",
        json={"webhook_url": None, "webhook_field_selection": None},
        headers=headers,
    )


def test_webhook_samples_all_fields_shows_every_optional_field_regardless_of_saved_selection(client, seeded_db):
    """2026-09-14 follow-up 3: "when select checkbox for parameters, it
    should reflect into sample JSON as well" - the Configuration screen
    updates its JSON preview live, as each checkbox is ticked, without a
    round trip to the server. That only works if webhook_samples_all_fields
    always carries a real sample value for every optional field of every
    event, independent of whatever selection is actually saved right now
    (webhook_samples, by contrast, reflects only the saved selection) - the
    frontend filters this maximal set down to whatever's currently ticked,
    it never invents a value itself."""
    headers = _admin_headers(client)

    # Saved selection is empty by default (see the round-trip test above).
    resp = client.get("/api/v1/admin/config/application", headers=headers)
    integration = resp.json()["integration"]
    assert integration["webhook_field_selection"] == {}

    plain = {s["event"]: s for s in integration["webhook_samples"]}
    maximal = {s["event"]: s for s in integration["webhook_samples_all_fields"]}
    assert set(plain) == set(maximal)

    # With nothing saved, subscription.renewed's plain sample carries only
    # its fixed field...
    assert set(plain["subscription.renewed"]["payload"]["payload"]) == {"subscription_id"}
    # ...but the "all fields" sample must still show every optional field
    # from the catalog (plan_code included) with a real value, so the
    # frontend has something to reveal the instant that box is ticked -
    # not just after a Save round-trip.
    renewed_all = maximal["subscription.renewed"]["payload"]["payload"]
    optional_renewed = {
        entry["field"] for entry in integration["webhook_field_catalog"]["subscription.renewed"]
    }
    assert optional_renewed <= set(renewed_all)
    assert "plan_code" in renewed_all
    assert renewed_all["plan_code"]  # a real, non-empty sample value, not a placeholder


def test_application_config_webhook_samples_cover_all_seven_events_with_trimmed_payloads(client, seeded_db):
    """2026-09 follow-up: 'Webhook for everyticket app are as below...
    show JSON with all data passing / show sample JSON with unique
    information'; follow-up 3: 'Add one more webhook for renew' plus an
    explicit trim of every payload; 2026-09-14 follow-up: upgraded/
    downgraded brought into the same sample list, and every event now
    ALSO exposes admin-selectable OPTIONAL extra fields - but with no
    selection saved (this application's default state), every sample
    below must still show exactly today's fixed payload shape, nothing
    more. The onboarding sample uses this application's real,
    already-seeded registration-form field keys (museum_name,
    contact_person - see app.core.seed); the other five non-onboarding
    events carry nothing but their fixed fields by default, so there's
    no application-specific data left for them to reflect until an admin
    opts in to extra fields."""
    headers = _admin_headers(client)

    client.put(
        "/api/v1/admin/config/application/integration",
        json={"webhook_url": None, "archive_after_days": 21},
        headers=headers,
    )

    resp = client.get("/api/v1/admin/config/application", headers=headers)
    samples = {s["event"]: s for s in resp.json()["integration"]["webhook_samples"]}
    assert set(samples) == {
        "subscription.activated",
        "subscription.renewed",
        "subscription.upgraded",
        "subscription.downgraded",
        "subscription.expired",
        "subscription.cancelled",
        "subscription.archived",
    }

    onboarding = samples["subscription.activated"]["payload"]
    assert onboarding["event_type"] == "subscription.activated"
    assert set(onboarding) == {"event_type", "payload"}  # just the two-field envelope, nothing merged in
    # registration-form answers are spread flat into the payload itself
    # (no nested "registration_data" key) - museum_name is a real seeded
    # form field, not a placeholder.
    assert "museum_name" in onboarding["payload"]
    assert "registration_data" not in onboarding["payload"]
    assert "phone_number" in onboarding["payload"]
    assert "mobile" not in onboarding["payload"]

    for event_type in ("subscription.renewed", "subscription.expired", "subscription.cancelled", "subscription.archived"):
        wire_body = samples[event_type]["payload"]
        assert wire_body["event_type"] == event_type
        assert set(wire_body["payload"]) == {"subscription_id"}

    for event_type in ("subscription.upgraded", "subscription.downgraded"):
        wire_body = samples[event_type]["payload"]
        assert wire_body["event_type"] == event_type
        assert set(wire_body["payload"]) == {
            "subscription_id", "customer_id", "plan_code", "status", "expires_at", "transaction_id",
        }

    # Restore defaults so later tests aren't affected.
    client.put(
        "/api/v1/admin/config/application/integration",
        json={"webhook_url": None, "archive_after_days": None},
        headers=headers,
    )


def test_update_notification_config_changes_outbound_sender_and_smtp_host(client, seeded_db, monkeypatch):
    _FakeSMTP.sent.clear()
    _FakeSMTP.connected_to.clear()
    monkeypatch.setattr(smtp_provider.smtplib, "SMTP", _FakeSMTP)
    headers = _admin_headers(client)

    resp = client.put(
        "/api/v1/admin/config/application/notification",
        json={
            "email_provider": "smtp",
            "smtp_host": "smtp.everyticket-billing.example.com",
            "smtp_port": 2525,
            "email_sender_name": "Everyticket Billing",
            "email_sender_address": "billing@everyticket.example.com",
            "email_reply_to": "support@everyticket.example.com",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["smtp_host"] == "smtp.everyticket-billing.example.com"

    client.post(
        "/api/v1/public/plans/basic/subscribe",
        json={"email": "sender-override@example.com", "mobile": "9833300002", "registration_data": {}},
    )
    client.post("/api/v1/public/identify", json={"email": "sender-override@example.com", "mobile": "9833300002"})

    assert any("Everyticket Billing <billing@everyticket.example.com>" in m for m in _FakeSMTP.sent)
    assert ("smtp.everyticket-billing.example.com", 2525) in _FakeSMTP.connected_to

    # Restore defaults so later tests' emails use the app-wide sender/SMTP again.
    client.put(
        "/api/v1/admin/config/application/notification",
        json={
            "email_provider": "smtp", "smtp_host": None, "smtp_port": None,
            "email_sender_name": None, "email_sender_address": None, "email_reply_to": None,
        },
        headers=headers,
    )


def test_notification_config_defaults_to_enabled(client, seeded_db):
    """2026-09-13 follow-up: "add one more field... 'Enable
    Notifications?'" - every existing/freshly-seeded application must
    default to notifications_enabled=True so nothing changes for anyone
    who hasn't touched this new field."""
    headers = _admin_headers(client)
    resp = client.get("/api/v1/admin/config/application", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["notification"]["notifications_enabled"] is True


def test_disabling_notifications_skips_email_send_without_touching_smtp(client, seeded_db, monkeypatch):
    """The whole point of the toggle: once turned off, an email that would
    otherwise have been sent (here, the OTP email a /public/identify call
    triggers) is skipped before the SMTP provider is ever invoked, and
    logged as SKIPPED (not FAILED - this isn't an error) rather than SENT."""
    _FakeSMTP.sent.clear()
    monkeypatch.setattr(smtp_provider.smtplib, "SMTP", _FakeSMTP)
    headers = _admin_headers(client)

    resp = client.put(
        "/api/v1/admin/config/application/notification",
        json={"notifications_enabled": False, "email_provider": "smtp"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["notifications_enabled"] is False

    client.post(
        "/api/v1/public/plans/basic/subscribe",
        json={"email": "notifs-off@example.com", "mobile": "9833300003", "registration_data": {}},
    )
    client.post("/api/v1/public/identify", json={"email": "notifs-off@example.com", "mobile": "9833300003"})

    # Nothing was actually sent - the fake SMTP transport was never touched.
    assert _FakeSMTP.sent == []

    log = (
        seeded_db.query(NotificationLog)
        .filter(NotificationLog.recipient == "notifs-off@example.com")
        .order_by(NotificationLog.id.desc())
        .first()
    )
    assert log is not None
    assert log.status == NotificationStatus.SKIPPED.value
    assert "disabled" in log.provider_response.lower()


def test_subscription_rules_disable_actually_blocks_the_action(client, seeded_db):
    headers = _admin_headers(client)

    subscribe = client.post(
        "/api/v1/public/plans/basic/subscribe",
        json={"email": "ruletest@example.com", "mobile": "9833300003", "registration_data": {}},
    )
    transaction_id = subscribe.json()["payment"]["transaction_id"]
    client.post("/api/v1/payment/mock/callback", json={"transaction_id": transaction_id, "scenario": "SUCCESS"})

    identify = client.post("/api/v1/public/identify", json={"email": "ruletest@example.com", "mobile": "9833300003"})
    verify = client.post(
        "/api/v1/public/otp/verify", json={"otp_session_id": identify.json()["otp_session_id"], "code": identify.json()["debug_otp_code"]}
    )
    customer_headers = {"Authorization": f"Bearer {verify.json()['access_token']}"}
    subscription_id = subscribe.json()["subscription"]["subscription_id"]

    try:
        client.put(
            "/api/v1/admin/config/application/subscription-rules",
            json={
                "allow_upgrade": False, "allow_downgrade": True, "allow_cancellation": False,
                "cancellation_behavior": "IMMEDIATE", "renewal_enabled": False, "repurchase_enabled": True,
            },
            headers=headers,
        )

        upgrade = client.post(
            f"/api/v1/customer/subscriptions/{subscription_id}/upgrade",
            json={"target_plan_code": "professional"},
            headers=customer_headers,
        )
        assert upgrade.status_code == 403
        assert upgrade.json()["error_code"] == "ACTION_NOT_ALLOWED"

        renew = client.post(f"/api/v1/customer/subscriptions/{subscription_id}/renew", headers=customer_headers)
        assert renew.status_code == 403
        assert renew.json()["error_code"] == "ACTION_NOT_ALLOWED"

        cancel = client.post(
            f"/api/v1/customer/subscriptions/{subscription_id}/cancel", json={"reason": "test"}, headers=customer_headers
        )
        assert cancel.status_code == 403
        assert cancel.json()["error_code"] == "ACTION_NOT_ALLOWED"
    finally:
        client.put(
            "/api/v1/admin/config/application/subscription-rules",
            json={
                "allow_upgrade": True, "allow_downgrade": True, "allow_cancellation": True,
                "cancellation_behavior": "IMMEDIATE", "renewal_enabled": True, "repurchase_enabled": True,
            },
            headers=headers,
        )


def test_security_config_get_defaults_and_round_trips(client, seeded_db):
    headers = _admin_headers(client)
    default = client.get("/api/v1/admin/config/security", headers=headers)
    assert default.status_code == 200, default.text
    assert default.json()["otp_length"] == 6
    assert default.json()["test_mode"] is True  # visible read-only, matches conftest's TEST_MODE=true

    try:
        updated = client.put(
            "/api/v1/admin/config/security",
            json={"otp_length": 4, "otp_expiry_seconds": 300, "otp_max_attempts": 5, "otp_resend_cooldown_seconds": 60},
            headers=headers,
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["otp_length"] == 4

        identify = client.post(
            "/api/v1/public/plans/basic/subscribe",
            json={"email": "otplength@example.com", "mobile": "9833300004", "registration_data": {}},
        )
        assert identify.status_code == 200, identify.text
        resp = client.post("/api/v1/public/identify", json={"email": "otplength@example.com", "mobile": "9833300004"})
        assert len(resp.json()["debug_otp_code"]) == 4
    finally:
        client.put(
            "/api/v1/admin/config/security",
            json={"otp_length": 6, "otp_expiry_seconds": 300, "otp_max_attempts": 5, "otp_resend_cooldown_seconds": 60},
            headers=headers,
        )
