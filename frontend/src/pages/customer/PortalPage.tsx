/**
 * Customer portal: GET /customer/me plus the four subscription-mutation
 * endpoints (upgrade/downgrade/renew/cancel). Upgrade/downgrade/renew all
 * create a new payment transaction that has to clear before anything
 * changes (same as a fresh subscribe) - simulated here the same way
 * SubscribePage does, since there's still no real gateway wired up.
 * Cancel is the one immediate, no-payment mutation (spec section 43).
 */
import { useCallback, useEffect, useState } from "react";
import { customerDownloadInvoicePdf, listPlans, cancelSubscription, downgradeSubscription, getCustomerPortal, renewSubscription, simulateMockCallback, upgradeSubscription } from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { PaymentCheckout } from "../../components/PaymentCheckout";
import { useAuth } from "../../context/AuthContext";
import type { CustomerPortalOut, MockCallbackResult, Plan, SubscribeResponse } from "../../api/types";

function formatDate(iso: string | null): string {
  if (!iso) return "-";
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function PortalPage() {
  const { customerToken, setCustomerToken } = useAuth();
  const [portal, setPortal] = useState<CustomerPortalOut | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [targetPlan, setTargetPlan] = useState<string>("");
  const [cancelReason, setCancelReason] = useState("");
  const [confirmingCancel, setConfirmingCancel] = useState(false);
  const [pendingPayment, setPendingPayment] = useState<SubscribeResponse | null>(null);
  const [lastCallback, setLastCallback] = useState<MockCallbackResult | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    if (!customerToken) return;
    try {
      const [portalData, planList] = await Promise.all([getCustomerPortal(customerToken), listPlans()]);
      setPortal(portalData);
      setPlans(planList);
    } catch (err) {
      setError(err);
    }
  }, [customerToken]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  function signOut() {
    setCustomerToken(null);
  }

  async function handlePlanChange() {
    if (!customerToken || !portal?.active_subscription || !targetPlan) return;
    const current = plans.find((p) => p.plan_code === portal.active_subscription!.plan_code);
    const target = plans.find((p) => p.plan_code === targetPlan);
    if (!current || !target) return;

    setBusy(true);
    setError(null);
    try {
      const mutate = target.price > current.price ? upgradeSubscription : downgradeSubscription;
      const result = await mutate(portal.active_subscription.subscription_id, targetPlan, customerToken);
      setPendingPayment(result);
      setLastCallback(null);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function handleRenew() {
    if (!customerToken || !portal?.active_subscription) return;
    setBusy(true);
    setError(null);
    try {
      const result = await renewSubscription(portal.active_subscription.subscription_id, customerToken);
      setPendingPayment(result);
      setLastCallback(null);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  async function handleCancel() {
    if (!customerToken || !portal?.active_subscription) return;
    setBusy(true);
    setError(null);
    try {
      await cancelSubscription(portal.active_subscription.subscription_id, cancelReason || undefined, customerToken);
      setConfirmingCancel(false);
      setCancelReason("");
      await refresh();
    } catch (err) {
      setError(err);
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
      setLastCallback(result);
      setPendingPayment(null);
      await refresh();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  if (!portal) {
    return (
      <section>
        <h1>My account</h1>
        <ErrorBanner error={error} />
        {!error && <p>Loading...</p>}
      </section>
    );
  }

  const { customer, active_subscription, subscriptions, payments, invoices } = portal;
  const otherPlans = plans.filter((p) => p.plan_code !== active_subscription?.plan_code);

  return (
    <section>
      <div className="page-header-row">
        <h1>My account</h1>
        <button className="button button-secondary" onClick={signOut}>
          Sign out
        </button>
      </div>

      <ErrorBanner error={error} />

      <div className="card">
        <h2>Customer</h2>
        <dl className="summary-list">
          <dt>Customer ID</dt>
          <dd>{customer.customer_id}</dd>
          <dt>Email</dt>
          <dd>{customer.email ?? "-"}</dd>
          <dt>Mobile</dt>
          <dd>{customer.mobile ?? "-"}</dd>
        </dl>
      </div>

      {pendingPayment && (
        <div className="card">
          <h2>Complete payment to apply this change</h2>
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

      {!pendingPayment && lastCallback && (
        <div className="card">
          <p>
            {lastCallback.subscription.status === "ACTIVE"
              ? "Payment succeeded and your subscription is up to date."
              : "That payment failed - your subscription is unchanged."}
          </p>
        </div>
      )}

      <div className="card">
        <h2>Active subscription</h2>
        {active_subscription ? (
          <>
            <dl className="summary-list">
              <dt>Plan</dt>
              <dd>{active_subscription.plan_name}</dd>
              <dt>Status</dt>
              <dd>{active_subscription.status}</dd>
              <dt>Price</dt>
              <dd>
                {active_subscription.currency} {active_subscription.price.toFixed(2)}
              </dd>
              <dt>Renews / expires</dt>
              <dd>{formatDate(active_subscription.expires_at)}</dd>
            </dl>

            <div className="portal-actions">
              <div className="portal-action-group">
                <label>
                  Change plan
                  <select value={targetPlan} onChange={(e) => setTargetPlan(e.target.value)}>
                    <option value="">Select a plan...</option>
                    {otherPlans.map((p) => (
                      <option key={p.plan_code} value={p.plan_code}>
                        {p.name} - {p.currency} {p.price.toFixed(2)}
                      </option>
                    ))}
                  </select>
                </label>
                <button className="button button-primary" disabled={busy || !targetPlan} onClick={handlePlanChange}>
                  Switch plan
                </button>
              </div>

              <button className="button button-secondary" disabled={busy} onClick={handleRenew}>
                Renew now
              </button>

              {!confirmingCancel ? (
                <button className="button button-danger" disabled={busy} onClick={() => setConfirmingCancel(true)}>
                  Cancel subscription
                </button>
              ) : (
                <div className="portal-action-group">
                  <label>
                    Reason (optional)
                    <input type="text" value={cancelReason} onChange={(e) => setCancelReason(e.target.value)} />
                  </label>
                  <p className="hint">Cancellation is immediate - no refund, no future renewal.</p>
                  <div className="button-row">
                    <button className="button button-danger" disabled={busy} onClick={handleCancel}>
                      Confirm cancellation
                    </button>
                    <button className="button button-secondary" disabled={busy} onClick={() => setConfirmingCancel(false)}>
                      Never mind
                    </button>
                  </div>
                </div>
              )}
            </div>
          </>
        ) : (
          <p>No active subscription right now.</p>
        )}
      </div>

      <div className="card">
        <h2>Subscription history</h2>
        <table className="data-table">
          <thead>
            <tr>
              <th>Plan</th>
              <th>Status</th>
              <th>Expires</th>
            </tr>
          </thead>
          <tbody>
            {subscriptions.map((s) => (
              <tr key={s.subscription_id}>
                <td>{s.plan_name}</td>
                <td>{s.status}</td>
                <td>{formatDate(s.expires_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h2>Payments</h2>
        <table className="data-table">
          <thead>
            <tr>
              <th>Transaction</th>
              <th>Amount</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {payments.map((p) => (
              <tr key={p.transaction_id}>
                <td>{p.transaction_id}</td>
                <td>
                  {p.currency} {p.amount.toFixed(2)}
                </td>
                <td>{p.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card">
        <h2>Invoices</h2>
        <table className="data-table">
          <thead>
            <tr>
              <th>Invoice</th>
              <th>Date</th>
              <th>Total</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {invoices.map((inv) => (
              <tr key={inv.invoice_id}>
                <td>{inv.invoice_id}</td>
                <td>{inv.invoice_date}</td>
                <td>
                  {inv.currency} {inv.total_amount.toFixed(2)}
                </td>
                <td>
                  <button
                    className="button button-secondary"
                    onClick={() => {
                      if (customerToken) void customerDownloadInvoicePdf(inv.invoice_id, customerToken);
                    }}
                  >
                    Download PDF
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
