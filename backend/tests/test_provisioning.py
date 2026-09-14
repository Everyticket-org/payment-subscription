"""
Everyticket provisioning result handling (spec sections 32, 37 - Phase 1
acceptance checklist items "Provisioning failure works" / "Provisioning
retry works").

Before this, Subscription.provisioning_status/ProvisioningStatus/
ProvisioningFailed all existed as columns/enums/exceptions but nothing
ever transitioned provisioning_status away from NOT_STARTED, so a real
Everyticket integration failure would never have been visible anywhere
(admin dashboard's "provisioning_failures" count would always read 0).
This file exercises the real behavior added to
app.webhooks.service._attempt_one(): parsing Everyticket's response body
to a subscription.activated delivery (not just its HTTP status),
transitioning provisioning_status accordingly, upserting the
CustomerApplicationMapping, and emailing the customer once on first
failure - reusing the exact same queue_event()/dispatch_pending() split
and httpx.MockTransport pattern tests/test_webhooks.py already
establishes, but against a REAL Subscription row (via
tests/test_invoices.py's _paid_subscription() helper) so provisioning_status
is actually asserted end-to-end.
"""
import httpx

from app.applications.models import Application, CustomerApplicationMapping
from app.core.enums import ProvisioningStatus
from app.notifications.email.providers.smtp import provider as smtp_provider
from app.webhooks import service as webhook_service
from app.webhooks.models import WebhookDelivery

from tests.test_admin_api import _admin_headers
from tests.test_invoices import _basic_plan, _paid_subscription


class _FakeSMTP:
    def __init__(self, host, port, timeout=10):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        pass

    def sendmail(self, from_addr, to_addrs, message):
        self.__class__.sent.append(message)


_FakeSMTP.sent = []


def _configure_webhook_destination(db) -> Application:
    application, _plan = _basic_plan(db)
    application.webhook_url = "http://everyticket.example.com/hooks"
    application.webhook_secret = "test-secret"
    db.add(application)
    db.flush()
    return application


def test_activation_queue_sets_provisioning_in_progress(seeded_db):
    _configure_webhook_destination(seeded_db)
    _customer, subscription, _txn, _invoice = _paid_subscription(seeded_db, email="prov-progress@example.com", mobile="9822400001")
    seeded_db.refresh(subscription)
    assert subscription.provisioning_status == ProvisioningStatus.IN_PROGRESS.value


def test_successful_provisioning_response_marks_success_and_stores_mapping(seeded_db):
    """2026-09-14 follow-up ("can we use subscription ID? as we are
    sending to everyticket"): the mapping's external_customer_id is now
    always THIS app's own subscription_id, set unconditionally - never
    whatever Everyticket's response body says under "external_customer_id"
    (here deliberately sent as a different-looking value, "MUSEUM-1001",
    to prove it's ignored). instance_id is unaffected - still read from
    Everyticket's response as before."""
    application = _configure_webhook_destination(seeded_db)
    customer, subscription, _txn, _invoice = _paid_subscription(seeded_db, email="prov-success@example.com", mobile="9822400002")
    seeded_db.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True, "external_customer_id": "MUSEUM-1001", "instance_id": "INSTANCE-1001"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    webhook_service.dispatch_pending(seeded_db, http_client=client)

    seeded_db.refresh(subscription)
    assert subscription.provisioning_status == ProvisioningStatus.SUCCESS.value

    mapping = (
        seeded_db.query(CustomerApplicationMapping)
        .filter(CustomerApplicationMapping.customer_id == customer.id, CustomerApplicationMapping.application_id == application.id)
        .one()
    )
    assert mapping.external_customer_id == subscription.subscription_id
    assert mapping.external_customer_id != "MUSEUM-1001"
    assert mapping.external_instance_id == "INSTANCE-1001"


def test_successful_provisioning_stores_mapping_even_when_everyticket_omits_external_customer_id(seeded_db):
    """The whole point of the 2026-09-14 follow-up above: Everyticket
    doesn't need to implement the external_customer_id part of the
    response contract at all anymore - a bare {"success": true}, with no
    external_customer_id and no instance_id, must still produce a working
    mapping (external_customer_id = this app's own subscription_id;
    external_instance_id stays unset since Everyticket never sent one)."""
    application = _configure_webhook_destination(seeded_db)
    customer, subscription, _txn, _invoice = _paid_subscription(
        seeded_db, email="prov-minimal-response@example.com", mobile="9822400007"
    )
    seeded_db.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    webhook_service.dispatch_pending(seeded_db, http_client=client)

    seeded_db.refresh(subscription)
    assert subscription.provisioning_status == ProvisioningStatus.SUCCESS.value

    mapping = (
        seeded_db.query(CustomerApplicationMapping)
        .filter(CustomerApplicationMapping.customer_id == customer.id, CustomerApplicationMapping.application_id == application.id)
        .one()
    )
    assert mapping.external_customer_id == subscription.subscription_id
    assert mapping.external_instance_id is None


def test_explicit_failure_body_on_2xx_is_treated_as_provisioning_failure(seeded_db):
    """Spec section 32: a 2xx HTTP status alone doesn't mean provisioning
    succeeded - Everyticket's own {success: false} in the body must also
    fail the delivery so it gets retried, not just leave
    provisioning_status stuck on a false SUCCESS."""
    _configure_webhook_destination(seeded_db)
    _customer, subscription, _txn, _invoice = _paid_subscription(seeded_db, email="prov-explicitfail@example.com", mobile="9822400003")
    seeded_db.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": False, "error": "museum name already exists"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    webhook_service.dispatch_pending(seeded_db, http_client=client)

    seeded_db.refresh(subscription)
    assert subscription.provisioning_status == ProvisioningStatus.FAILED.value

    delivery = seeded_db.query(WebhookDelivery).one()
    assert delivery.status == "FAILED"
    assert delivery.next_retry_at is not None


def test_failed_delivery_marks_provisioning_failed_and_emails_once(seeded_db, monkeypatch):
    _FakeSMTP.sent.clear()
    monkeypatch.setattr(smtp_provider.smtplib, "SMTP", _FakeSMTP)

    _configure_webhook_destination(seeded_db)
    _customer, subscription, _txn, _invoice = _paid_subscription(seeded_db, email="prov-fail@example.com", mobile="9822400004")
    seeded_db.commit()

    def failing_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="museum service unavailable")

    client = httpx.Client(transport=httpx.MockTransport(failing_handler))
    webhook_service.dispatch_pending(seeded_db, http_client=client)

    seeded_db.refresh(subscription)
    assert subscription.provisioning_status == ProvisioningStatus.FAILED.value
    # _paid_subscription() already triggers its own payment_success/
    # invoice_generated emails as side effects - filter to just the new
    # provisioning_issue template's own distinctive text.
    provisioning_emails = [m for m in _FakeSMTP.sent if "finishing setup with our integration partner" in m]
    assert len(provisioning_emails) == 1

    # Force the delivery due again right now and fail a second time -
    # still FAILED, and still only ONE provisioning_issue email total (no
    # repeat spam while the automatic retry schedule works through its
    # backoff).
    delivery = seeded_db.query(WebhookDelivery).one()
    from datetime import datetime, timezone

    delivery.next_retry_at = datetime.now(timezone.utc)
    seeded_db.commit()
    webhook_service.dispatch_pending(seeded_db, http_client=client)

    seeded_db.refresh(subscription)
    assert subscription.provisioning_status == ProvisioningStatus.FAILED.value
    provisioning_emails = [m for m in _FakeSMTP.sent if "finishing setup with our integration partner" in m]
    assert len(provisioning_emails) == 1


def test_provisioning_recovers_on_a_later_successful_retry(seeded_db):
    application = _configure_webhook_destination(seeded_db)
    customer, subscription, _txn, _invoice = _paid_subscription(seeded_db, email="prov-recover@example.com", mobile="9822400005")
    seeded_db.commit()

    def failing_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="temporarily down")

    client = httpx.Client(transport=httpx.MockTransport(failing_handler))
    webhook_service.dispatch_pending(seeded_db, http_client=client)
    seeded_db.refresh(subscription)
    assert subscription.provisioning_status == ProvisioningStatus.FAILED.value

    delivery = seeded_db.query(WebhookDelivery).one()
    from datetime import datetime, timezone

    delivery.next_retry_at = datetime.now(timezone.utc)
    seeded_db.commit()

    def succeeding_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True, "external_customer_id": "MUSEUM-2002", "instance_id": "INSTANCE-2002"})

    recovered_client = httpx.Client(transport=httpx.MockTransport(succeeding_handler))
    webhook_service.dispatch_pending(seeded_db, http_client=recovered_client)

    seeded_db.refresh(subscription)
    assert subscription.provisioning_status == ProvisioningStatus.SUCCESS.value
    mapping = (
        seeded_db.query(CustomerApplicationMapping)
        .filter(CustomerApplicationMapping.customer_id == customer.id, CustomerApplicationMapping.application_id == application.id)
        .one()
    )
    # Same 2026-09-14 follow-up as the test above: the response's own
    # "external_customer_id" ("MUSEUM-2002") is ignored - this app's own
    # subscription_id is what gets stored.
    assert mapping.external_customer_id == subscription.subscription_id


def test_admin_cannot_manually_retry_an_already_succeeded_delivery(client, seeded_db):
    _configure_webhook_destination(seeded_db)
    _customer, _subscription, _txn, _invoice = _paid_subscription(seeded_db, email="prov-noretry@example.com", mobile="9822400006")
    seeded_db.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": True, "external_customer_id": "MUSEUM-3003", "instance_id": "INSTANCE-3003"})

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    webhook_service.dispatch_pending(seeded_db, http_client=mock_client)

    delivery = seeded_db.query(WebhookDelivery).one()
    headers = _admin_headers(client)
    resp = client.post(f"/api/v1/admin/webhooks/deliveries/{delivery.id}/retry", headers=headers)
    assert resp.status_code == 409, resp.text
    assert resp.json()["error_code"] == "WEBHOOK_ALREADY_DELIVERED"
