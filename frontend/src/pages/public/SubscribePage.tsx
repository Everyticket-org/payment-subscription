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
 *
 * Visual redesign (2026-09-15 follow-up, second pass - "please change
 * layout for plan listing, registration form page as well"). Every
 * handler, effect, state variable and conditional branch below is
 * byte-identical in logic to before this pass; only the markup and
 * classNames changed (plus one purely-derived, presentation-only
 * `currentStepIndex` value used for the new step indicator), scoped
 * under the new .subscribe-page wrapper in index.css so nothing outside
 * this page is affected.
 */
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  getCustomerPortal,
  getPublicMessages,
  identify,
  listPlans,
  simulateMockCallback,
  subscribe,
  verifyOtp,
} from "../../api/endpoints";
import { ApiError } from "../../api/client";
import { ErrorBanner } from "../../components/ErrorBanner";
import { DynamicRegistrationForm, useRegistrationFormFields } from "../../components/DynamicRegistrationForm";
import { PaymentCheckout } from "../../components/PaymentCheckout";
import { useAuth } from "../../context/AuthContext";
import { useToast } from "../../context/ToastContext";
import { isSessionExpired } from "../../utils/authError";
import { sanitizeHtml } from "../../utils/sanitizeHtml";
import type { MockCallbackResult, Plan, SubscribeResponse } from "../../api/types";

type Step = "form" | "otp" | "payment" | "done";

const STEP_LABELS = ["Your details", "Payment", "Confirmation"] as const;

// Small inline icons (no icon-library dependency, same convention as
// PortalPage's local SVG components) used to give the payment/done
// step cards a bit of the same visual polish as the customer portal.
function CardIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="5" width="20" height="14" rx="2.5" />
      <path d="M2 10h20" />
      <path d="M6 15h4" />
    </svg>
  );
}

function CheckCircleIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="9.5" />
      <path d="M8 12.5l2.5 2.5L16 9.5" />
    </svg>
  );
}

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
  const [otherPlans, setOtherPlans] = useState<Plan[]>([]);
  // The plan being subscribed to (this page's own planCode), shown with its
  // full details/features in the same side panel as "Other plans" -
  // Vishal's follow-up: "Show selected Plan on right side with its feature
  // above other plans selection.. keep both things into same card".
  const [selectedPlan, setSelectedPlan] = useState<Plan | null>(null);
  // 2026-09-13 follow-up: the configurable post-subscription confirmation
  // message, shown on the "done" step only for a genuinely first-time
  // subscription (callbackResult.payment.payment_type === "NEW") - never
  // for an existing customer whose /subscribe call was silently auto-
  // routed to an upgrade/downgrade against their existing subscription
  // (spec section 9/22's auto-routing - they already have credentials).
  const [postSubscriptionMessage, setPostSubscriptionMessage] = useState<string | null>(null);
  // Vishal: "One customer can fill registration data once only at first
  // time customer creation. for second time, it will redirect to my
  // subscription page only." A signed-in customer landing here (as
  // opposed to a brand-new visitor) has already given registration data
  // once - "checking" avoids flashing the registration form/card before
  // we know whether to redirect; "active-subscription" is the
  // redirect-in-flight state (an existing customer who already has a
  // subscription manages plan changes from My Subscription > Change plan
  // instead - see ChangePlanPage.tsx); "no-active-subscription" is a
  // lapsed/cancelled customer who's still allowed to buy a new plan here,
  // just without ever being asked for registration data again.
  const [signedInStatus, setSignedInStatus] = useState<
    "not-signed-in" | "checking" | "active-subscription" | "no-active-subscription"
  >("not-signed-in");
  // Set just before the OTP-verify flow authenticates someone, so the
  // general "already signed in on mount" effect below (which reacts to
  // the very same customerToken becoming non-null) skips its own,
  // redundant portal check - handleOtpSubmit does that check itself,
  // inline, since only it knows whether to auto-continue the subscribe
  // afterwards (a fresh OTP verification is a continuation of an
  // in-progress attempt) or a mount-time token just means "show the
  // manual Subscribe-with-my-account option".
  const otpFlowActiveRef = useRef(false);

  const { fields: registrationFields, error: registrationFieldsError } = useRegistrationFormFields();

  useEffect(() => {
    if (otpFlowActiveRef.current) return;
    if (!customerToken) {
      setSignedInStatus("not-signed-in");
      return;
    }
    let cancelled = false;
    setSignedInStatus("checking");
    getCustomerPortal(customerToken)
      .then((portal) => {
        if (cancelled) return;
        if (portal.active_subscription) {
          setSignedInStatus("active-subscription");
          navigate("/portal", { replace: true });
        } else {
          setSignedInStatus("no-active-subscription");
        }
      })
      .catch((err) => {
        if (cancelled) return;
        if (isSessionExpired(err)) {
          // Stale/invalid token - treat this visit as anonymous rather
          // than getting stuck on "checking" forever.
          setCustomerToken(null);
          return;
        }
        // Fail open: an unrelated fetch error shouldn't block someone
        // from at least attempting to subscribe.
        setSignedInStatus("no-active-subscription");
      });
    return () => {
      cancelled = true;
    };
  }, [customerToken, navigate, setCustomerToken]);

  useEffect(() => {
    // Fetched unconditionally alongside otherPlans below rather than only
    // once "done" is reached - one cheap public GET, and it's ready the
    // instant the mock callback resolves rather than adding a visible
    // delay to the "done" step's first render.
    getPublicMessages()
      .then((msgs) => setPostSubscriptionMessage(msgs.post_subscription_message))
      .catch(() => {});
  }, []);

  useEffect(() => {
    // Side panel on this page (spec section 51: "professional, not MVP")
    // so someone mid-subscribe can see/switch to another plan without
    // losing their place - a fetch failure here is non-critical (the
    // panel just stays empty), so it's swallowed rather than surfaced
    // via the page's main ErrorBanner.
    listPlans()
      .then((all) => {
        setSelectedPlan(all.find((p) => p.plan_code === planCode) ?? null);
        setOtherPlans(
          all.filter((p) => {
            if (p.plan_code === planCode) return false;
            // A signed-in customer switching plans here goes through the
            // upgrade/downgrade path (spec follow-up), which never accepts
            // a free trial plan as a target - so don't offer one. A
            // brand-new, not-signed-in visitor can still see and pick a
            // trial plan (a genuinely new subscription, where the one-
            // trial-per-lifetime check runs server-side).
            if (customerToken && p.is_trial) return false;
            return true;
          }),
        );
      })
      .catch(() => {});
  }, [planCode, customerToken]);

  if (!planCode) {
    return <p>No plan selected.</p>;
  }

  async function doSubscribe(token?: string | null) {
    setBusy(true);
    setError(null);
    try {
      // registration_data is only ever sent for a genuinely anonymous
      // (no token) attempt - a brand-new customer, or one who turns out
      // to be existing and gets diverted through the OTP step below. Any
      // token-bearing call, by construction, means an already-identified
      // existing customer (either already signed in, or just OTP-
      // verified) - Vishal: "One customer can fill registration data once
      // only at first time customer creation" - so it's never sent
      // again, even if some was typed into the anonymous form's fields
      // before the OTP detour.
      const result = await subscribe(
        planCode!,
        token ? {} : { email, mobile, registration_data: registrationValues },
        token,
      );
      setSubscribeResult(result);
      if (result.payment.status === "SUCCESS") {
        // A free plan (price 0 - always a trial plan, spec follow-up: a
        // non-trial plan can never be priced at 0) never actually goes
        // through the gateway (2026-09-13 follow-up: "if price of plan is
        // 0 then no need to redirect to payment gateway") -
        // create_payment_transaction() activates it server-side
        // immediately, so the response already reports SUCCESS. Skip the
        // payment step and go straight to "done", the same place a real
        // successful payment simulation lands. invoice_id isn't part of
        // SubscribeResponse (only MockCallbackResult carries it), but the
        // invoice was still generated and emailed server-side - it's just
        // not named on this screen.
        setCallbackResult({ payment: result.payment, subscription: result.subscription, invoice_id: null });
        setStep("done");
        toast.success("Subscription activated");
      } else {
        setStep("payment");
      }
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
    // Marks this token change as "already being handled" so the mount-
    // time signed-in effect (above) doesn't also run its own, redundant
    // portal check for the exact same token - this function decides the
    // outcome itself, inline, since only it knows this is a continuation
    // of an in-progress subscribe attempt rather than someone just
    // arriving at this page already signed in.
    otpFlowActiveRef.current = true;
    try {
      const result = await verifyOtp(otpSessionId, otpCode);
      setCustomerToken(result.access_token);
      // Vishal: "One customer can fill registration data once only at
      // first time customer creation. for second time, it will redirect
      // to my subscription page only." Reaching this OTP step already
      // means this is an existing account (see OTP_VERIFICATION_REQUIRED
      // above) - if they also already have an active subscription, send
      // them to My Subscription (Change plan there) instead of completing
      // a second subscribe here. Only a lapsed/cancelled existing
      // customer (no active subscription) continues the attempt, and
      // even then without the registration_data they may have typed
      // before this detour - doSubscribe() never sends it once a token is
      // involved.
      const existingPortal = await getCustomerPortal(result.access_token);
      if (existingPortal.active_subscription) {
        toast.info("You already have an active subscription - manage it from My Subscription.");
        navigate("/portal");
        return;
      }
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

  // Purely derived, presentation-only - which of the 3 displayed steps
  // ("Your details" covers both the "form" and "otp" sub-states, since
  // OTP is just a detour within giving your details) is current/done.
  // Never read by any handler above; only used by the step indicator JSX
  // below.
  const currentStepIndex = step === "form" || step === "otp" ? 0 : step === "payment" ? 1 : 2;

  return (
    <section className="subscribe-page">
      <div className="portal-page-head">
        <div>
          <div className="portal-eyebrow">
            Everyticket <span className="sep">/</span> Subscribe
          </div>
          <h1>Subscribe to {selectedPlan?.name ?? planCode}</h1>
        </div>
      </div>

      <ErrorBanner error={error} />
      <ErrorBanner error={registrationFieldsError} />

      <div className="subscribe-stepper">
        {STEP_LABELS.map((label, i) => (
          <div
            key={label}
            className={`subscribe-step ${i < currentStepIndex ? "is-done" : i === currentStepIndex ? "is-current" : ""}`}
          >
            <span className="subscribe-step-dot">{i < currentStepIndex ? "✓" : i + 1}</span>
            <span className="subscribe-step-label">{label}</span>
            {i < STEP_LABELS.length - 1 && <span className="subscribe-step-line" aria-hidden="true" />}
          </div>
        ))}
      </div>

      <div className="subscribe-layout">
        <div className="subscribe-main">
          {step === "form" && (
            <>
              {customerToken ? (
                signedInStatus === "checking" || signedInStatus === "active-subscription" ? (
                  // "active-subscription" is the redirect-in-flight state -
                  // this still renders briefly while navigate() takes effect,
                  // so it deliberately shows the same "checking" message
                  // rather than a flash of the subscribe card.
                  <div className="card portal-card">
                    <p>Checking your account...</p>
                  </div>
                ) : (
                  <div className="card portal-card">
                    <p>You're signed in - subscribe using your existing account.</p>
                    {/* No registration form here, ever - Vishal: "One customer
                        can fill registration data once only at first time
                        customer creation." A signed-in customer already gave
                        that data when their account was first created; this
                        branch only renders at all for one that currently has
                        no active subscription (a lapsed/cancelled repurchase),
                        since an active subscriber was already redirected to
                        My Subscription above. */}
                    <button className="button button-primary" disabled={busy} onClick={() => doSubscribe(customerToken)}>
                      {busy ? "Subscribing..." : "Subscribe with my account"}
                    </button>
                  </div>
                )
              ) : (
                <form className="card portal-card" onSubmit={handleFormSubmit}>
                  <label>
                    Email *
                    <input
                      type="email"
                      required
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      placeholder="you@example.com"
                    />
                  </label>
                  <label>
                    Mobile *
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
            <form className="card portal-card" onSubmit={handleOtpSubmit}>
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
            <div className="card portal-card">
              <div className="portal-card-title-row">
                <span className="portal-icon-tag">
                  <CardIcon />
                </span>
                <h2 style={{ margin: 0 }}>Almost there - complete payment</h2>
              </div>
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
            <div className="card portal-card">
              {callbackResult.subscription.status === "ACTIVE" ? (
                <>
                  <div className="portal-card-title-row">
                    <span className="portal-icon-tag" style={{ background: "var(--success-bg)", color: "var(--success)" }}>
                      <CheckCircleIcon />
                    </span>
                    <h2 style={{ margin: 0 }}>Subscription active</h2>
                  </div>
                  <p>Your subscription is now active{callbackResult.invoice_id ? ` and invoice ${callbackResult.invoice_id} was generated.` : "."}</p>
                  <p className="hint">
                    Transaction: <code>{callbackResult.payment.transaction_id}</code>
                  </p>
                  {callbackResult.payment.payment_type === "NEW" && postSubscriptionMessage && (
                    <p>{postSubscriptionMessage}</p>
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
        </div>

        {step !== "done" && (selectedPlan || otherPlans.length > 0) && (
          <aside className="subscribe-plans-panel">
            {selectedPlan && (
              <div className="subscribe-selected-plan">
                <p className="subscribe-selected-plan-eyebrow">Your plan</p>
                <p className="subscribe-selected-plan-name">{selectedPlan.name}</p>
                <p className="plan-price">
                  {selectedPlan.is_trial ? (
                    `Free for ${selectedPlan.trial_period_days ?? "?"} days`
                  ) : (
                    <>
                      {selectedPlan.currency} {selectedPlan.price.toFixed(2)}
                      <span className="plan-interval">
                        {" "}
                        / {selectedPlan.billing_frequency > 1 ? `${selectedPlan.billing_frequency} ` : ""}
                        {selectedPlan.billing_interval}
                        {selectedPlan.billing_frequency > 1 ? "s" : ""}
                      </span>
                    </>
                  )}
                </p>
                {selectedPlan.description && (
                  // Same rich-text description used on the public plans
                  // listing (spec section 51 bullet-point editor) - the
                  // "features" for a plan are exactly this description, so
                  // reuse the same sanitize-then-render treatment here.
                  <div
                    className="plan-description"
                    dangerouslySetInnerHTML={{ __html: sanitizeHtml(selectedPlan.description) }}
                  />
                )}
              </div>
            )}

            {otherPlans.length > 0 && (
              <div className="subscribe-other-plans">
                <h2>Other plans</h2>
                <p className="hint">Not sure this is the right one? Switch before you pay.</p>
                <div className="subscribe-plans-row">
                  {otherPlans.map((p) => (
                    <Link key={p.plan_code} to={`/subscribe/${p.plan_code}`} className="plan-mini-card">
                      <span className="plan-mini-name">{p.name}</span>
                      <span className="plan-mini-price">
                        {p.is_trial ? `Free for ${p.trial_period_days ?? "?"} days` : `${p.currency} ${p.price.toFixed(2)}`}
                      </span>
                    </Link>
                  ))}
                </div>
              </div>
            )}
          </aside>
        )}
      </div>
    </section>
  );
}
