/** Admin Payments list (spec sections 23-28, 51, 53) - read-only. */
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { adminListPayments } from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Pagination } from "../../components/Pagination";
import { StatusBadge } from "../../components/StatusBadge";
import { useAuth } from "../../context/AuthContext";
import type { PageOut, PaymentAdminOut } from "../../api/types";

const LIMIT = 20;
const STATUSES = ["", "INITIATED", "PENDING", "SUCCESS", "FAILED", "CANCELLED"];

export function AdminPaymentsPage() {
  const { adminToken } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [page, setPage] = useState<PageOut<PaymentAdminOut> | null>(null);
  const [error, setError] = useState<unknown>(null);

  const status = searchParams.get("status") ?? "";
  const offset = Number(searchParams.get("offset") ?? "0");

  const reload = useCallback(() => {
    if (!adminToken) return;
    adminListPayments({ status: status || undefined, limit: LIMIT, offset }, adminToken).then(setPage).catch(setError);
  }, [adminToken, status, offset]);

  useEffect(reload, [reload]);

  return (
    <section>
      <h1>Payments</h1>

      <ErrorBanner error={error} />

      <div className="admin-panel">
        <div className="admin-toolbar">
          <label>
            Status
            <select value={status} onChange={(e) => setSearchParams({ status: e.target.value, offset: "0" })}>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s || "All"}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Transaction</th>
                <th>Customer</th>
                <th>Gateway</th>
                <th className="numeric">Amount</th>
                <th>Type</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {page?.items.map((p) => (
                <tr key={p.transaction_id} className="clickable" onClick={() => navigate(`/admin/payments/${p.transaction_id}`)}>
                  <td>{p.transaction_id}</td>
                  <td>{p.customer_id}</td>
                  <td>{p.gateway}</td>
                  <td className="numeric">
                    {p.currency} {p.amount.toFixed(2)}
                  </td>
                  <td>{p.payment_type}</td>
                  <td>
                    <StatusBadge value={p.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {page === null && !error && <p>Loading...</p>}
        {page && page.items.length === 0 && <p className="hint">No payments match.</p>}
        {page && (
          <Pagination
            total={page.total}
            limit={page.limit}
            offset={page.offset}
            onOffsetChange={(next) => setSearchParams({ status, offset: String(next) })}
          />
        )}
      </div>
    </section>
  );
}
