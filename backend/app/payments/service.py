"""
Payment orchestration (spec sections 23, 26-29, 58).

process_gateway_result() is the single choke point every payment
outcome - mock callback today, PayU webhook once that adapter exists -
flows through. It is the idempotency boundary (spec section 28: N
identical SUCCESS callbacks must produce exactly one activation) and the
financial-transaction-safety boundary (spec section 58: verify -> update
payment -> update subscription -> generate invoice -> commit, with no
external HTTP calls held open inside the transaction - webhook/email
dispatch are queued for background delivery, not called synchronously;
that queuing is not wired up yet, see docs/implementation-status.md).
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.applications.models import Application
from app.audit import service as audit_service
from app.core.enums import PaymentStatus, PaymentType, SubscriptionEventType
from app.core.exceptions import PaymentTransactionNotFound
from app.core.ids import new_transaction_id
from app.customers.models import Customer, CustomerRegistrationData
from app.invoices.models import Invoice
from app.invoices.service import generate_invoice, get_or_render_pdf
from app.notifications.email import service as email_service
from app.payments.gateways.registry import get_gateway
from app.payments.interfaces.gateway import GatewayPaymentResult
from app.payments.models import PaymentTransaction
from app.payments.schemas import PaymentTransactionOut
from app.plans.models import Plan
from app.subscriptions import service as subscription_service
from app.subscriptions.models import Subscription
from app.webhooks import service as webhook_service
from app.webhooks.payloads import onboarding_payload, renewed_payload

logger = logging.getLogger("subscription")

_TERMINAL_STATUSES = {PaymentStatus.SUCCESS.value, PaymentStatus.FAILED.value, PaymentStatus.CANCELLED.value}


def create_payment_transaction(
    db: Session,
    *,
    customer: Customer,
    subscription: Subscription,
    plan: Plan,
    payment_type: str,
    gateway_code: str = "mock",
    gateway_mode: str = "test",
    application: Application | None = None,
) -> PaymentTransaction:
    # `db`+`gateway_mode` resolve the admin-configured, per-mode PayU
    # credentials (app.payments.gateway_config) when this application has
    # any configured, falling back to env vars otherwise - see
    # app.payments.gateways.registry.get_gateway's own docstring. `application`
    # additionally resolves this application's admin-configured PayU
    # redirect/webhook URLs (2026-09 follow-up) - harmless to omit or to
    # pass for the mock gateway, which ignores all of this.
    gateway = get_gateway(gateway_code, db=db, mode=gateway_mode, application=application)

    transaction = PaymentTransaction(
        transaction_id=new_transaction_id(),
        idempotency_key=str(uuid.uuid4()),
        customer_id=customer.id,
        subscription_id=subscription.id,
        target_plan_id=plan.id,
        gateway=gateway_code,
        amount=plan.price,
        currency=plan.currency,
        payment_type=payment_type,
        status=PaymentStatus.INITIATED.value,
        request_timestamp=datetime.now(timezone.utc),
    )
    db.add(transaction)
    db.flush()

    # Redirect-based gateways (PayU) need customer/plan display details the
    # mock gateway ignores. This app doesn't collect a customer name field
    # yet (see docs/implementation-status.md's dynamic-registration-form
    # gap) so firstname is derived from the email's local part - a
    # documented simplification, not a guess at PayU's own API.
    derived_firstname = (customer.email.split("@")[0] if customer.email else "Customer").replace(".", " ").title()
    result = gateway.create_payment(
        transaction_id=transaction.transaction_id,
        amount=float(plan.price),
        currency=plan.currency,
        metadata={
            "subscription_id": subscription.subscription_id,
            "customer_id": customer.customer_id,
            "productinfo": plan.name,
            "firstname": derived_firstname,
            "email": customer.email,
            "phone": customer.mobile,
        },
    )
    transaction.gateway_transaction_id = result.gateway_transaction_id
    transaction.raw_gateway_response = result.raw_response
    # Real bug fixed here: this was never set before, so a PayU payment's
    # status stayed INITIATED forever (instead of PENDING, what PayU's
    # own create_payment() actually reports) until the surl/furl callback
    # arrived - build_payment_out()'s checkout-surfacing check
    # (status == "PENDING") never fired, so the frontend's hosted-
    # checkout redirect form would never have rendered for a real PayU
    # payment. Harmless no-op for the mock gateway, which already
    # reports INITIATED here (its own outcome only ever changes via an
    # explicit simulated callback).
    transaction.status = result.status
    db.add(transaction)
    db.flush()
    return transaction


def build_payment_out(transaction: PaymentTransaction) -> PaymentTransactionOut:
    """Builds the API-facing payment shape, surfacing PayU's hosted-checkout
    form fields (action_url/fields/hash) when this is a redirect-based
    gateway payment still awaiting the customer completing checkout on
    PayU's own page. The mock gateway never sets these - checkout stays
    None and the frontend keeps using its existing "simulate payment"
    buttons."""
    payment_out = PaymentTransactionOut.model_validate(transaction)
    if (
        transaction.gateway == "payu"
        and transaction.status == "PENDING"
        and isinstance(transaction.raw_gateway_response, dict)
        and "fields" in transaction.raw_gateway_response
    ):
        payment_out.checkout = transaction.raw_gateway_response
    return payment_out


def process_gateway_result(
    db: Session, *, transaction: PaymentTransaction, result: GatewayPaymentResult
) -> tuple[PaymentTransaction, Invoice | None]:
    """Returns (updated transaction, invoice if one was generated). Safe to
    call more than once with the same terminal result (idempotency,
    section 28)."""
    if transaction.status in _TERMINAL_STATUSES:
        # Already processed to a terminal state - duplicate callback
        # (spec section 28/54 DUPLICATE_CALLBACK scenario). Do not
        # reprocess; just report current state back to the caller.
        existing_invoice = (
            db.query(Invoice).filter(Invoice.payment_transaction_id == transaction.id).first()
        )
        return transaction, existing_invoice

    transaction.status = result.status
    transaction.response_timestamp = datetime.now(timezone.utc)
    transaction.raw_gateway_response = result.raw_response
    transaction.failure_reason = result.failure_reason
    if result.gateway_transaction_id:
        transaction.gateway_transaction_id = result.gateway_transaction_id
    db.add(transaction)
    db.flush()

    subscription = transaction.subscription
    application = db.get(Application, subscription.application_id)
    invoice: Invoice | None = None
    # Populated below whenever a real Everyticket webhook event is
    # queued for this payment - used AFTER commit (see below) to kick
    # off one immediate, non-blocking delivery attempt per event
    # (2026-09-11 follow-up: "why its not being called properly on
    # payment success" - see webhook_service.attempt_soon()'s docstring
    # for the full explanation).
    queued_webhook_event_ids: list[str] = []

    if result.status == PaymentStatus.SUCCESS.value:
        if transaction.payment_type == PaymentType.UPGRADE.value:
            target_plan = db.query(Plan).filter(Plan.id == transaction.target_plan_id).one()
            subscription_service.apply_plan_change(
                db, subscription=subscription, new_plan=target_plan, event_type=SubscriptionEventType.UPGRADED.value
            )
        elif transaction.payment_type == PaymentType.DOWNGRADE.value:
            target_plan = db.query(Plan).filter(Plan.id == transaction.target_plan_id).one()
            subscription_service.apply_plan_change(
                db, subscription=subscription, new_plan=target_plan, event_type=SubscriptionEventType.DOWNGRADED.value
            )
        elif transaction.payment_type == PaymentType.RENEWAL.value:
            subscription_service.renew_subscription(db, subscription=subscription)
        else:  # PaymentType.NEW
            subscription_service.activate_subscription(db, subscription=subscription)
        invoice = generate_invoice(db, subscription=subscription, payment=transaction)
        audit_service.record(
            db,
            actor="system",
            action="PAYMENT_SUCCEEDED",
            entity_type="payment_transaction",
            entity_id=transaction.transaction_id,
            new_value={"status": transaction.status, "subscription_id": subscription.subscription_id},
        )

        # Outbound Everyticket webhook (spec sections 19, 31, 33): a pure
        # DB write here (see app/webhooks/service.py's module docstring
        # for why) - never synchronously inside this transaction (spec
        # section 58). The real HTTP delivery attempt happens after this
        # transaction commits below: an immediate, backgrounded
        # attempt_soon() call (2026-09-11 follow-up) plus, as a backstop
        # for anything that fails or was somehow missed, the Celery beat
        # sweep in app/webhooks/tasks.py.
        #
        # PaymentType.NEW (first-ever activation, "onboarding") gets its
        # own richer payload - the customer's full registration-form
        # answers plus plan details, trimmed to exactly the fields Vishal
        # asked to keep (2026-09 follow-up 3) - built via
        # app.webhooks.payloads.onboarding_payload so the admin
        # Configuration screen's sample-JSON preview can never drift from
        # what's actually sent (app.api.v1.admin_config calls the same
        # function). RENEWAL is trimmed to just subscription_id, same as
        # expire/cancel/archive below. Upgrade/downgrade are not part of
        # Vishal's numbered webhook list and keep their existing, richer
        # payload shape unchanged.
        if application is not None:
            if transaction.payment_type == PaymentType.NEW.value:
                registration_entry = (
                    db.query(CustomerRegistrationData)
                    .filter(CustomerRegistrationData.subscription_id == subscription.id)
                    .order_by(CustomerRegistrationData.created_at.desc())
                    .first()
                )
                _queued_event = webhook_service.queue_event(
                    db,
                    application=application,
                    event_type="subscription.activated",
                    entity_type="subscription",
                    entity_id=subscription.subscription_id,
                    payload=onboarding_payload(
                        subscription_id=subscription.subscription_id,
                        email=subscription.customer.email,
                        mobile=subscription.customer.mobile,
                        plan_code=subscription.plan.plan_code,
                        plan_name=subscription.plan.name,
                        price=float(subscription.plan.price),
                        is_trial=subscription.is_trial,
                        expires_at=subscription.expires_at.isoformat() if subscription.expires_at else None,
                        registration_data=(registration_entry.data if registration_entry else {}),
                    ),
                )
                if _queued_event is not None:
                    queued_webhook_event_ids.append(_queued_event.event_id)
            elif transaction.payment_type == PaymentType.RENEWAL.value:
                # Trimmed to just subscription_id (2026-09 follow-up 3:
                # "Renew, Expire, Cancel, Archived ... payload with
                # subscription ID") - Everyticket looks up anything else
                # about the subscription by this ID.
                _queued_event = webhook_service.queue_event(
                    db,
                    application=application,
                    event_type="subscription.renewed",
                    entity_type="subscription",
                    entity_id=subscription.subscription_id,
                    payload=renewed_payload(subscription_id=subscription.subscription_id),
                )
                if _queued_event is not None:
                    queued_webhook_event_ids.append(_queued_event.event_id)
            else:
                # UPGRADE/DOWNGRADE - not part of Vishal's numbered webhook
                # list, so these keep their existing, richer payload shape
                # unchanged.
                webhook_event_type = {
                    PaymentType.UPGRADE.value: "subscription.upgraded",
                    PaymentType.DOWNGRADE.value: "subscription.downgraded",
                }[transaction.payment_type]
                _queued_event = webhook_service.queue_event(
                    db,
                    application=application,
                    event_type=webhook_event_type,
                    entity_type="subscription",
                    entity_id=subscription.subscription_id,
                    payload={
                        "subscription_id": subscription.subscription_id,
                        "customer_id": subscription.customer.customer_id,
                        "plan_code": subscription.plan.plan_code,
                        "status": subscription.status,
                        "expires_at": subscription.expires_at.isoformat() if subscription.expires_at else None,
                        "transaction_id": transaction.transaction_id,
                    },
                )
                if _queued_event is not None:
                    queued_webhook_event_ids.append(_queued_event.event_id)
    elif result.status == PaymentStatus.FAILED.value:
        subscription_service.mark_payment_failed(db, subscription=subscription)
        audit_service.record(
            db,
            actor="system",
            action="PAYMENT_FAILED",
            entity_type="payment_transaction",
            entity_id=transaction.transaction_id,
            new_value={"status": transaction.status, "failure_reason": result.failure_reason},
        )
    # PENDING / UNKNOWN (incl. simulated TIMEOUT): leave the subscription in
    # PENDING_PAYMENT untouched - spec section 27, unknown states must never
    # activate a subscription.

    db.commit()
    db.refresh(transaction)

    # Real webhook delivery attempt(s) - AFTER the financial transaction
    # above has committed, same "never inside that commit" rule as the
    # emails below (spec section 58), and non-blocking: attempt_soon()
    # hands off to a background thread with its own DB session, so this
    # request returns exactly as fast as it did before this event was
    # added - it never waits on the outbound HTTP call. Without this, a
    # queued event's very first attempt depended entirely on the Celery
    # beat schedule eventually picking it up (still true for any RETRY
    # after a failure - this only ever makes one immediate attempt).
    for _event_id in queued_webhook_event_ids:
        webhook_service.attempt_soon(_event_id)

    # Confirmation email (spec section 49) - sent AFTER the financial
    # transaction above has committed, never inside it (spec section 58:
    # no external call held open inside that commit). Best-effort; never
    # raises (see email_service's module docstring).
    if result.status == PaymentStatus.SUCCESS.value:
        email_service.send_templated_email(
            db,
            template_code="payment_success",
            to=subscription.customer.email,
            context={
                "plan_name": subscription.plan.name,
                "currency": transaction.currency,
                "amount": f"{float(transaction.amount):.2f}",
                "transaction_id": transaction.transaction_id,
            },
            related_entity_type="payment_transaction",
            related_entity_id=transaction.transaction_id,
            application=application,
        )

        # Invoice PDF email (spec section 45) - best-effort, same as every
        # other email in this module: a PDF render/attach failure must
        # never surface as an error on an already-successful payment.
        if invoice is not None:
            try:
                pdf_bytes = get_or_render_pdf(db, invoice)
            except Exception:
                logger.exception("invoice PDF render failed for %s - skipping invoice email", invoice.invoice_id)
                pdf_bytes = None
            if pdf_bytes:
                email_service.send_templated_email(
                    db,
                    template_code="invoice_generated",
                    to=subscription.customer.email,
                    context={
                        "invoice_id": invoice.invoice_id,
                        "plan_name": subscription.plan.name,
                        "currency": invoice.currency,
                        "amount": f"{float(invoice.amount):.2f}",
                        "tax_amount": f"{float(invoice.tax_amount):.2f}",
                        "total_amount": f"{float(invoice.total_amount):.2f}",
                    },
                    related_entity_type="invoice",
                    related_entity_id=invoice.invoice_id,
                    attachments=[(f"{invoice.invoice_id}.pdf", pdf_bytes, "pdf")],
                    application=application,
                )
    elif result.status == PaymentStatus.FAILED.value:
        email_service.send_templated_email(
            db,
            template_code="payment_failed",
            to=subscription.customer.email,
            context={
                "plan_name": subscription.plan.name,
                "currency": transaction.currency,
                "amount": f"{float(transaction.amount):.2f}",
                "failure_reason": result.failure_reason,
            },
            related_entity_type="payment_transaction",
            related_entity_id=transaction.transaction_id,
            application=application,
        )

    return transaction, invoice


def simulate_mock_callback(db: Session, *, transaction_id: str, scenario: str) -> tuple[PaymentTransaction, Invoice | None]:
    """Admin/testing-module entry point (spec section 54 TEST PAYMENT) and
    what the E2E test drives. Uses the exact same process_gateway_result()
    path a real gateway webhook would use."""
    transaction = (
        db.query(PaymentTransaction).filter(PaymentTransaction.transaction_id == transaction_id).first()
    )
    if transaction is None:
        raise PaymentTransactionNotFound(f"Unknown transaction {transaction_id}")

    gateway = get_gateway(transaction.gateway)
    result = gateway.process_webhook(
        payload={
            "transaction_id": transaction.transaction_id,
            "gateway_transaction_id": transaction.gateway_transaction_id,
            "amount": float(transaction.amount),
            "currency": transaction.currency,
            "scenario": scenario,
        }
    )
    return process_gateway_result(db, transaction=transaction, result=result)
