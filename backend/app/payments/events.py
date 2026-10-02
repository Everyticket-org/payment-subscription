"""
Payment event log (app.payments.models.PaymentEvent): one append-only row
per thing that happened to a payment - started, browser return, server
webhook, reconciliation check - so an admin can answer "where did this
payment come from, which URL did PayU call back, and did the webhook
arrive?" without digging through server logs.

Two rules every caller relies on:

1. Logging never breaks a payment. record_payment_event() commits its own
   row and swallows (and logs) any error, rolling back only its own
   insert. It must therefore be called only when the session has NO other
   pending work the caller still needs - i.e. after the caller's own
   commit (process_gateway_result() commits internally), or on a path that
   wrote nothing.

2. Only allow-listed gateway fields are stored (sanitize_payload). The
   response hash and anything card-related never reach this table.

source_ip is request.client.host. Behind nginx that is the real client IP
only because uvicorn trusts X-Forwarded-For from 127.0.0.1 by default and
docker-compose.yml runs the backend with host networking, so the host's
nginx connects from 127.0.0.1. If nginx ever runs elsewhere, set uvicorn's
FORWARDED_ALLOW_IPS to its address (never "*" while port 8002 is
reachable directly), and make sure nginx sends X-Forwarded-For.
Source IP and user agent are personal data: rows are purged after
settings.PAYMENT_EVENT_RETENTION_DAYS (purge_old_events).
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.payments.models import PaymentEvent, PaymentTransaction

logger = logging.getLogger("subscription")

# PayU response fields useful for support/troubleshooting. Everything else
# (hash, card number/name/token, customer name/email/phone, udf values) is
# dropped - an allow-list, so a new PayU field is never stored by accident.
_ALLOWED_PAYLOAD_KEYS = frozenset({
    "txnid",
    "mihpayid",
    "status",
    "unmappedstatus",
    "amount",
    "amt",
    "net_amount_debit",
    "mode",
    "PG_TYPE",
    "bankcode",
    "bank_ref_num",
    "error",
    "error_Message",
    "field9",
    "addedon",
    "productinfo",
    "msg",
})

_MAX_LEN = 500


def _clip(value: Any, limit: int = _MAX_LEN) -> str | None:
    if value is None or value == "":
        return None
    text = str(value)
    return text[:limit]


def sanitize_payload(payload: dict[str, Any] | None) -> dict[str, str] | None:
    if not isinstance(payload, dict):
        return None
    cleaned = {k: _clip(v) for k, v in payload.items() if k in _ALLOWED_PAYLOAD_KEYS}
    return {k: v for k, v in cleaned.items() if v is not None} or None


def summarize_payload(payload: dict[str, Any] | None) -> str:
    """Log-safe one-line view of a gateway response: the same allow-listed
    fields as the stored payload (never the hash, card data, email or
    phone), as sorted JSON so log lines are easy to grep and diff."""
    return json.dumps(sanitize_payload(payload) or {}, sort_keys=True, ensure_ascii=False)


def log_gateway_response_received(source: str, *, endpoint: str | None, payload: dict[str, Any] | None) -> None:
    """Logged the moment a PayU response arrives, before any processing, so
    the response is in the logs even if processing later crashes."""
    txnid = payload.get("txnid") if isinstance(payload, dict) else None
    logger.info(
        "PayU %s received: endpoint=%s transaction_id=%s response=%s",
        source, endpoint, txnid, summarize_payload(payload),
    )


# Event results that need a person to look at them (ERROR) or that may be
# probing/misconfiguration (WARNING); everything else is routine (INFO).
_ERROR_RESULTS = frozenset({"LATE_SUCCESS_IGNORED", "AMOUNT_MISMATCH", "ERROR"})
_WARNING_RESULTS = frozenset({"HASH_FAILED", "UNKNOWN_TXN", "MISSING_TXNID", "TOKEN_REJECTED"})


def _log_level(result: str) -> int:
    if result in _ERROR_RESULTS:
        return logging.ERROR
    if result in _WARNING_RESULTS:
        return logging.WARNING
    return logging.INFO


def request_details(request: Request | None) -> dict[str, str | None]:
    """Who/where a request came from. initiated_from prefers Origin (sent
    on cross-origin POSTs such as the frontend calling this API) and falls
    back to Referer."""
    if request is None:
        return {"endpoint": None, "source_ip": None, "user_agent": None, "initiated_from": None}
    headers = request.headers
    return {
        "endpoint": _clip(request.url.path, 255),
        "source_ip": _clip(request.client.host if request.client else None, 64),
        "user_agent": _clip(headers.get("user-agent")),
        "initiated_from": _clip(headers.get("origin") or headers.get("referer")),
    }


def record_payment_event(
    db: Session,
    *,
    event_type: str,
    result: str,
    transaction_id: str | None,
    request: Request | None = None,
    channel: str | None = None,
    gateway_status: str | None = None,
    gateway_transaction_id: str | None = None,
    hash_verified: bool | None = None,
    payload: dict[str, Any] | None = None,
    surl_sent: str | None = None,
    furl_sent: str | None = None,
    return_url: str | None = None,
) -> None:
    """Best-effort: commits one PaymentEvent, never raises. See module
    docstring rule 1 for when it is safe to call.

    Also writes the same event as one log line (level by result, see
    _log_level) - before the DB insert, so it is logged even if the insert
    fails."""
    try:
        details = request_details(request)
        logger.log(
            _log_level(result),
            "Payment event %s/%s: transaction_id=%s endpoint=%s gateway_status=%s mihpayid=%s "
            "hash_verified=%s surl=%s furl=%s response=%s",
            event_type, result, transaction_id, details["endpoint"], gateway_status, gateway_transaction_id,
            hash_verified, surl_sent, furl_sent, summarize_payload(payload),
        )
        db.add(
            PaymentEvent(
                transaction_id=_clip(transaction_id, 30),
                event_type=event_type,
                channel=channel,
                endpoint=details["endpoint"],
                initiated_from=details["initiated_from"] if event_type == "INITIATED" else None,
                surl_sent=_clip(surl_sent),
                furl_sent=_clip(furl_sent),
                return_url=_clip(return_url),
                source_ip=details["source_ip"],
                user_agent=details["user_agent"],
                gateway_status=_clip(gateway_status, 30),
                gateway_transaction_id=_clip(gateway_transaction_id, 150),
                hash_verified=hash_verified,
                result=result,
                payload=sanitize_payload(payload),
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "Could not record payment event %s/%s for transaction_id=%s - payment processing is unaffected",
            event_type, result, transaction_id,
        )


def checkout_form(transaction: PaymentTransaction) -> dict[str, Any]:
    """The PayU checkout form saved when the payment was created - at the
    top level of raw_gateway_response while PENDING, or under "checkout"
    once a gateway response has been merged in
    (app.payments.service.merge_gateway_response)."""
    raw = transaction.raw_gateway_response
    if not isinstance(raw, dict):
        return {}
    form = raw.get("checkout") if isinstance(raw.get("checkout"), dict) else raw
    return form if isinstance(form.get("fields"), dict) else {}


def record_initiated(
    db: Session,
    *,
    transaction: PaymentTransaction,
    channel: str,
    request: Request | None,
    return_url: str | None = None,
) -> None:
    """INITIATED event for a payment the caller has just committed."""
    fields = checkout_form(transaction).get("fields") or {}
    record_payment_event(
        db,
        event_type="INITIATED",
        result="CREATED",
        transaction_id=transaction.transaction_id,
        request=request,
        channel=channel,
        gateway_status=transaction.status,
        surl_sent=fields.get("surl"),
        furl_sent=fields.get("furl"),
        return_url=return_url,
    )


_TERMINAL = {"SUCCESS", "FAILED", "CANCELLED"}


def classify_outcome(*, previous_status: str, result_status: str, transaction_id: str) -> str:
    """What process_gateway_result() actually did with a verified result,
    given the transaction's status BEFORE the call. It ignores anything
    for an already-terminal transaction; a SUCCESS ignored that way means
    PayU may have taken money we never applied, so it is logged as an
    error for a person to follow up."""
    if previous_status not in _TERMINAL:
        return "PROCESSED"
    if result_status == "SUCCESS" and previous_status != "SUCCESS":
        logger.error(
            "LATE SUCCESS ignored: PayU reports SUCCESS for transaction_id=%s, which is already %s - "
            "check PayU and refund or apply manually",
            transaction_id, previous_status,
        )
        return "LATE_SUCCESS_IGNORED"
    return "DUPLICATE_IGNORED"


def purge_old_events(db: Session, *, now: datetime | None = None) -> int:
    """Deletes payment_events rows older than PAYMENT_EVENT_RETENTION_DAYS.
    Returns how many were removed."""
    days = get_settings().PAYMENT_EVENT_RETENTION_DAYS
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    deleted = db.query(PaymentEvent).filter(PaymentEvent.created_at < cutoff).delete(synchronize_session=False)
    db.commit()
    return deleted
