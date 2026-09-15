/**
 * Admin Customer detail (spec section 53): identity, registration data,
 * Everyticket mapping, subscriptions, payments, invoices - all read-only
 * except suspend/activate (financial history itself is never editable
 * here, per spec section 53).
 *
 * 2026-09-15 follow-up ("give suggestion for customer detail page", then
 * "yes its better, please implement" on the reviewed mockup image):
 * restyled to match the same admin-panel visual language as the
 * Dashboard/sidebar/Customers-list passes - avatar-led identity header
 * (reusing the Customers list's avatar/initials/plan-pill helpers, moved
 * to utils/customerDisplay.ts so both pages stay visually identical),
 * a collapsible Registration data panel (open by default - collapsible
 * because a long registration form would otherwise force a wall of
 * key/value pairs on every visit), and Subscriptions/Payments/Invoices as
 * tabs instead of a fixed 3-column grid (the grid squeezed all three
 * tables into a third of the page width each). Every value shown is real:
 * the header's "current plan" pill is picked from `subscriptions` with
 * the exact same "ACTIVE one if there is one, else most recent" rule the
 * Customers list's backend already uses for the same purpose (the
 * backend already returns `subscriptions` newest-first, so this needs no
 * new API call). "Customer since" uses the customer record's own
 * `created_at`, newly surfaced on CustomerOut for this - previously the
 * backend just never returned it since nothing displayed it.
 */
import { Fragment, useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  adminActivateCustomer,
  adminGenerateSsoLink,
  adminGetCustomer,
  adminListPlans,
  adminListRegistrationFormFields,
  adminSuspendCustomer,
} from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { StatusBadge } from "../../components/StatusBadge";
import { useAuth } from "../../context/AuthContext";
import { useToast } from "../../context/ToastContext";
import { PLAN_COLORS, avatarColorFor, initialsFor } from "../../utils/customerDisplay";
import type {
  CustomerAdminDetailOut,
  PlanAdminOut,
  RegistrationFormFieldAdminOut,
  SsoLinkOut,
} from "../../api/types";

type DetailTab = "subscriptions" | "payments" | "invoices";

export function AdminCustomerDetailPage() {
  const { customerId = "" } = useParams();
  const { adminToken } = useAuth();
  const toast = useToast();
  const [detail, setDetail] = useState<CustomerAdminDetailOut | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [ssoLink, setSsoLink] = useState<SsoLinkOut | null>(null);
  const [plans, setPlans] = useState<PlanAdminOut[]>([]);
  const [regOpen, setRegOpen] = useState(true);
  const [activeTab, setActiveTab] = useState<DetailTab>("subscriptions");
  // Registration data below is keyed by field_key (e.g. "museum_name"),
  // not fit for display - fetch the admin-configured fields once (same
  // list the Registration form admin page manages) so each key can be
  // shown as its human-readable Label ("Museum Name") instead. Fetched
  // independently of `reload` since it doesn't depend on customerId and
  // a customer's data is never re-labeled just because it was reloaded.
  const [formFields, setFormFields] = useState<RegistrationFormFieldAdminOut[]>([]);

  const reload = useCallback(() => {
    if (!adminToken) return;
    adminGetCustomer(customerId, adminToken).then(setDetail).catch(setError);
  }, [adminToken, customerId]);

  useEffect(reload, [reload]);

  useEffect(() => {
    if (!adminToken) return;
    adminListRegistrationFormFields(adminToken).then(setFormFields).catch(() => {});
  }, [adminToken]);

  // Same plan-color palette as the Customers list, keyed the same way
  // (by position in the real plan list) - so a plan's pill is the same
  // color whether seen from the list or from this detail page.
  useEffect(() => {
    if (!adminToken) return;
    adminListPlans(adminToken)
      .then(setPlans)
      .catch(() => setPlans([]));
  }, [adminToken]);

  // Falls back to the raw key for any value collected under a field that
  // has since been renamed or removed from the registration form - real
  // historical data that was actually submitted should never disappear
  // from a customer's record just because the field config changed.
  function fieldLabel(key: string): string {
    return formFields.find((f) => f.field_key === key)?.label ?? key;
  }

  async function handleSuspend() {
    if (!adminToken) return;
    setBusy(true);
    try {
      await adminSuspendCustomer(customerId, undefined, adminToken);
      toast.success("Customer suspended");
      reload();
    } catch (err) {
      setError(err);
      toast.error(err);
    } finally {
      setBusy(false);
    }
  }

  async function handleActivate() {
    if (!adminToken) return;
    setBusy(true);
    try {
      await adminActivateCustomer(customerId, adminToken);
      toast.success("Customer activated");
      reload();
    } catch (err) {
      setError(err);
      toast.error(err);
    } finally {
      setBusy(false);
    }
  }

  async function handleGenerateSsoLink() {
    if (!adminToken) return;
    setBusy(true);
    setError(null);
    setSsoLink(null);
    try {
      const result = await adminGenerateSsoLink(customerId, adminToken);
      setSsoLink(result);
      toast.success("SSO test link generated");
    } catch (err) {
      setError(err);
      toast.error(err);
    } finally {
      setBusy(false);
    }
  }

  const planColorByCode = Object.fromEntries(plans.map((p, i) => [p.plan_code, PLAN_COLORS[i % PLAN_COLORS.length]]));
  // Same "ACTIVE one if there is one, else most recent" rule the
  // Customers list's backend uses (_pick_current_subscription in
  // admin_customers.py) - done here in the already-fetched list instead
  // of a new API call, since the backend already returns `subscriptions`
  // ordered newest-first (so [0], absent an ACTIVE one, is "most recent").
  const currentSubscription = detail
    ? (detail.subscriptions.find((s) => s.status === "ACTIVE") ?? detail.subscriptions[0] ?? null)
    : null;

  return (
    <section className="admin-customer-detail-page">
      <p className="breadcrumb">
        <Link to="/admin/customers">&larr; Customers</Link>
      </p>

      <ErrorBanner error={error} />

      {detail === null && !error && <p>Loading...</p>}

      {detail && (
        <>
          <div className="admin-panel">
            {/* Same maxWidth/flexWrap/gap override as before this pass -
                without it the identity block and Suspend/Generate SSO
                link buttons never drop to their own line at narrow
                (~480px) widths, unlike every other admin page. */}
            <div className="page-header-row" style={{ maxWidth: "none", flexWrap: "wrap", gap: 12 }}>
              <div className="customer-detail-id">
                <span className="cust-avatar customer-detail-avatar" style={{ background: avatarColorFor(customerId) }}>
                  {initialsFor(detail.customer.email ?? customerId)}
                </span>
                <div>
                  <h1>{detail.customer.email}</h1>
                  <p className="customer-detail-cid">{customerId}</p>
                  <div className="customer-detail-tags">
                    <StatusBadge value={detail.customer.status} />
                    {currentSubscription && (
                      <span className="plan-pill">
                        <span
                          className="plan-pill-dot"
                          style={{ background: planColorByCode[currentSubscription.plan_code] || "#9ca3af" }}
                        />
                        {currentSubscription.plan_name}
                      </span>
                    )}
                  </div>
                </div>
              </div>
              <div className="button-row">
                {detail.customer.status === "ACTIVE" ? (
                  <button className="button button-danger" disabled={busy} onClick={handleSuspend}>
                    Suspend
                  </button>
                ) : (
                  <button className="button button-primary" disabled={busy} onClick={handleActivate}>
                    Activate
                  </button>
                )}
                <button className="button button-secondary" disabled={busy} onClick={handleGenerateSsoLink}>
                  Generate test SSO link
                </button>
              </div>
            </div>

            <dl className="summary-list" style={{ marginTop: 20, paddingTop: 18, borderTop: "1px solid var(--border)" }}>
              <dt>Mobile</dt>
              <dd>{detail.customer.mobile}</dd>
              {detail.application_mapping?.external_customer_id && (
                <>
                  <dt>Everyticket ID</dt>
                  <dd>{detail.application_mapping.external_customer_id}</dd>
                </>
              )}
              <dt>Customer since</dt>
              <dd>{new Date(detail.customer.created_at).toLocaleDateString()}</dd>
            </dl>

            {ssoLink && (
              <div className="inline-form">
                <p className="hint">
                  Everyticket SSO test link (TEST_MODE only - expires {new Date(ssoLink.expires_at).toLocaleTimeString()}
                  ):
                </p>
                <p style={{ wordBreak: "break-all" }}>
                  <a href={ssoLink.consume_url} target="_blank" rel="noreferrer">
                    {ssoLink.consume_url}
                  </a>
                </p>
              </div>
            )}
          </div>

          {detail.registration_data.length > 0 && (
            <div className="admin-panel">
              <button
                type="button"
                className="collapsible-head"
                onClick={() => setRegOpen((v) => !v)}
                aria-expanded={regOpen}
              >
                <h2>Registration data</h2>
                <svg
                  className={`collapsible-chevron${regOpen ? " open" : ""}`}
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <path d="M6 9l6 6 6-6" />
                </svg>
              </button>
              {regOpen && (
                /* Only the most recent submission is shown - a customer
                   can accumulate multiple historical rows over separate
                   subscribe attempts (each preserved for history, see
                   CustomerRegistrationData model), but the backend
                   already orders these newest-first, so rendering every
                   row here would show old fields as if they were all
                   current/duplicated. */
                <dl className="summary-list" style={{ marginTop: 16 }}>
                  {Object.entries(detail.registration_data[0].data).map(([k, v]) => (
                    <Fragment key={k}>
                      <dt>{fieldLabel(k)}</dt>
                      <dd>{String(v)}</dd>
                    </Fragment>
                  ))}
                </dl>
              )}
            </div>
          )}

          <div className="admin-panel">
            <div className="detail-tabs">
              <button
                type="button"
                className={`detail-tab${activeTab === "subscriptions" ? " active" : ""}`}
                onClick={() => setActiveTab("subscriptions")}
              >
                Subscriptions <span className="detail-tab-count">{detail.subscriptions.length}</span>
              </button>
              <button
                type="button"
                className={`detail-tab${activeTab === "payments" ? " active" : ""}`}
                onClick={() => setActiveTab("payments")}
              >
                Payments <span className="detail-tab-count">{detail.payments.length}</span>
              </button>
              <button
                type="button"
                className={`detail-tab${activeTab === "invoices" ? " active" : ""}`}
                onClick={() => setActiveTab("invoices")}
              >
                Invoices <span className="detail-tab-count">{detail.invoices.length}</span>
              </button>
            </div>

            {activeTab === "subscriptions" && (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Plan</th>
                      <th>Status</th>
                      <th>Expires</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.subscriptions.map((s) => (
                      <tr key={s.subscription_id}>
                        <td>
                          <Link to={`/admin/subscriptions/${s.subscription_id}`}>{s.subscription_id}</Link>
                        </td>
                        <td>{s.plan_name}</td>
                        <td>
                          <StatusBadge value={s.status} />
                        </td>
                        <td>{s.expires_at ? new Date(s.expires_at).toLocaleDateString() : "-"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {detail.subscriptions.length === 0 && <p className="hint">None yet.</p>}
              </div>
            )}

            {activeTab === "payments" && (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Transaction</th>
                      <th className="numeric">Amount</th>
                      <th>Status</th>
                      <th>Created</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.payments.map((p) => (
                      <tr key={p.transaction_id}>
                        <td>
                          <Link to={`/admin/payments/${p.transaction_id}`}>{p.transaction_id}</Link>
                        </td>
                        <td className="numeric">
                          {p.currency} {p.amount.toFixed(2)}
                        </td>
                        <td>
                          <StatusBadge value={p.status} />
                        </td>
                        <td>{new Date(p.created_at).toLocaleDateString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {detail.payments.length === 0 && <p className="hint">None yet.</p>}
              </div>
            )}

            {activeTab === "invoices" && (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Invoice</th>
                      <th>Billing period</th>
                      <th>Date</th>
                      <th className="numeric">Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.invoices.map((inv) => (
                      <tr key={inv.invoice_id}>
                        <td>
                          <Link to={`/admin/invoices/${inv.invoice_id}`}>{inv.invoice_id}</Link>
                        </td>
                        <td>
                          {inv.billing_period_start} &ndash; {inv.billing_period_end}
                        </td>
                        <td>{inv.invoice_date}</td>
                        <td className="numeric">
                          {inv.currency} {inv.total_amount.toFixed(2)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {detail.invoices.length === 0 && <p className="hint">None yet.</p>}
              </div>
            )}
          </div>
        </>
      )}
    </section>
  );
}
