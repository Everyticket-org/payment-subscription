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
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.audit import service as audit_service
from app.core.enums import PaymentStatus
from app.core.exceptions import PaymentTransactionNotFound
from app.core.ids import new_transaction_id
from app.customers.models import Customer
from app.invoices.models import Invoice
from app.invoices.service import generate_invoice
from app.payments.gateways.registry import get_gateway
from app.payments.interfaces.gateway import GatewayPaymentResult
from app.payments.models import PaymentTransaction
from app.plans.models import Plan
from app.subscriptions import service as subscription_service
from app.subscriptions.models import Subscription

_TERMINAL_STATUSES = {PaymentStatus.SUCCESS.value, PaymentStatus.FAILED.value, PaymentStatus.CANCELLED.value}


def create_payment_transaction(
    db: Session,
    *,
    customer: Customer,
    subscription: Subscription,
    plan: Plan,
    payment_type: str,
    gateway_code: str = "mock",
) -> PaymentTransaction:
    gateway = get_gateway(gateway_code)

    transaction = PaymentTransaction(
        transaction_id=new_transaction_id(),
        idempotency_key=str(uuid.uuid4()),
        customer_id=customer.id,
        subscription_id=subscription.id,
        gateway=gateway_code,
        amount=plan.price,
        currency=plan.currency,
        payment_type=payment_type,
        status=PaymentStatus.INITIATED.value,
        request_timestamp=datetime.now(timezone.utc),
    )
    db.add(transaction)
    db.flush()

    result = gateway.create_payment(
        transaction_id=transaction.transaction_id,
        amount=float(plan.price),
        currency=plan.currency,
        metadata={"subscription_id": subscription.subscription_id, "customer_id": customer.customer_id},
    )
    transaction.gateway_transaction_id = result.gateway_transaction_id
    transaction.raw_gateway_response = result.raw_response
    db.add(transaction)
    db.flush()
    return transaction


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
    invoice: Invoice | None = None

    if result.status == PaymentStatus.SUCCESS.value:
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
        # NOTE: this is where subscription.activated should be queued as an
        # outbound Everyticket webhook + confirmation email (spec sections
        # 19, 31, 49). Both are follow-up work - see
        # docs/implementation-status.md - so nothing is dispatched yet.
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
