/**
 * Dedicated plan-switch page for the customer portal (frontend request,
 * 2026-09: "Plan switch - will lead to new page like fresh is doing..
 * currently inline form becomes messy" - the old <select> + button
 * inline in PortalPage's Active subscription card is replaced by this
 * page, modeled on the same step flow SubscribePage already uses
 * (pick -> pay -> done), so both flows feel consistent.
 *
 * Reuses the same upgrade/downgrade endpoints and the same mock-payment
 * "simulate a callback" step PortalPage's inline form used - only the
 * layout changes, not the underlying mechanics.
 *
 * Visual redesign (2026-09-15 follow-up, same pass as PortalPage - see
 * that file's header comment for the full request). Every handler,
 * state variable and conditional branch is unchanged; only the markup
 * and classNames changed, scoped under the new portal- and
 * change-plan-page classes in index.css so nothing outside the customer
 * portal is affected.
 */
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  downgradeSubscription,
  getCustomerPortal,
  listPlans,
  simulateMockCallback,
  upgradeSubscription,
} from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { PaymentCheckout } from "../../components/PaymentCheckout";
import { useAuth } from "../../context/AuthContext";
import { useToast } from "../../context/ToastContext";
import { isSessionExpired } from "../../utils/authError";
import { sanitizeHtml } from "../../utils/sanitizeHtml";
import type { CustomerPortalOut, MockCallbackResult, Plan, SubscribeResponse } from "../../api/types";

type Step = "select" | "payment" | "done";

export function ChangePlanPage() {
  const { customerToken, setCustomerToken } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();

  const [portal, setPortal] = useState<CustomerPortalOut | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [step, setStep] = useState<Step>("select");
  const [pendingPayment, setPendingPayment] = useState<SubscribeResponse | null>(null);
  const [callbackResult, setCallbackResult] = useState<MockCallbackResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!customerToken) return;
    Promise.all([getCustomerPortal(customerToken), listPlans()])
      .then(([portalData, planList]) => {
        setPortal(portalData);
        setPlans(planList);
      })
      .catch((err) => {
        // Same reasoning as PortalPage.refresh(): without this, an
        // expired/invalid token leaves `portal` null forever, which keeps
        // this page on its "loading" branch below - the only branch that
        // doesn't render Layout's per-page content, but even that has no
        // effect here since there was never a Sign out control on this
        // page either. Clearing the token lets RequireCustomer redirect
        // to /login instead.
        if (isSessionExpired(err)) {
          setCustomerToken(null);
          return;
        }
        setError(err);
      });
  }, [customerToken, setCustomerToken]);

  function reportError(err: unknown) {
    if (isSessionExpired(err)) {
      setCustomerToken(null);
      return;
    }
    setError(err);
    toast.error(err);
  }

  async function handlePick(target: Plan) {
    if (!customerToken || !portal?.active_subscription) return;
    const current = plans.find((p) => p.plan_code === portal.active_subscription!.plan_code);
    if (!current) return;

    setBusy(true);
    setError(null);
    try {
      const mutate = target.price > current.price ? upgradeSubscription : downgradeSubscription;
      const result = await mutate(portal.active_subscription.subscription_id, target.plan_code, customerToken);
      setPendingPayment(result);
      setStep("payment");
      toast.info("Complete payment to apply the plan change");
    } catch (err) {
      reportError(err);
    } finally {
      setBusy(false);
    }
  }

  async function handleSimulate(scenario: "SUCCESS" | "FAILED") {
    if (!pendingPayment) return;
    setBusy(true);
    setError(null);
    try {
      const result = await simulateMockCallback(pendingPayment.payment.transaction_id, scenario);
      setCallbackResult(result);
      setStep("done");
      if (result.subscription.status === "ACTIVE") {
        toast.success("Plan changed");
      } else {
        toast.error("Payment failed - plan unchanged");
      }
    } catch (err) {
      reportError(err);
    } finally {
      setBusy(false);
    }
  }

  if (!portal) {
    return (
      <section className="change-plan-page">
        <h1>Change plan</h1>
        <ErrorBanner error={error} />
        {!error && <p>Loading...</p>}
      </section>
    );
  }

  if (!portal.active_subscription) {
    return (
      <section className="change-plan-page">
        <h1>Change plan</h1>
        <div className="portal-card" style={{ maxWidth: 480 }}>
          <p style={{ marginBottom: 16 }}>You don't have an active subscription to change.</p>
          <Link className="button button-primary" to="/">
            Browse plans
          </Link>
        </div>
      </section>
    );
  }

  // Free trial plans are never a valid upgrade/downgrade target (a trial
  // can only ever be a brand-new subscription, checked server-side too).
  const otherPlans = plans.filter((p) => p.plan_code !== portal.active_subscription!.plan_code && !p.is_trial);
  const currentPrice = plans.find((c) => c.plan_code === portal.active_subscription!.plan_code)?.price ?? 0;

  return (
    <section className="change-plan-page">
      <div className="portal-page-head">
        <div>
          <div className="portal-eyebrow">
            My Subscription <span className="sep">/</span> Change plan
          </div>
          <h1>Change plan</h1>
          {step === "select" && (
            <p>
              You're currently on <b>{portal.active_subscription.plan_name}</b>. Pick a plan below to switch - you'll
              complete payment before the change takes effect.
            </p>
          )}
        </div>
        <Link className="button button-secondary" to="/portal">
          Back to my account
        </Link>
      </div>

      <ErrorBanner error={error} />

      {step === "select" && (
        <>
          <div className="plan-grid">
            {otherPlans.map((p) => (
              <div className="card plan-card" key={p.plan_code}>
                <h2>{p.name}</h2>
                <p className="plan-price">
                  {p.currency} {p.price.toFixed(2)}
                </p>
                {p.description && (
                  <div
                    className="plan-description"
                    dangerouslySetInnerHTML={{ __html: sanitizeHtml(p.description) }}
                  />
                )}
                <button className="button button-primary" disabled={busy} onClick={() => handlePick(p)}>
                  {p.price > currentPrice ? "Upgrade to this plan" : "Downgrade to this plan"}
                </button>
              </div>
            ))}
          </div>
          {otherPlans.length === 0 && <p className="hint">No other plans available to switch to right now.</p>}
          <p className="hint" style={{ marginTop: 20 }}>
            No proration &middot; no refund &middot; the change applies immediately at the target plan's full price.
          </p>
        </>
      )}

      {step === "payment" && pendingPayment && (
        <div className="portal-card" style={{ maxWidth: 480 }}>
          <h2>Almost there - complete payment</h2>
          <dl className="summary-list">
            <dt>Amount</dt>
            <dd>
              {pendingPayment.payment.currency} {pendingPayment.payment.amount.toFixed(2)}
            </dd>
            <dt>Transaction</dt>
            <dd>{pendingPayment.payment.transaction_id}</dd>
          </dl>
          <PaymentCheckout payment={pendingPayment.payment} busy={busy} onSimulate={handleSimulate} />
        </div>
      )}

      {step === "done" && callbackResult && (
        <div className="portal-card" style={{ maxWidth: 480 }}>
          {callbackResult.subscription.status === "ACTIVE" ? (
            <>
              <h2>Plan changed</h2>
              <p>Your subscription has been updated.</p>
              <button className="button button-primary" onClick={() => navigate("/portal")}>
                Back to my account
              </button>
            </>
          ) : (
            <>
              <h2>Payment failed</h2>
              <p>The simulated payment failed. Your plan was not changed - you can try again.</p>
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
