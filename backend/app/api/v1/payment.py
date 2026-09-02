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

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.applications.models import Application
from app.core.config import get_settings
from app.payments import service as payment_service
from app.payments.gateways.registry import get_gateway
from app.payments.models import PaymentTransaction
from app.payments.schemas import MockCallbackRequest, PaymentTransactionOut
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


async def _handle_payu_return(request: Request, db: Session) -> RedirectResponse:
    """Shared by both surl and furl - PayU's own docs say the *verified*
    `status` field is authoritative, not which URL PayU happened to hit
    (a merchant-side redirect misconfiguration or a PENDING-then-later-
    reversed transaction could land on either), so both routes below
    delegate here rather than assuming success/failure from the path."""
    settings = get_settings()
    form = await request.form()
    payload = dict(form)
    txnid = payload.get("txnid")

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
    frontend_url = application.return_url if application and application.return_url else settings.FRONTEND_URL

    def _redirect(status: str, **extra: str) -> RedirectResponse:
        params = "&".join([f"status={status}"] + [f"{k}={v}" for k, v in extra.items() if v is not None])
        return RedirectResponse(url=f"{frontend_url.rstrip('/')}/payment/return?{params}", status_code=303)

    if not txnid:
        logger.warning("PayU callback with no txnid in body: %r", payload)
        return _redirect("error", reason="missing_transaction_id")

    transaction = db.query(PaymentTransaction).filter(PaymentTransaction.transaction_id == txnid).first()
    if transaction is None:
        logger.warning("PayU callback for unknown transaction_id=%s", txnid)
        return _redirect("error", reason="unknown_transaction", transaction_id=txnid)

    # Resolve against the admin-configured, per-mode PayU credentials
    # (app.payments.gateway_config) so the reverse-hash verification below
    # uses the SAME salt create_payment_transaction() used to build the
    # request hash for this transaction - falls back to env vars if
    # nothing is configured, same pattern as everywhere else.
    gateway_mode = application.gateway_mode if application is not None else "test"
    gateway = get_gateway(transaction.gateway, db=db, mode=gateway_mode, application=application)
    result = gateway.process_webhook(payload=payload)
    updated_transaction, invoice = payment_service.process_gateway_result(db, transaction=transaction, result=result)

    return _redirect(
        result.status.lower(),
        transaction_id=updated_transaction.transaction_id,
        subscription_id=updated_transaction.subscription.subscription_id,
    )


@router.post("/payu/callback/success")
async def payu_callback_success(request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    return await _handle_payu_return(request, db)


@router.post("/payu/callback/failure")
async def payu_callback_failure(request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    return await _handle_payu_return(request, db)
