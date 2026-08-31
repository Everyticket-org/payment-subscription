/**
 * The public subscribe flow, spanning three backend concepts in one page:
 *   1. POST /subscribe - either directly (new customer, or an
 *      already-logged-in customer) or after being refused with
 *      OTP_VERIFICATION_REQUIRED (spec section 9 - an unauthenticated
 *      caller whose email+mobile match an existing account must prove it
 *      via OTP before anything happens on that account).
 *   2. The identify -> OTP verify duplicate-detection flow, inlined here
 *      rather than sending the user away, since it's the natural place
 *      to hit it (also reachable standalone from /login).
 *   3. The mock payment gateway - since there's no real PayU integration
 *      yet, this page exposes the same "simulate a callback" action the
 *      backend's Testing module will eventually offer, so the whole
 *      subscribe -> pay -> active loop is actually exercisable end to
 *      end from the browser.
 *
 * registration_data is collected via DynamicRegistrationForm (spec
 * section 8), driven by whatever active RegistrationFormField rows the
 * admin has configured for this application - no hardcoded field set.
 */
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { identify, simulateMockCallback, subscribe, verifyOtp } from "../../api/endpoints";
import { ApiError } from "../../api/client";
import { ErrorBanner } from "../../components/ErrorBanner";
import { DynamicRegistrationForm, useRegistrationFormFields } from "../../components/DynamicRegistrationForm";
import { PaymentCheckout } from "../../components/PaymentCheckout";
import { useAuth } from "../../context/AuthContext";
import { useToast } from "../../context/ToastContext";
import type { MockCallbackResult, SubscribeResponse } from "../../api/types";

type Step = "form" | "otp" | "payment" | "done";

export function SubscribePage() {
  const { planCode } = useParams<{ planCode: string }>();
  const { customerToken, setCustomerToken } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();

  const [step, setStep] = useState<Step>("form");
  const [email, setEmail] = useState("");
  const [mobile, setMobile] = useState("");
  const [otpSessionId, setOtpSessionId] = useState<string | null>(null);
  const [otpCode, setOtpCode] = useState("");
  const [debugOtpCode, setDebugOtpCode] = useState<string | null>(null);
  const [subscribeResult, setSubscribeResult] = useState<SubscribeResponse | null>(null);
  const [callbackResult, setCallbackResult] = useState<MockCallbackResult | null>(null);
  const [registrationValues, setRegistrationValues] = useState<Record<string, string>>({});
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const { fields: registrationFields, error: registrationFieldsError } = useRegistrationFormFields();

  if (!planCode) {
    return <p>No plan selected.</p>;
  }

  async function doSubscribe(token?: string | null) {
    setBusy(true);
    setError(null);
    try {
      const result = await subscribe(
        planCode!,
        token ? { registration_data: registrationValues } : { email, mobile, registration_data: registrationValues },
        token,
      );
      setSubscribeResult(result);
      setStep("payment");
    } catch (err) {
      if (err instanceof ApiError && err.errorCode === "OTP_VERIFICATION_REQUIRED") {
        // Existing account - walk them through identify + OTP before
        // retrying, rather than just showing the raw refusal.
        try {
          const ident = await identify(email, mobile);
          setOtpSessionId(ident.otp_session_id);
          setDebugOtpCode(ident.debug_otp_code);
          setStep("otp");
        } catch (identifyErr) {
          setError(identifyErr);
          toast.error(identifyErr);
        }
      } else {
        setError(err);
        toast.error(err);
      }
    } finally {
      setBusy(false);
    }
  }

  async function handleFormSubmit(e: FormEvent) {
    e.preventDefault();
    await doSubscribe(null);
  }

  async function handleOtpSubmit(e: FormEvent) {
    e.preventDefault();
    if (!otpSessionId) return;
    setBusy(true);
    setError(null);
    try {
      const result = await verifyOtp(otpSessionId, otpCode);
      setCustomerToken(result.access_token);
      await doSubscribe(result.access_token);
    } catch (err) {
      setError(err);
      toast.error(err);
    } finally {
      setBusy(false);
    }
  }

  async function handleSimulate(scenario: "SUCCESS" | "FAILED") {
    if (!subscribeResult) return;
    setBusy(true);
    setError(null);
    try {
      const result = await simulateMockCallback(subscribeResult.payment.transaction_id, scenario);
      setCallbackResult(result);
      setStep("done");
      if (result.subscription.status === "ACTIVE") {
        toast.success("Subscription activated");
      }
    } catch (err) {
      setError(err);
      toast.error(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <h1>Subscribe to {planCode}</h1>
      <ErrorBanner error={error} />
      <ErrorBanner error={registrationFieldsError} />

      {step === "form" && (
        <>
          {customerToken ? (
            <div className="card">
              <p>You're signed in - subscribe using your existing account.</p>
              {registrationFields && (
                <DynamicRegistrationForm
                  fields={registrationFields}
                  values={registrationValues}
                  onChange={(key, value) => setRegistrationValues((prev) => ({ ...prev, [key]: value }))}
                />
              )}
              <button className="button button-primary" disabled={busy} onClick={() => doSubscribe(customerToken)}>
                {busy ? "Subscribing..." : "Subscribe with my account"}
              </button>
            </div>
          ) : (
            <form className="card" onSubmit={handleFormSubmit}>
              <label>
                Email
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="you@example.com"
                />
              </label>
              <label>
                Mobile
                <input
                  type="tel"
                  required
                  value={mobile}
                  onChange={(e) => setMobile(e.target.value)}
                  placeholder="9XXXXXXXXX"
                />
              </label>
              {registrationFields && (
                <DynamicRegistrationForm
                  fields={registrationFields}
                  values={registrationValues}
                  onChange={(key, value) => setRegistrationValues((prev) => ({ ...prev, [key]: value }))}
                />
              )}
              <button className="button button-primary" type="submit" disabled={busy}>
                {busy ? "Please wait..." : "Continue"}
              </button>
              <p className="hint">
                Already have an account? This will ask you to verify with an OTP instead of creating a
                duplicate one.
              </p>
            </form>
          )}
        </>
      )}

      {step === "otp" && (
        <form className="card" onSubmit={handleOtpSubmit}>
          <p>We found an existing account for that email/mobile. Enter the verification code to continue.</p>
          {debugOtpCode && (
            <p className="hint hint-dev">
              Dev/test mode: the code is <code>{debugOtpCode}</code> (no real SMS/email is sent yet).
            </p>
          )}
          <label>
            Verification code
            <input
              type="text"
              required
              value={otpCode}
              onChange={(e) => setOtpCode(e.target.value)}
              placeholder="6-digit code"
            />
          </label>
          <button className="button button-primary" type="submit" disabled={busy}>
            {busy ? "Verifying..." : "Verify and continue"}
          </button>
        </form>
      )}

      {step === "payment" && subscribeResult && (
        <div className="card">
          <h2>Almost there - complete payment</h2>
          <dl className="summary-list">
            <dt>Plan</dt>
            <dd>{planCode}</dd>
            <dt>Amount</dt>
            <dd>
              {subscribeResult.payment.currency} {subscribeResult.payment.amount.toFixed(2)}
            </dd>
            <dt>Transaction</dt>
            <dd>{subscribeResult.payment.transaction_id}</dd>
            <dt>Status</dt>
            <dd>{subscribeResult.payment.status}</dd>
          </dl>
          <PaymentCheckout payment={subscribeResult.payment} busy={busy} onSimulate={handleSimulate} />
        </div>
      )}

      {step === "done" && callbackResult && (
        <div className="card">
          {callbackResult.subscription.status === "ACTIVE" ? (
            <>
              <h2>Subscription active</h2>
              <p>Your subscription is now active{callbackResult.invoice_id ? ` and invoice ${callbackResult.invoice_id} was generated.` : "."}</p>
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
          ) : (
            <>
              <h2>Payment failed</h2>
              <p>The simulated payment failed. Your subscription was not activated - you can try again.</p>
              <button className="button button-primary" onClick={() => navigate(0)}>
                Try again
              </button>
            </>
          )}
        </div>
      )}
    </section>
  );
}
