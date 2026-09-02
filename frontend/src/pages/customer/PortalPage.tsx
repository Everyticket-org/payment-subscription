/**
 * Customer portal: GET /customer/me plus the four subscription-mutation
 * endpoints (upgrade/downgrade/renew/cancel). Upgrade/downgrade/renew all
 * create a new payment transaction that has to clear before anything
 * changes (same as a fresh subscribe) - simulated here the same way
 * SubscribePage does, since there's still no real gateway wired up.
 * Cancel is the one immediate, no-payment mutation (spec section 43).
 *
 * Layout (frontend request, 2026-09): account identity + registration-
 * form details share one card, the active subscription (with change-plan
 * / renew+cancel actions) is its own card, and a single combined table
 * below replaces the old separate subscription-history / payments /
 * invoices tables - one row per subscription, correlated with that
 * subscription's most recent payment (PaymentTransactionOut.subscription_ref)
 * and, when that payment cleared, the invoice it produced
 * (InvoiceOut.transaction_id). See backend app/api/v1/customer.py's
 * get_portal() for where those correlation fields are populated.
 */
import { Fragment, useCallback, useEffect, useState } from "react";
import {
  customerDownloadInvoicePdf,
  getRegistrationForm,
  listPlans,
  cancelSubscription,
  downgradeSubscription,
  getCustomerPortal,
  renewSubscription,
  simulateMockCallback,
  upgradeSubscription,
} from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { PaymentCheckout } from "../../components/PaymentCheckout";
import { StatusBadge } from "../../components/StatusBadge";
import { useAuth } from "../../context/AuthContext";
import { useToast } from "../../context/ToastContext";
import type {
  CustomerPortalOut,
  InvoiceOut,
  MockCallbackResult,
  PaymentTransactionOut,
  Plan,
  PortalSubscriptionOut,
  RegistrationFormFieldOut,
  SubscribeResponse,
} from "../../api/types";

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "-";
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function formatBillingCycle(interval: string, frequency: number): string {
  if (frequency === 1) {
    if (interval === "month") return "Monthly";
    if (interval === "year") return "Annual";
  }
  return `Every ${frequency} ${interval}${frequency > 1 ? "s" : ""}`;
}

function latestPaymentFor(subscriptionId: string, payments: PaymentTransactionOut[]): PaymentTransactionOut | null {
  const matches = payments.filter((p) => p.subscription_ref === subscriptionId);
  if (matches.length === 0) return null;
  // GET /customer/me already orders payments by created_at desc, but sort
  // defensively rather than assume that ordering survives the filter.
  return [...matches].sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""))[0];
}

function invoiceForPayment(payment: PaymentTransactionOut | null, invoices: InvoiceOut[]): InvoiceOut | null {
  if (!payment) return null;
  return invoices.find((inv) => inv.transaction_id === payment.transaction_id) ?? null;
}

export function PortalPage() {
  const { customerToken, setCustomerToken } = useAuth();
  const toast = useToast();
  const [portal, setPortal] = useState<CustomerPortalOut | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [formFields, setFormFields] = useState<RegistrationFormFieldOut[]>([]);
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
      const [portalData, planList, fields] = await Promise.all([
        getCustomerPortal(customerToken),
        listPlans(),
        getRegistrationForm().catch(() => []),
      ]);
      setPortal(portalData);
      setPlans(planList);
      setFormFields(fields);
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
      toast.info("Complete payment to apply the plan change");
    } catch (err) {
      setError(err);
      toast.error(err);
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
      toast.info("Complete payment to renew");
    } catch (err) {
      setError(err);
      toast.error(err);
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
      toast.success("Subscription cancelled");
      await refresh();
    } catch (err) {
      setError(err);
      toast.error(err);
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
      if (result.subscription.status === "ACTIVE") {
        toast.success("Payment succeeded - subscription updated");
      } else {
        toast.error("Payment failed - subscription unchanged");
      }
      await refresh();
    } catch (err) {
      setError(err);
      toast.error(err);
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

  const { customer, registration_data, active_subscription, subscriptions, payments, invoices } = portal;
  // Free trial plans are never a valid upgrade/downgrade target (spec
  // follow-up: a trial can only ever be a brand-new subscription, checked
  // server-side too in customer.py's _change_plan) - excluded here so the
  // dropdown never offers a choice the backend would refuse anyway.
  const otherPlans = plans.filter((p) => p.plan_code !== active_subscription?.plan_code && !p.is_trial);
  const fieldLabels = new Map(formFields.map((f) => [f.field_key, f.label]));

  return (
    <section className="portal-page">
      <div className="page-header-row page-header-row-wide">
        <h1>My account</h1>
        <button className="button button-secondary" onClick={signOut}>
          Sign out
        </button>
      </div>

      <ErrorBanner error={error} />

      <div className="detail-grid">
        <div className="card card-wide">
          <h2>Account</h2>
          <dl className="summary-list">
            <dt>Customer ID</dt>
            <dd>{customer.customer_id}</dd>
            <dt>Email</dt>
            <dd>{customer.email ?? "-"}</dd>
            <dt>Mobile</dt>
            <dd>{customer.mobile ?? "-"}</dd>
          </dl>
          {registration_data.length > 0 && (
            <>
              <h3>Registration details</h3>
              <dl className="summary-list">
                {registration_data.flatMap((entry) =>
                  Object.entries(entry.data).map(([key, value]) => (
                    <Fragment key={`${entry.created_at}-${key}`}>
                      <dt>{fieldLabels.get(key) ?? key}</dt>
                      <dd>{String(value ?? "-")}</dd>
                    </Fragment>
                  )),
                )}
              </dl>
            </>
          )}
        </div>

        <div className="card card-wide">
          <h2>Active subscription</h2>
          {active_subscription ? (
            <>
              <dl className="summary-list">
                <dt>Plan</dt>
                <dd>{active_subscription.plan_name}</dd>
                <dt>Status</dt>
                <dd>
                  <StatusBadge value={active_subscription.status} />
                </dd>
                <dt>Price</dt>
                <dd>
                  {active_subscription.currency} {active_subscription.price.toFixed(2)} - {formatBillingCycle(active_subscription.billing_interval, active_subscription.billing_frequency)}
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

                <div className="portal-actions-cols">
                  <div className="portal-action-col">
                    <h3>Renew</h3>
                    {active_subscription.is_trial ? (
                      <p className="hint">
                        Free trials can't be renewed - subscribe to a paid plan before it ends to keep access without interruption.
                      </p>
                    ) : (
                      <button className="button button-secondary" disabled={busy} onClick={handleRenew}>
                        Renew now
                      </button>
                    )}
                  </div>
                  <div className="portal-action-col">
                    <h3>Cancel</h3>
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
                </div>
              </div>
            </>
          ) : (
            <p>No active subscription right now.</p>
          )}
        </div>
      </div>

      {pendingPayment && (
        <div className="card card-wide">
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
        <div className="card card-wide">
          <p>
            {lastCallback.subscription.status === "ACTIVE"
              ? "Payment succeeded and your subscription is up to date."
              : "That payment failed - your subscription is unchanged."}
          </p>
        </div>
      )}

      <div className="card card-wide">
        <h2>Subscriptions, payments &amp; invoices</h2>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Plan</th>
                <th>Billing cycle</th>
                <th className="numeric">Amount</th>
                <th>Last payment</th>
                <th>Invoice</th>
                <th>Next billing</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {subscriptions.map((s: PortalSubscriptionOut) => {
                const payment = latestPaymentFor(s.subscription_id, payments);
                const invoice = invoiceForPayment(payment, invoices);
                return (
                  <tr key={s.subscription_id}>
                    <td>{s.plan_name}</td>
                    <td>{formatBillingCycle(s.billing_interval, s.billing_frequency)}</td>
                    <td className="numeric">
                      {s.currency} {s.price.toFixed(2)}
                    </td>
                    <td>
                      {payment ? `${payment.status === "SUCCESS" ? "Paid" : payment.status.replace(/_/g, " ")} - ${formatDate(payment.created_at)}` : "-"}
                    </td>
                    <td>
                      {invoice ? (
                        <button
                          className="button button-secondary"
                          onClick={() => {
                            if (customerToken) void customerDownloadInvoicePdf(invoice.invoice_id, customerToken);
                          }}
                        >
                          {invoice.invoice_id}
                        </button>
                      ) : (
                        "-"
                      )}
                    </td>
                    <td>{formatDate(s.expires_at)}</td>
                    <td>
                      <StatusBadge value={s.status} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {subscriptions.length === 0 && <p className="hint">No subscriptions yet.</p>}
      </div>
    </section>
  );
}
