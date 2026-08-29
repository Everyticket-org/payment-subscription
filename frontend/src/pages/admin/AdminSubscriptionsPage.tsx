/** Admin Subscriptions list (spec sections 51, 53) - read-only, filter
 * by status/plan/customer, click through to the detail + history view. */
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { adminListSubscriptions } from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Pagination } from "../../components/Pagination";
import { StatusBadge } from "../../components/StatusBadge";
import { useAuth } from "../../context/AuthContext";
import type { PageOut, SubscriptionAdminOut } from "../../api/types";

const LIMIT = 20;
const STATUSES = ["", "PENDING_PAYMENT", "ACTIVE", "PAYMENT_FAILED", "CANCELLED", "EXPIRED"];

export function AdminSubscriptionsPage() {
  const { adminToken } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [page, setPage] = useState<PageOut<SubscriptionAdminOut> | null>(null);
  const [error, setError] = useState<unknown>(null);

  const status = searchParams.get("status") ?? "";
  const customerId = searchParams.get("customer_id") ?? "";
  const offset = Number(searchParams.get("offset") ?? "0");

  const reload = useCallback(() => {
    if (!adminToken) return;
    adminListSubscriptions(
      { status: status || undefined, customer_id: customerId || undefined, limit: LIMIT, offset },
      adminToken,
    )
      .then(setPage)
      .catch(setError);
  }, [adminToken, status, customerId, offset]);

  useEffect(reload, [reload]);

  return (
    <section>
      <h1>Subscriptions</h1>

      <ErrorBanner error={error} />

      <div className="admin-panel">
        <div className="admin-toolbar">
          <label>
            Status
            <select
              value={status}
              onChange={(e) => setSearchParams({ status: e.target.value, customer_id: customerId, offset: "0" })}
            >
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s || "All"}
                </option>
              ))}
            </select>
          </label>
          <label>
            Customer ID
            <input
              defaultValue={customerId}
              placeholder="CUS-xxxx"
              onBlur={(e) => setSearchParams({ status, customer_id: e.target.value, offset: "0" })}
            />
          </label>
        </div>

        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Customer</th>
                <th>Plan</th>
                <th>Status</th>
                <th>Expires</th>
              </tr>
            </thead>
            <tbody>
              {page?.items.map((s) => (
                <tr key={s.subscription_id} className="clickable" onClick={() => navigate(`/admin/subscriptions/${s.subscription_id}`)}>
                  <td>{s.subscription_id}</td>
                  <td>{s.customer_id}</td>
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
        {page === null && !error && <p>Loading...</p>}
        {page && page.items.length === 0 && <p className="hint">No subscriptions match.</p>}
        {page && (
          <Pagination
            total={page.total}
            limit={page.limit}
            offset={page.offset}
            onOffsetChange={(next) => setSearchParams({ status, customer_id: customerId, offset: String(next) })}
          />
        )}
      </div>
    </section>
  );
}
