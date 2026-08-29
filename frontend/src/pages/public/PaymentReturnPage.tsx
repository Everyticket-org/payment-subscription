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
 */
import { Link, useSearchParams } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";

export function PaymentReturnPage() {
  const [params] = useSearchParams();
  const { customerToken } = useAuth();
  const status = params.get("status");
  const transactionId = params.get("transaction_id");
  const reason = params.get("reason");

  const succeeded = status === "success";
  const pending = status === "pending";

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
