/**
 * Admin Customer detail (spec section 53): identity, registration data,
 * Everyticket mapping, subscriptions, payments, invoices - all read-only
 * except suspend/activate (financial history itself is never editable
 * here, per spec section 53).
 */
import { Fragment, useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  adminActivateCustomer,
  adminGenerateSsoLink,
  adminGetCustomer,
  adminSuspendCustomer,
} from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { StatusBadge } from "../../components/StatusBadge";
import { useAuth } from "../../context/AuthContext";
import { useToast } from "../../context/ToastContext";
import type { CustomerAdminDetailOut, SsoLinkOut } from "../../api/types";

export function AdminCustomerDetailPage() {
  const { customerId = "" } = useParams();
  const { adminToken } = useAuth();
  const toast = useToast();
  const [detail, setDetail] = useState<CustomerAdminDetailOut | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [ssoLink, setSsoLink] = useState<SsoLinkOut | null>(null);

  const reload = useCallback(() => {
    if (!adminToken) return;
    adminGetCustomer(customerId, adminToken).then(setDetail).catch(setError);
  }, [adminToken, customerId]);

  useEffect(reload, [reload]);

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

  return (
    <section>
      <p className="breadcrumb">
        <Link to="/admin/customers">&larr; Customers</Link>
      </p>
      <h1>{customerId}</h1>

      <ErrorBanner error={error} />

      {detail === null && !error && <p>Loading...</p>}

      {detail && (
        <>
          <div className="admin-panel">
            <div className="page-header-row" style={{ maxWidth: "none" }}>
              <dl className="summary-list">
                <dt>Email</dt>
                <dd>{detail.customer.email}</dd>
                <dt>Mobile</dt>
                <dd>{detail.customer.mobile}</dd>
                <dt>Status</dt>
                <dd>
                  <StatusBadge value={detail.customer.status} />
                </dd>
                {detail.application_mapping?.external_customer_id && (
                  <>
                    <dt>Everyticket ID</dt>
                    <dd>{detail.application_mapping.external_customer_id}</dd>
                  </>
                )}
              </dl>
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
              <h2>Registration data</h2>
              {detail.registration_data.map((r, i) => (
                <dl className="summary-list" key={i}>
                  {Object.entries(r.data).map(([k, v]) => (
                    <Fragment key={k}>
                      <dt>{k}</dt>
                      <dd>{String(v)}</dd>
                    </Fragment>
                  ))}
                </dl>
              ))}
            </div>
          )}

          <div className="detail-grid">
            <div className="admin-panel">
              <h2>Subscriptions</h2>
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
              </div>
              {detail.subscriptions.length === 0 && <p className="hint">None yet.</p>}
            </div>

            <div className="admin-panel">
              <h2>Payments</h2>
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Transaction</th>
                      <th className="numeric">Amount</th>
                      <th>Status</th>
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
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {detail.payments.length === 0 && <p className="hint">None yet.</p>}
            </div>

            <div className="admin-panel">
              <h2>Invoices</h2>
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Invoice</th>
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
                        <td>{inv.invoice_date}</td>
                        <td className="numeric">
                          {inv.currency} {inv.total_amount.toFixed(2)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {detail.invoices.length === 0 && <p className="hint">None yet.</p>}
            </div>
          </div>
        </>
      )}
    </section>
  );
}
