"""Payment gateway callback API (spec sections 61, 54). Only the mock
gateway's simulated callback is wired up in this pass - the real PayU
callback/webhook endpoint lands with the PayU adapter (follow-up work,
see docs/implementation-status.md)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.payments import service as payment_service
from app.payments.schemas import MockCallbackRequest, PaymentTransactionOut
from app.subscriptions.schemas import SubscriptionOut

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
