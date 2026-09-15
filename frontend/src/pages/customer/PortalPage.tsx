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
 *
 * Visual redesign (2026-09-15 follow-up, Vishal's own words: "Current
 * Front end design is very simple and ordinary... suggest one page
 * redesign very elegant, proper spacing, responsive, customer experience
 * centric... now change all customer portal pages with such good
 * design" - approved from an image mockup of this exact page first).
 * Every piece of data, every handler and every conditional branch below
 * is unchanged from the previous version - only the markup/classNames
 * changed, all scoped under the new portal-* classes in index.css so
 * the public marketing pages and the admin console (which still use the
 * plain .card/.data-table/.detail-grid primitives) are untouched.
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  customerDownloadInvoicePdf,
  getRegistrationForm,
  cancelSubscription,
  getCustomerPortal,
  renewSubscription,
  simulateMockCallback,
} from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { isSessionExpired } from "../../utils/authError";
import { PaymentCheckout } from "../../components/PaymentCheckout";
import { StatusBadge } from "../../components/StatusBadge";
import { useAuth } from "../../context/AuthContext";
import { useToast } from "../../context/ToastContext";
import type {
  CustomerPortalOut,
  InvoiceOut,
  MockCallbackResult,
  PaymentTransactionOut,
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

// Purely presentational - how far through the current billing period this
// subscription is, for the hero card's progress bar. Clamped to 0-100 so a
// clock-skewed or already-lapsed date never draws a bar past either end.
function renewalProgress(startsAt: string | null, expiresAt: string | null): number {
  if (!startsAt || !expiresAt) return 0;
  const start = new Date(startsAt).getTime();
  const end = new Date(expiresAt).getTime();
  const now = Date.now();
  if (!(end > start)) return 0;
  return Math.max(0, Math.min(100, ((now - start) / (end - start)) * 100));
}

// Also purely presentational - cycles a plan through a small set of badge
// colors so the history list reads as distinct plans at a glance, rather
// than every row wearing the same accent. Not tied to plan tier/price.
function planBadgeTone(planCode: string): string {
  let hash = 0;
  for (const ch of planCode) hash = (hash * 31 + ch.charCodeAt(0)) % 3;
  return hash === 1 ? "tone-2" : hash === 2 ? "tone-3" : "";
}

function DownloadIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 3v12m0 0-4-4m4 4 4-4M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function AccountIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="8" r="4" />
      <path d="M4 20c0-4 4-6 8-6s8 2 8 6" strokeLinecap="round" />
    </svg>
  );
}

function DocumentIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M4 21V7a2 2 0 0 1 2-2h6l6 6v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2Z" />
      <path d="M12 5v6h6" />
    </svg>
  );
}

export function PortalPage() {
  const { customerToken, setCustomerToken } = useAuth();
  const toast = useToast();
  const [portal, setPortal] = useState<CustomerPortalOut | null>(null);
  const [formFields, setFormFields] = useState<RegistrationFormFieldOut[]>([]);
  const [cancelReason, setCancelReason] = useState("");
  const [confirmingCancel, setConfirmingCancel] = useState(false);
  const [pendingPayment, setPendingPayment] = useState<SubscribeResponse | null>(null);
  const [lastCallback, setLastCallback] = useState<MockCallbackResult | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    if (!customerToken) return;
    try {
      const [portalData, fields] = await Promise.all([
        getCustomerPortal(customerToken),
        getRegistrationForm().catch(() => []),
      ]);
      setPortal(portalData);
      setFormFields(fields);
    } catch (err) {
      // An expired/invalid token would otherwise strand the user on this
      // page's "loading" branch forever (no portal data ever arrives, so
      // the page never reaches the view that has its own Sign out button) -
      // clear it instead so RequireCustomer sends them to /login right
      // away. Layout's header also has a Sign out control now as a
      // manual fallback for any other case.
      if (isSessionExpired(err)) {
        setCustomerToken(null);
        return;
      }
      setError(err);
    }
  }, [customerToken, setCustomerToken]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Shared by every mutation below: an expired/invalid token surfacing
  // mid-session (user already has the portal loaded, then a later action
  // 401s) gets the same "clear the token and let RequireCustomer redirect
  // to /login" treatment as the initial load in refresh() above, instead
  // of just toasting "Invalid or expired token" and leaving them stuck on
  // a now-broken portal.
  function reportError(err: unknown) {
    if (isSessionExpired(err)) {
      setCustomerToken(null);
      return;
    }
    setError(err);
    toast.error(err);
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
      reportError(err);
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
      setLastCallback(result);
      setPendingPayment(null);
      if (result.subscription.status === "ACTIVE") {
        toast.success("Payment succeeded - subscription updated");
      } else {
        toast.error("Payment failed - subscription unchanged");
      }
      await refresh();
    } catch (err) {
      reportError(err);
    } finally {
      setBusy(false);
    }
  }

  if (!portal) {
    return (
      <section className="portal-page">
        <h1>My Subscription</h1>
        <ErrorBanner error={error} />
        {!error && <p>Loading...</p>}
      </section>
    );
  }

  const { customer, registration_data, active_subscription, subscriptions, payments, invoices } = portal;
  const fieldLabels = new Map(formFields.map((f) => [f.field_key, f.label]));

  return (
    <section className="portal-page">
      {/* Sign out lives in the public-site header now (components/Layout.tsx)
          - having a second one here too was redundant (frontend request,
          2026-09: "Remove Signout nearby my account title as already you
          have added in header now"). */}
      <div className="portal-page-head">
        <div>
          <div className="portal-eyebrow">
            Account <span className="sep">/</span> My Subscription
          </div>
          <h1>My Subscription</h1>
          <p>Manage your plan, payments and account details in one place.</p>
        </div>
      </div>

      <ErrorBanner error={error} />

      <div className="portal-layout">
        <div className="portal-stack">
          {/* ---- Hero: active subscription ---- */}
          <div className="portal-hero">
            {active_subscription ? (
              <>
                <div className="portal-hero-top">
                  <div>
                    <p className="portal-plan-kicker">Current plan</p>
                    <h2 className="portal-plan-name">{active_subscription.plan_name}</h2>
                    <p className="portal-plan-price">
                      {active_subscription.currency} {active_subscription.price.toFixed(2)}{" "}
                      <b>/ {active_subscription.billing_interval}</b>
                      {" "}&middot;{" "}
                      {formatBillingCycle(active_subscription.billing_interval, active_subscription.billing_frequency)}
                    </p>
                  </div>
                  <StatusBadge value={active_subscription.status} />
                </div>

                <div className="portal-meter">
                  <div className="portal-meter-row">
                    <span>Started {formatDate(active_subscription.starts_at)}</span>
                    <span>Renews {formatDate(active_subscription.expires_at)}</span>
                  </div>
                  <div className="portal-meter-track">
                    <div
                      className="portal-meter-fill"
                      style={{
                        width: `${renewalProgress(active_subscription.starts_at, active_subscription.expires_at)}%`,
                      }}
                    />
                  </div>
                </div>

                <div className="portal-hero-actions">
                  {active_subscription.is_trial ? (
                    <p className="hint" style={{ margin: 0 }}>
                      Free trials can't be switched to another plan - subscribe to a paid plan instead.
                    </p>
                  ) : (
                    <>
                      <Link className="button button-primary" to="/portal/change-plan">
                        Change plan
                      </Link>
                      <button className="button button-secondary" disabled={busy} onClick={handleRenew}>
                        Renew now
                      </button>
                      {!confirmingCancel && (
                        <button
                          type="button"
                          className="portal-link-danger"
                          disabled={busy}
                          onClick={() => setConfirmingCancel(true)}
                        >
                          Cancel subscription
                        </button>
                      )}
                    </>
                  )}
                </div>

                {active_subscription.is_trial && (
                  <p className="hint" style={{ marginTop: 12 }}>
                    Free trials can't be renewed - subscribe to a paid plan before it ends to keep access without
                    interruption.
                  </p>
                )}

                {confirmingCancel && (
                  <div className="portal-cancel-panel">
                    <label>
                      Reason (optional)
                      <input type="text" value={cancelReason} onChange={(e) => setCancelReason(e.target.value)} />
                    </label>
                    <p className="hint">Cancellation is immediate - no refund, no future renewal.</p>
                    <div className="button-row">
                      <button className="button button-danger" disabled={busy} onClick={handleCancel}>
                        Confirm cancellation
                      </button>
                      <button
                        className="button button-secondary"
                        disabled={busy}
                        onClick={() => setConfirmingCancel(false)}
                      >
                        Never mind
                      </button>
                    </div>
                  </div>
                )}
              </>
            ) : (
              <div>
                <p className="portal-plan-kicker">Subscription</p>
                <h2 className="portal-plan-name" style={{ fontSize: 22 }}>
                  No active subscription right now
                </h2>
                <p className="hint" style={{ marginBottom: 20 }}>
                  Choose a plan to get started - your account and registration details are already on file below.
                </p>
                <Link className="button button-primary" to="/">
                  Browse plans
                </Link>
              </div>
            )}
          </div>

          {pendingPayment && (
            <div className="portal-card">
              <div className="portal-section-head">
                <h2>Complete payment to apply this change</h2>
              </div>
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
            <div className="portal-card">
              <p style={{ margin: 0 }}>
                {lastCallback.subscription.status === "ACTIVE"
                  ? "Payment succeeded and your subscription is up to date."
                  : "That payment failed - your subscription is unchanged."}
              </p>
            </div>
          )}

          {/* ---- History: subscriptions, payments & invoices ---- */}
          <div className="portal-card">
            <div className="portal-section-head">
              <h2>Subscriptions, payments &amp; invoices</h2>
              <span className="portal-count">
                {subscriptions.length} record{subscriptions.length === 1 ? "" : "s"}
              </span>
            </div>
            <div className="portal-history-list">
              <div className="portal-history-head">
                <span>Plan</span>
                <span>Last payment</span>
                <span>Next billing</span>
                <span>Invoice</span>
                <span>Status</span>
              </div>
              {subscriptions.map((s: PortalSubscriptionOut) => {
                const payment = latestPaymentFor(s.subscription_id, payments);
                const invoice = invoiceForPayment(payment, invoices);
                return (
                  <div className="portal-history-row" key={s.subscription_id}>
                    <div className="portal-history-row-line">
                      <span className="portal-cell-label">Plan</span>
                      <div className="portal-plan-cell">
                        <div className={`portal-plan-badge ${planBadgeTone(s.plan_code)}`}>
                          {s.plan_code.slice(0, 2).toUpperCase()}
                        </div>
                        <div className="txt">
                          <b>{s.plan_name}</b>
                          <span>
                            {formatBillingCycle(s.billing_interval, s.billing_frequency)} &middot; {s.currency}{" "}
                            {s.price.toFixed(2)}
                          </span>
                        </div>
                      </div>
                    </div>

                    <div className="portal-history-row-line">
                      <span className="portal-cell-label">Last payment</span>
                      {payment ? (
                        <div>
                          <div className="portal-cell-main">
                            {payment.status === "SUCCESS" ? "Paid" : payment.status.replace(/_/g, " ")}
                          </div>
                          <div className="portal-cell-sub">{formatDate(payment.created_at)}</div>
                        </div>
                      ) : (
                        <span className="portal-cell-dim">-</span>
                      )}
                    </div>

                    <div className="portal-history-row-line">
                      <span className="portal-cell-label">Next billing</span>
                      <span className="portal-cell-main">{formatDate(s.expires_at)}</span>
                    </div>

                    <div className="portal-history-row-line">
                      <span className="portal-cell-label">Invoice</span>
                      {invoice ? (
                        <button
                          type="button"
                          className="portal-inv-link"
                          onClick={() => {
                            if (customerToken) void customerDownloadInvoicePdf(invoice.invoice_id, customerToken);
                          }}
                        >
                          <DownloadIcon />
                          {invoice.invoice_id}
                        </button>
                      ) : (
                        <span className="portal-cell-dim">No invoice</span>
                      )}
                    </div>

                    <div className="portal-history-row-line">
                      <span className="portal-cell-label">Status</span>
                      <StatusBadge value={s.status} />
                    </div>
                  </div>
                );
              })}
            </div>
            {subscriptions.length === 0 && <p className="hint">No subscriptions yet.</p>}
          </div>
        </div>

        {/* ---- Sidebar: account + registration details ---- */}
        <div className="portal-stack">
          <div className="portal-card">
            <div className="portal-card-title-row">
              <div className="portal-icon-tag">
                <AccountIcon />
              </div>
              <div>
                <h3>Account</h3>
                <div className="portal-card-sub">Your identity on Everyticket</div>
              </div>
            </div>
            <div className="portal-info-row">
              <span className="k">Customer ID</span>
              <span className="v">{customer.customer_id}</span>
            </div>
            <div className="portal-info-row">
              <span className="k">Email</span>
              <span className="v">{customer.email ?? "-"}</span>
            </div>
            <div className="portal-info-row">
              <span className="k">Mobile</span>
              <span className="v">{customer.mobile ?? "-"}</span>
            </div>
          </div>

          {registration_data.length > 0 && (
            <div className="portal-card">
              <div className="portal-card-title-row">
                <div className="portal-icon-tag">
                  <DocumentIcon />
                </div>
                <div>
                  <h3>Registration details</h3>
                  <div className="portal-card-sub">Submitted at signup</div>
                </div>
              </div>
              {/* Only the most recent submission is shown - multiple
                  historical rows can exist across separate subscribe
                  attempts (each preserved for history), and the backend
                  already orders these newest-first, so showing every row
                  here would display old fields as if duplicated/current. */}
              {Object.entries(registration_data[0].data).map(([key, value]) => (
                <div className="portal-info-row" key={key}>
                  <span className="k">{fieldLabels.get(key) ?? key}</span>
                  <span className="v">{String(value ?? "-")}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
