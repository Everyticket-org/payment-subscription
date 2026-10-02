"""
PayU reconciliation sweep - the backstop for payments whose browser return
(surl/furl) AND server webhook were both lost. Run every few minutes by
Celery beat (app.payments.tasks); safe to run more than once, because every
outcome goes through the idempotent process_gateway_result().

For each PayU payment still INITIATED/PENDING after
PAYU_RECONCILE_AFTER_MINUTES, asks PayU's Verify Payment API
(PayUGateway.get_payment_status) and:

  PayU "success"   -> apply SUCCESS, if PayU's amount matches ours
                      (a mismatch is logged as AMOUNT_MISMATCH, never applied)
  PayU "failure"   -> apply FAILED, but only once the payment is at least
                      PAYU_RECONCILE_FAIL_AFTER_MINUTES old, so a customer
                      still on PayU's page is never failed early
  PayU "pending"   -> leave it; checked again later
  "Not Found"      -> the customer never submitted payment at PayU; after
                      PAYU_RECONCILE_EXPIRE_AFTER_HOURS it is marked FAILED
                      ("expired") and no longer checked

Checks back off as a payment ages (every run at first, at most every 6
hours later) so abandoned checkouts don't hit PayU every few minutes for a
day. Each check is recorded as a RECONCILE payment event.
"""
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.applications.models import Application
from app.core.config import get_settings
from app.core.enums import PaymentEventResult, PaymentEventType, PaymentStatus
from app.payments import service as payment_service
from app.payments.events import checkout_form, classify_outcome, record_payment_event
from app.payments.gateways.registry import get_gateway
from app.payments.interfaces.gateway import GatewayPaymentResult
from app.payments.models import PaymentEvent, PaymentTransaction

logger = logging.getLogger("subscription")

# Payments older than this are no longer checked at all.
_MAX_AGE = timedelta(days=7)
_MIN_INTERVAL = timedelta(minutes=10)
_MAX_INTERVAL = timedelta(hours=6)


def _aware(value: datetime) -> datetime:
    # MySQL/SQLite DATETIME columns come back naive; every value written by
    # this app is UTC (app.core.database.utcnow).
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _check_interval(age: timedelta) -> timedelta:
    return min(max(age / 4, _MIN_INTERVAL), _MAX_INTERVAL)


def _due(db: Session, transaction: PaymentTransaction, *, age: timedelta, now: datetime) -> bool:
    last_check = (
        db.query(func.max(PaymentEvent.created_at))
        .filter(
            PaymentEvent.transaction_id == transaction.transaction_id,
            PaymentEvent.event_type == PaymentEventType.RECONCILE.value,
        )
        .scalar()
    )
    return last_check is None or now - _aware(last_check) >= _check_interval(age)


def _reconcile_one(
    db: Session, transaction: PaymentTransaction, *, application: Application | None, age: timedelta
) -> str:
    settings = get_settings()
    txnid = transaction.transaction_id
    # Verify with the credential set that signed this payment's form, even
    # if the admin has switched test/live since.
    mode = checkout_form(transaction).get("mode") or (application.gateway_mode if application else "test")
    gateway = get_gateway(transaction.gateway, db=db, mode=mode, application=application)
    result = gateway.get_payment_status(gateway_transaction_id=txnid)
    payu_details = result.raw_response.get("verify_payment") if isinstance(result.raw_response, dict) else None

    def _log(outcome: str) -> str:
        record_payment_event(
            db,
            event_type=PaymentEventType.RECONCILE.value,
            result=outcome,
            transaction_id=txnid,
            gateway_status=(payu_details or {}).get("status"),
            gateway_transaction_id=result.gateway_transaction_id,
            payload=payu_details,
        )
        return outcome

    if result.status == PaymentStatus.SUCCESS.value:
        if abs(result.amount - float(transaction.amount)) > 0.009:
            logger.error(
                "Reconcile: PayU reports SUCCESS for %s with amount %.2f, expected %.2f - NOT applied",
                txnid, result.amount, float(transaction.amount),
            )
            return _log(PaymentEventResult.AMOUNT_MISMATCH.value)
        previous_status = transaction.status
        payment_service.process_gateway_result(db, transaction=transaction, result=result)
        logger.info("Reconcile: applied SUCCESS for %s from PayU Verify Payment API", txnid)
        return _log(classify_outcome(previous_status=previous_status, result_status=result.status, transaction_id=txnid))

    if result.status == PaymentStatus.FAILED.value:
        if age < timedelta(minutes=settings.PAYU_RECONCILE_FAIL_AFTER_MINUTES):
            return _log(PaymentEventResult.STILL_PENDING.value)
        previous_status = transaction.status
        payment_service.process_gateway_result(db, transaction=transaction, result=result)
        logger.info("Reconcile: applied FAILED for %s from PayU Verify Payment API", txnid)
        return _log(classify_outcome(previous_status=previous_status, result_status=result.status, transaction_id=txnid))

    if result.status == "UNKNOWN" and age >= timedelta(hours=settings.PAYU_RECONCILE_EXPIRE_AFTER_HOURS):
        hours = settings.PAYU_RECONCILE_EXPIRE_AFTER_HOURS
        expired = GatewayPaymentResult(
            gateway=transaction.gateway,
            gateway_transaction_id=None,
            status=PaymentStatus.FAILED.value,
            amount=float(transaction.amount),
            currency=transaction.currency,
            raw_response={"reconcile": "expired", "verify_payment": payu_details},
            failure_reason=f"Expired - no payment was made at PayU within {hours} hours",
        )
        payment_service.process_gateway_result(db, transaction=transaction, result=expired)
        logger.info("Reconcile: expired %s - PayU has no record after %d hours", txnid, hours)
        return _log(PaymentEventResult.EXPIRED.value)

    return _log(PaymentEventResult.STILL_PENDING.value)


def reconcile_pending(db: Session, *, now: datetime | None = None) -> dict[str, int]:
    """One sweep. Returns how many payments ended in each outcome (plus
    "skipped" for ones not yet due for another check)."""
    settings = get_settings()
    now = now or datetime.now(timezone.utc)
    newest = now - timedelta(minutes=settings.PAYU_RECONCILE_AFTER_MINUTES)
    oldest = now - _MAX_AGE

    candidates = (
        db.query(PaymentTransaction)
        .filter(
            PaymentTransaction.gateway == "payu",
            PaymentTransaction.status.in_([PaymentStatus.INITIATED.value, PaymentStatus.PENDING.value]),
            PaymentTransaction.created_at <= newest,
            PaymentTransaction.created_at >= oldest,
        )
        .order_by(PaymentTransaction.created_at.asc())
        .all()
    )
    application = db.query(Application).filter(Application.code == "EVERYTICKET").first()

    counts: dict[str, int] = {}
    checked = 0
    for transaction in candidates:
        if checked >= settings.PAYU_RECONCILE_BATCH_SIZE:
            break
        age = now - _aware(transaction.created_at)
        if not _due(db, transaction, age=age, now=now):
            counts["skipped"] = counts.get("skipped", 0) + 1
            continue
        checked += 1
        txnid = transaction.transaction_id
        try:
            outcome = _reconcile_one(db, transaction, application=application, age=age)
        except Exception:
            # Network/HTTP error, bad credentials, or a processing failure -
            # roll back anything half-done; the next sweep tries again.
            logger.exception("Reconcile: check failed for transaction_id=%s - will retry", txnid)
            db.rollback()
            record_payment_event(
                db, event_type=PaymentEventType.RECONCILE.value, result=PaymentEventResult.ERROR.value,
                transaction_id=txnid,
            )
            outcome = PaymentEventResult.ERROR.value
        counts[outcome] = counts.get(outcome, 0) + 1
    return counts
