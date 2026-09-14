/**
 * Landing page for PayU's Hosted Checkout redirect (spec section 25).
 *
 * The backend's /api/v1/payment/payu/callback/{success,failure} routes
 * verify PayU's response hash server-side, apply the payment outcome,
 * then 302-redirect the browser here with the VERIFIED status - this
 * page never re-derives success/failure itself, it just reads what the
 * backend already decided (?status=..., matching PaymentStatus values
 * lowercased: success | failed | pending | cancelled | unknown | error).
 *
 * If the customer was already signed in (e.g. upgrading from the portal),
 * their token is untouched in localStorage across this full-page
 * redirect round trip, so "Go to my account" works immediately. A brand
 * new subscriber has no token yet at this point - only the OTP login flow
 * issues one - so they're pointed at /login instead.
 *
 * 2026-09-13 follow-up ("show message '...you will get your credentials
 * in sometime' for first time subscription... This message also should
 * be configurable"): the redirect now also carries ?payment_type=
 * NEW|RENEWAL|UPGRADE|DOWNGRADE (app/api/v1/payment.py) - the
 * configurable message is fetched and shown right after the Transaction
 * line, but ONLY when payment_type is exactly "NEW", so an existing
 * customer renewing or changing plans (they already have credentials)
 * never sees it.
 */
import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { getPublicMessages } from "../../api/endpoints";
import { useAuth } from "../../context/AuthContext";

export function PaymentReturnPage() {
  const [params] = useSearchParams();
  const { customerToken } = useAuth();
  const status = params.get("status");
  const transactionId = params.get("transaction_id");
  const paymentType = params.get("payment_type");
  const reason = params.get("reason");
  const [postSubscriptionMessage, setPostSubscriptionMessage] = useState<string | null>(null);

  const succeeded = status === "success";
  const pending = status === "pending";
  const isNewSubscription = paymentType === "NEW";

  useEffect(() => {
    if (!succeeded || !isNewSubscription) return;
    getPublicMessages()
      .then((msgs) => setPostSubscriptionMessage(msgs.post_subscription_message))
      .catch(() => {});
  }, [succeeded, isNewSubscription]);

  return (
    <section>
      <h1>{succeeded ? "Payment successful" : pending ? "Payment pending" : "Payment unsuccessful"}</h1>
      <div className="card">
        {succeeded && (
          <>
            <p>Your payment was completed on PayU and your subscription has been updated.</p>
            {transactionId && (
              <p className="hint">
                Transaction: <code>{transactionId}</code>
              </p>
            )}
            {isNewSubscription && postSubscriptionMessage && <p>{postSubscriptionMessage}</p>}
            {customerToken ? (
              <Link className="button button-primary" to="/portal">
                Go to my account
              </Link>
            ) : (
              <>
                <p className="hint">Sign in with the OTP flow to view your subscription any time.</p>
                <Link className="button button-primary" to="/login">
                  Sign in
                </Link>
              </>
            )}
          </>
        )}

        {pending && (
          <>
            <p>
              PayU hasn't reported a final outcome for this payment yet. If you completed payment, check back
              shortly - it will be applied as soon as PayU's confirmation arrives.
            </p>
            {transactionId && (
              <p className="hint">
                Transaction: <code>{transactionId}</code>
              </p>
            )}
            <Link className="button button-primary" to="/">
              Back to plans
            </Link>
          </>
        )}

        {!succeeded && !pending && (
          <>
            <p>
              {status === "error"
                ? "Something went wrong processing the return from PayU."
                : "PayU reported this payment was not successful."}
              {reason ? ` (${reason.replace(/_/g, " ")})` : ""}
            </p>
            {transactionId && (
              <p className="hint">
                Transaction: <code>{transactionId}</code>
              </p>
            )}
            <p className="hint">Your subscription was not changed - you can try again.</p>
            <Link className="button button-primary" to="/">
              Back to plans
            </Link>
          </>
        )}
      </div>
    </section>
  );
}
