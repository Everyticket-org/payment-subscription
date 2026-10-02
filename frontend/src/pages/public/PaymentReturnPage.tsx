/**
 * Landing page for PayU's Hosted Checkout redirect (spec section 25).
 *
 * The backend's /api/v1/payment/payu/callback/{success,failure} routes
 * verify PayU's response hash server-side, apply the payment outcome,
 * then redirect the browser here with ?transaction_id=...&token=...
 *
 * What this page shows comes from GET /api/v1/payment/{id}/status (the
 * backend database), never from the redirect's own ?status=..., which
 * anyone can type into the address bar. The token is short-lived and only
 * unlocks this one payment, so a guest who has just subscribed can see
 * their result without signing in.
 *
 * While the payment is still PENDING (PayU hasn't confirmed yet) the page
 * checks again every 5 seconds for up to 2 minutes, so a confirmation that
 * arrives by PayU's server webhook shows up without a reload.
 *
 * A redirect without a token means the backend could not verify PayU's
 * response (?reason=verification_failed | unknown_transaction |
 * missing_transaction_id) - shown as a generic "couldn't confirm" state.
 *
 * 2026-09-13 follow-up: the configurable post-subscription message is
 * shown on success, but ONLY for a first-time subscription
 * (payment_type NEW) - an existing customer renewing or changing plans
 * already has their credentials.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ApiError } from "../../api/client";
import { getPaymentStatus, getPublicMessages } from "../../api/endpoints";
import type { PaymentStatusOut } from "../../api/types";
import { useAuth } from "../../context/AuthContext";
import { formatAmount } from "../../utils/planDisplay";

const POLL_INTERVAL_MS = 5000;
const POLL_LIMIT_MS = 2 * 60 * 1000;
const STEP_LABELS = ["Your details", "Payment", "Confirmation"] as const;
const WAITING_STATUSES = new Set(["INITIATED", "PENDING", "UNKNOWN"]);

function Stepper({ done }: { done: boolean }) {
  return (
    <div className="subscribe-stepper">
      {STEP_LABELS.map((label, i) => {
        const isLast = i === STEP_LABELS.length - 1;
        const isDone = !isLast || done;
        return (
          <div key={label} className={`subscribe-step ${isDone ? "is-done" : "is-current"}`}>
            <span className="subscribe-step-dot">{isDone ? "✓" : i + 1}</span>
            <span className="subscribe-step-label">{label}</span>
            {!isLast && <span className="subscribe-step-line" aria-hidden="true" />}
          </div>
        );
      })}
    </div>
  );
}

export function PaymentReturnPage() {
  const [params] = useSearchParams();
  const { customerToken } = useAuth();
  const transactionId = params.get("transaction_id");
  const token = params.get("token");
  const reason = params.get("reason");
  const paymentTypeHint = params.get("payment_type");

  const [payment, setPayment] = useState<PaymentStatusOut | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [timedOut, setTimedOut] = useState(false);
  const [postSubscriptionMessage, setPostSubscriptionMessage] = useState<string | null>(null);
  const pollRef = useRef<{ timer?: number; cancelled: boolean }>({ cancelled: false });

  const startChecking = useCallback(() => {
    if (!transactionId || !token) return;
    window.clearTimeout(pollRef.current.timer);
    const poll = { cancelled: false, timer: undefined as number | undefined };
    pollRef.current.cancelled = true; // stop any earlier loop
    pollRef.current = poll;
    const startedAt = Date.now();

    const check = async () => {
      try {
        const result = await getPaymentStatus(transactionId, token);
        if (poll.cancelled) return;
        setPayment(result);
        if (WAITING_STATUSES.has(result.status)) {
          if (Date.now() - startedAt < POLL_LIMIT_MS) {
            poll.timer = window.setTimeout(check, POLL_INTERVAL_MS);
          } else {
            setTimedOut(true);
          }
        }
      } catch (err) {
        if (!poll.cancelled) setLoadError(err);
      }
    };
    void check();
  }, [transactionId, token]);

  useEffect(() => {
    startChecking();
    return () => {
      pollRef.current.cancelled = true;
      window.clearTimeout(pollRef.current.timer);
    };
  }, [startChecking]);

  // "Try again" / "Check again" buttons: clear the previous outcome, then
  // start a fresh 2-minute checking window.
  const retry = () => {
    setTimedOut(false);
    setLoadError(null);
    startChecking();
  };

  const succeeded = payment?.status === "SUCCESS";
  const isNewSubscription = (payment?.payment_type ?? paymentTypeHint) === "NEW";

  useEffect(() => {
    if (!succeeded || !isNewSubscription) return;
    getPublicMessages()
      .then((msgs) => setPostSubscriptionMessage(msgs.post_subscription_message))
      .catch(() => {});
  }, [succeeded, isNewSubscription]);

  const accountLink = customerToken ? (
    <Link className="button button-primary" to="/portal">
      Go to my account
    </Link>
  ) : (
    <Link className="button button-primary" to="/login">
      Sign in to my account
    </Link>
  );

  // --- The backend couldn't verify PayU's response (no token issued) ---
  if (!transactionId || !token) {
    return (
      <section>
        <h1>We couldn't confirm this payment</h1>
        <div className="card payment-result">
          <p>
            We couldn't verify the response from PayU{reason ? ` (${reason.replace(/_/g, " ")})` : ""}. If you were
            charged, your subscription updates as soon as PayU confirms the payment to us, and you'll get an email.
          </p>
          {transactionId && (
            <p className="hint">
              Transaction: <code>{transactionId}</code>
            </p>
          )}
          <div className="button-row">
            {accountLink}
            <Link className="button button-secondary" to="/">
              Back to plans
            </Link>
          </div>
        </div>
      </section>
    );
  }

  // --- Token rejected (expired link, e.g. reopened from history) or network error ---
  if (loadError && !payment) {
    const expired = loadError instanceof ApiError && loadError.errorCode === "PAYMENT_STATUS_TOKEN_INVALID";
    return (
      <section>
        <h1>{expired ? "This payment link has expired" : "We couldn't load your payment"}</h1>
        <div className="card payment-result">
          <p>
            {expired
              ? "For your security, this page only shows payment details for a short time. Sign in to see your subscription and invoices."
              : "Check your connection and try again. Your payment itself is not affected."}
          </p>
          <p className="hint">
            Transaction: <code>{transactionId}</code>
          </p>
          <div className="button-row">
            {!expired && (
              <button className="button button-primary" onClick={retry}>
                Try again
              </button>
            )}
            {accountLink}
          </div>
        </div>
      </section>
    );
  }

  // --- First check still in flight ---
  if (!payment) {
    return (
      <section>
        {isNewSubscription && <Stepper done={false} />}
        <div className="card payment-result payment-result-center" aria-live="polite">
          <div className="payment-spinner" aria-hidden="true" />
          <h1>Confirming your payment…</h1>
          <p className="hint">Checking with our server. This takes a few seconds.</p>
        </div>
      </section>
    );
  }

  const transactionLine = (
    <dl className="summary-list payment-result-details">
      <dt>Plan</dt>
      <dd>{payment.plan_name}</dd>
      <dt>Amount</dt>
      <dd>{formatAmount(payment.amount, payment.currency)}</dd>
      <dt>Transaction</dt>
      <dd>
        <code>{payment.transaction_id}</code>
      </dd>
      {payment.invoice_id && (
        <>
          <dt>Invoice</dt>
          <dd>
            <code>{payment.invoice_id}</code> (emailed to you)
          </dd>
        </>
      )}
    </dl>
  );

  // --- SUCCESS ---
  if (succeeded) {
    return (
      <section>
        {isNewSubscription && <Stepper done />}
        <h1>{isNewSubscription ? "You're subscribed" : "Payment successful"}</h1>
        <div className="card payment-result">
          <p>Your payment was received and your subscription is updated.</p>
          {transactionLine}
          {isNewSubscription && postSubscriptionMessage && <p>{postSubscriptionMessage}</p>}
          <div className="button-row">{accountLink}</div>
        </div>
      </section>
    );
  }

  // --- Still waiting for PayU ---
  if (WAITING_STATUSES.has(payment.status)) {
    return (
      <section>
        {isNewSubscription && <Stepper done={false} />}
        <h1>Waiting for PayU to confirm</h1>
        <div className="card payment-result" aria-live="polite">
          {!timedOut ? (
            <div className="payment-waiting">
              <div className="payment-spinner payment-spinner-small" aria-hidden="true" />
              <p>We're checking again every few seconds. You don't need to pay again.</p>
            </div>
          ) : (
            <p>
              This is taking longer than usual. We'll email you as soon as PayU confirms the payment. You don't need
              to pay again.
            </p>
          )}
          {transactionLine}
          <div className="button-row">
            {timedOut && (
              <button className="button button-primary" onClick={retry}>
                Check again
              </button>
            )}
            {accountLink}
          </div>
        </div>
      </section>
    );
  }

  // --- FAILED / CANCELLED ---
  const retryTo = payment.payment_type === "NEW" ? `/subscribe/${payment.plan_code}` : "/portal";
  return (
    <section>
      <h1>Payment didn't go through</h1>
      <div className="card payment-result">
        <p>
          {payment.status === "CANCELLED" ? "The payment was cancelled." : "PayU couldn't complete this payment."}{" "}
          Your subscription hasn't changed.
        </p>
        {payment.failure_reason && <p className="hint">Reason: {payment.failure_reason}</p>}
        {transactionLine}
        <div className="button-row">
          <Link className="button button-primary" to={retryTo}>
            Retry payment
          </Link>
          <Link className="button button-secondary" to="/">
            Choose another plan
          </Link>
        </div>
      </div>
    </section>
  );
}
