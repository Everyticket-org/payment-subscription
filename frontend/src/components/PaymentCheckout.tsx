/**
 * Shared "complete this payment" widget used by both SubscribePage and
 * PortalPage (upgrade/downgrade/renew all create a payment the same way
 * a fresh subscribe does). Renders one of two completely different UIs
 * depending on which gateway actually created the payment:
 *
 *   - PayU (payment.checkout is set): a real hosted-checkout redirect.
 *     The browser is sent to PayU's own payment page via an auto-built
 *     form POST (spec section 25) - the customer completes payment there
 *     with PayU's test cards, and PayU redirects back to
 *     /payment/return once done (see PaymentReturnPage).
 *   - Mock (payment.checkout is absent): the existing same-page
 *     "simulate a callback" buttons, unchanged from before PayU existed.
 */
import type { PaymentTransactionOut } from "../api/types";
import { formatAmount } from "../utils/planDisplay";

interface PaymentCheckoutProps {
  payment: PaymentTransactionOut;
  busy: boolean;
  onSimulate: (scenario: "SUCCESS" | "FAILED") => void;
}

function submitPayuForm(actionUrl: string, fields: Record<string, string>) {
  const form = document.createElement("form");
  form.method = "POST";
  form.action = actionUrl;
  form.style.display = "none";
  for (const [name, value] of Object.entries(fields)) {
    const input = document.createElement("input");
    input.type = "hidden";
    input.name = name;
    input.value = value;
    form.appendChild(input);
  }
  document.body.appendChild(form);
  form.submit();
}

export function PaymentCheckout({ payment, busy, onSimulate }: PaymentCheckoutProps) {
  if (payment.checkout) {
    const { action_url, fields, mode } = payment.checkout;
    // Payments created before the backend recorded `mode` fall back to
    // which PayU host the form posts to.
    const isLive = mode ? mode === "live" : !action_url.includes("test.payu.in");
    const amount = formatAmount(payment.amount, payment.currency);
    return (
      <div className="payment-checkout">
        <dl className="payment-summary">
          <div className="payment-summary-row">
            <dt>{fields.productinfo}</dt>
            <dd className="payment-summary-amount">{amount}</dd>
          </div>
          <div className="payment-summary-row payment-summary-meta">
            <dt>Billed to</dt>
            <dd>{fields.email}</dd>
          </div>
        </dl>
        <p className="payment-notice">
          Keep this tab open. Don't refresh or press Back while you pay - you'll come back here automatically.
        </p>
        {isLive ? (
          <p className="hint">You'll pay on PayU's secure payment page.</p>
        ) : (
          <p className="hint">
            Test mode: you'll be taken to PayU's test payment page. Use one of{" "}
            <a href="https://docs.payu.in/docs/test-cards-upi-id-and-wallets" target="_blank" rel="noreferrer">
              PayU's published test cards
            </a>{" "}
            to complete or decline the payment there - nothing here simulates the outcome.
          </p>
        )}
        <button
          className="button button-primary"
          disabled={busy}
          onClick={() => submitPayuForm(action_url, fields as unknown as Record<string, string>)}
        >
          {isLive ? `Pay ${amount} securely` : "Continue to PayU test payment"}
        </button>
      </div>
    );
  }

  return (
    <div>
      <p className="hint hint-dev">
        No real payment gateway is configured for this application (set PAYU_MERCHANT_KEY/SALT and switch
        the application's gateway to "payu" to test the real flow) - this simulates the gateway callback the
        same way a real webhook would arrive.
      </p>
      <div className="button-row">
        <button className="button button-primary" disabled={busy} onClick={() => onSimulate("SUCCESS")}>
          Simulate payment success
        </button>
        <button className="button button-secondary" disabled={busy} onClick={() => onSimulate("FAILED")}>
          Simulate payment failure
        </button>
      </div>
    </div>
  );
}
