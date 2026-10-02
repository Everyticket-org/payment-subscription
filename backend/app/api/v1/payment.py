"""Payment gateway callback API (spec sections 61, 54).

Two very different callback shapes live here:
  - /mock/callback - a plain JSON API the frontend/tests call directly to
    drive the mock gateway (spec section 24 / 54's TEST PAYMENT).
  - /payu/callback/{success,failure} - PayU's own Hosted Checkout redirect
    target (spec sections 25, 28). The CUSTOMER's BROWSER is redirected
    here by PayU with a form-encoded POST body (not a server-to-server
    webhook, and not JSON) after they finish paying on PayU's page, so
    this can't be a normal Depends()-typed Pydantic body - it reads
    whatever fields PayU actually sent via Request.form() and verifies
    the response hash itself (PayUGateway.process_webhook) before
    trusting anything in it, then 302-redirects the browser on to the
    frontend with the verified outcome.
"""
import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.applications.models import Application
from app.core.enums import PaymentEventResult, PaymentEventType
from app.core.exceptions import PaymentStatusTokenInvalid
from app.invoices.models import Invoice
from app.payments import service as payment_service
from app.payments.events import classify_outcome, log_gateway_response_received, record_payment_event
from app.payments.gateway_config import resolve_return_base_url
from app.payments.gateways.registry import get_gateway
from app.payments.models import PaymentTransaction
from app.payments.schemas import MockCallbackRequest, PaymentStatusOut, PaymentTransactionOut
from app.payments.status_token import create_status_token, token_matches
from app.subscriptions.schemas import SubscriptionOut

logger = logging.getLogger("subscription")

router = APIRouter(prefix="/payment", tags=["payment"])


@router.post("/mock/callback")
def mock_callback(body: MockCallbackRequest, db: Session = Depends(get_db)):
    """Simulates a gateway server-side callback (spec section 24, and the
    'TEST PAYMENT' simulator in section 54 will call this same service
    function directly once the admin testing module exists). Idempotent -
    replaying the same transaction_id+scenario after it has already
    reached a terminal state does not reprocess it (spec section 28)."""
    transaction, invoice = payment_service.simulate_mock_callback(
        db, transaction_id=body.transaction_id, scenario=body.scenario
    )
    return {
        "payment": PaymentTransactionOut.model_validate(transaction),
        "subscription": SubscriptionOut.model_validate(transaction.subscription),
        "invoice_id": invoice.invoice_id if invoice else None,
    }


def _redirect_to_result_page(return_base: str, status: str, **extra: str | None) -> RedirectResponse:
    params = {"status": status, **{k: v for k, v in extra.items() if v is not None}}
    return RedirectResponse(url=f"{return_base}/payment/return?{urlencode(params)}", status_code=303)


async def _handle_payu_return(request: Request, db: Session) -> RedirectResponse:
    """Shared by both surl and furl - PayU's own docs say the *verified*
    `status` field is authoritative, not which URL PayU happened to hit
    (a merchant-side redirect misconfiguration or a PENDING-then-later-
    reversed transaction could land on either), so both routes below
    delegate here rather than assuming success/failure from the path.

    Every outcome is recorded as a BROWSER_RETURN payment event
    (app.payments.events), including rejected ones. A verified return
    also carries a short-lived status token (app.payments.status_token)
    so the result page can read the real status from GET
    /payment/{transaction_id}/status instead of trusting the URL."""
    form = await request.form()
    payload = dict(form)
    txnid = payload.get("txnid")
    log_gateway_response_received("browser return", endpoint=request.url.path, payload=payload)

    # Looked up once, up front, and reused below both for return_url (this
    # redirect) and gateway_mode (the reverse-hash verification further
    # down) - same Application row either way, no need to query it twice.
    #
    # return_url (2026-09 follow-up: "PayU redirect back to localhost:4200
    # which is wrong. instead allow to configure return URL") overrides
    # settings.FRONTEND_URL when the admin has configured this application's
    # own frontend URL - same DB-row-overrides-env-fallback pattern as
    # everywhere else.
    application = db.query(Application).filter(Application.code == "EVERYTICKET").first()
    return_base = resolve_return_base_url(application)

    def _log(result: str, **fields) -> None:
        record_payment_event(
            db,
            event_type=PaymentEventType.BROWSER_RETURN.value,
            result=result,
            transaction_id=txnid,
            request=request,
            payload=payload,
            return_url=f"{return_base}/payment/return",
            **fields,
        )

    if not txnid:
        logger.warning("PayU callback with no txnid in body (fields: %s)", sorted(payload))
        _log(PaymentEventResult.MISSING_TXNID.value)
        return _redirect_to_result_page(return_base, "error", reason="missing_transaction_id")

    transaction = db.query(PaymentTransaction).filter(PaymentTransaction.transaction_id == txnid).first()
    if transaction is None:
        logger.warning("PayU callback for unknown transaction_id=%s", txnid)
        _log(PaymentEventResult.UNKNOWN_TXN.value, gateway_status=payload.get("status"))
        return _redirect_to_result_page(return_base, "error", reason="unknown_transaction", transaction_id=txnid)

    # Resolve against the admin-configured, per-mode PayU credentials
    # (app.payments.gateway_config) so the reverse-hash verification below
    # uses the SAME salt create_payment_transaction() used to build the
    # request hash for this transaction - falls back to env vars if
    # nothing is configured, same pattern as everywhere else.
    gateway_mode = application.gateway_mode if application is not None else "test"
    gateway = get_gateway(transaction.gateway, db=db, mode=gateway_mode, application=application)
    result = gateway.process_webhook(payload=payload)
    if not result.hash_verified:
        # Never persist an unauthenticated response: FAILED is terminal, so
        # recording a forged POST would make the genuine PayU callback (or
        # webhook) for this transaction be ignored as a duplicate. No status
        # token either - a forged POST must not unlock someone's payment.
        logger.warning("PayU callback hash verification failed for transaction_id=%s - ignored", txnid)
        _log(
            PaymentEventResult.HASH_FAILED.value,
            hash_verified=False,
            gateway_status=payload.get("status"),
            gateway_transaction_id=payload.get("mihpayid"),
        )
        return _redirect_to_result_page(return_base, "error", reason="verification_failed", transaction_id=txnid)

    previous_status = transaction.status
    updated_transaction, invoice = payment_service.process_gateway_result(db, transaction=transaction, result=result)
    _log(
        classify_outcome(previous_status=previous_status, result_status=result.status, transaction_id=txnid),
        hash_verified=True,
        gateway_status=payload.get("status"),
        gateway_transaction_id=result.gateway_transaction_id,
    )

    return _redirect_to_result_page(
        return_base,
        result.status.lower(),
        transaction_id=updated_transaction.transaction_id,
        subscription_id=updated_transaction.subscription.subscription_id,
        # 2026-09-13 follow-up: lets PaymentReturnPage.tsx tell a brand-new
        # subscription's first payment (NEW) apart from a renewal/upgrade/
        # downgrade, so the configurable post-subscription message only
        # ever shows for a genuinely first-time subscriber.
        payment_type=updated_transaction.payment_type,
        token=create_status_token(updated_transaction.transaction_id),
    )


@router.post("/payu/callback/success")
async def payu_callback_success(request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    return await _handle_payu_return(request, db)


@router.post("/payu/callback/failure")
async def payu_callback_failure(request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    return await _handle_payu_return(request, db)


# Prefix of every subscription txnid (app.core.ids.new_transaction_id). One
# PayU merchant account is shared with the EveryTicket existing site and the
# SaaS backend, each with its own webhook URL; anything without this prefix
# belongs to one of them and is ignored here.
_SUBSCRIPTION_TXNID_PREFIX = "TXN-"


@router.post("/payu/webhook")
async def payu_webhook(request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    """PayU server-to-server webhook (configured on the PayU dashboard) -
    the safety net for when the customer pays but never comes back through
    surl/furl (closed the tab, lost network), which would otherwise leave
    the subscription PENDING although PayU captured the money.

    Same verification and processing as the surl/furl return: the
    reverse hash is checked by PayUGateway.process_webhook, and
    process_gateway_result is idempotent, so the webhook and the browser
    return for one payment can arrive in either order.

    Always answers 200 once the body is understood - including for
    ignored/foreign/forged payloads - so PayU doesn't keep redelivering and
    a forger learns nothing. Only an unexpected processing error returns 500,
    so PayU's own retry delivers the webhook again.

    Every webhook for one of OUR transactions is recorded as a WEBHOOK
    payment event; other systems' payments (no TXN- prefix) are not.
    """
    try:
        form = await request.form()
        payload = dict(form)
    except Exception:
        # Not form-encoded (e.g. a JSON payment-link webhook) - not ours.
        logger.info("PayU webhook ignored: body is not form-encoded")
        return JSONResponse({"status": "ignored"})

    txnid = str(payload.get("txnid") or "")
    if not txnid.startswith(_SUBSCRIPTION_TXNID_PREFIX):
        logger.info("PayU webhook ignored: txnid=%s is not a subscription transaction", txnid or None)
        return JSONResponse({"status": "ignored"})
    log_gateway_response_received("webhook", endpoint=request.url.path, payload=payload)

    def _log(result: str, **fields) -> None:
        record_payment_event(
            db,
            event_type=PaymentEventType.WEBHOOK.value,
            result=result,
            transaction_id=txnid,
            request=request,
            payload=payload,
            gateway_status=payload.get("status"),
            **fields,
        )

    transaction = db.query(PaymentTransaction).filter(PaymentTransaction.transaction_id == txnid).first()
    if transaction is None:
        logger.warning("PayU webhook for unknown transaction_id=%s - ignored", txnid)
        _log(PaymentEventResult.UNKNOWN_TXN.value)
        return JSONResponse({"status": "ignored"})

    # Resolve credentials exactly as the surl/furl return does, so the hash
    # is verified with the same salt that signed this transaction's request.
    application = db.query(Application).filter(Application.code == "EVERYTICKET").first()
    gateway_mode = application.gateway_mode if application is not None else "test"
    gateway = get_gateway(transaction.gateway, db=db, mode=gateway_mode, application=application)
    result = gateway.process_webhook(payload=payload)
    if not result.hash_verified:
        logger.warning("PayU webhook hash verification failed for transaction_id=%s - ignored", txnid)
        _log(PaymentEventResult.HASH_FAILED.value, hash_verified=False, gateway_transaction_id=payload.get("mihpayid"))
        return JSONResponse({"status": "ignored"})

    previous_status = transaction.status
    try:
        updated_transaction, _invoice = payment_service.process_gateway_result(
            db, transaction=transaction, result=result
        )
    except Exception:
        logger.exception("PayU webhook processing FAILED for transaction_id=%s", txnid)
        db.rollback()
        _log(PaymentEventResult.ERROR.value, hash_verified=True, gateway_transaction_id=result.gateway_transaction_id)
        return JSONResponse({"status": "error"}, status_code=500)

    _log(
        classify_outcome(previous_status=previous_status, result_status=result.status, transaction_id=txnid),
        hash_verified=True,
        gateway_transaction_id=result.gateway_transaction_id,
    )
    logger.info("PayU webhook processed: transaction_id=%s status=%s", txnid, updated_transaction.status)
    return JSONResponse({"status": "processed"})


@router.get("/{transaction_id}/status", response_model=PaymentStatusOut)
def payment_status(
    transaction_id: str,
    request: Request,
    token: str = Query(default="", description="Status token from the PayU return redirect"),
    db: Session = Depends(get_db),
) -> PaymentStatusOut:
    """What the /payment/return page shows - read from our database, never
    from the redirect's own status=... query parameter. Requires the
    short-lived token the PayU return redirect carried; a missing,
    expired or mismatched token gets the same 403 as an unknown
    transaction, and is recorded as a STATUS_CHECK event. Successful
    checks are not recorded (the page polls every few seconds)."""
    transaction = None
    if token_matches(token, transaction_id):
        transaction = (
            db.query(PaymentTransaction).filter(PaymentTransaction.transaction_id == transaction_id).first()
        )
    if transaction is None:
        record_payment_event(
            db,
            event_type=PaymentEventType.STATUS_CHECK.value,
            result=PaymentEventResult.TOKEN_REJECTED.value,
            transaction_id=transaction_id,
            request=request,
        )
        raise PaymentStatusTokenInvalid("This payment link has expired or is not valid. Sign in to see your subscription.")

    invoice = db.query(Invoice).filter(Invoice.payment_transaction_id == transaction.id).first()
    subscription = transaction.subscription
    return PaymentStatusOut(
        transaction_id=transaction.transaction_id,
        status=transaction.status,
        payment_type=transaction.payment_type,
        amount=float(transaction.amount),
        currency=transaction.currency,
        plan_code=transaction.target_plan.plan_code,
        plan_name=transaction.target_plan.name,
        subscription_id=subscription.subscription_id,
        subscription_status=subscription.status,
        invoice_id=invoice.invoice_id if invoice else None,
        failure_reason=transaction.failure_reason,
        updated_at=transaction.updated_at,
    )
