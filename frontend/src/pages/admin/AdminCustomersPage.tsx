/**
 * Admin Customers list (spec sections 51, 53) - search + paginate, click
 * a row to drill into AdminCustomerDetailPage.
 */
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { adminListCustomers } from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Pagination } from "../../components/Pagination";
import { StatusBadge } from "../../components/StatusBadge";
import { useAuth } from "../../context/AuthContext";
import { parsePageLimit } from "../../utils/pagination";
import type { CustomerAdminListItem, PageOut } from "../../api/types";

export function AdminCustomersPage() {
  const { adminToken } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [page, setPage] = useState<PageOut<CustomerAdminListItem> | null>(null);
  const [error, setError] = useState<unknown>(null);

  const q = searchParams.get("q") ?? "";
  const limit = parsePageLimit(searchParams.get("limit"));
  const offset = Number(searchParams.get("offset") ?? "0");

  const reload = useCallback(() => {
    if (!adminToken) return;
    adminListCustomers({ q: q || undefined, limit, offset }, adminToken).then(setPage).catch(setError);
  }, [adminToken, q, limit, offset]);

  useEffect(reload, [reload]);

  return (
    <section>
      <h1>Customers</h1>

      <ErrorBanner error={error} />

      <div className="admin-panel">
        <form
          className="admin-toolbar"
          onSubmit={(e) => {
            e.preventDefault();
            const value = new FormData(e.currentTarget).get("q");
            setSearchParams({ q: String(value ?? ""), limit: String(limit), offset: "0" });
          }}
        >
          <label>
            Search
            <input name="q" defaultValue={q} placeholder="Email, mobile, or CUS-xxxx" />
          </label>
          <button className="button button-primary" type="submit">
            Search
          </button>
        </form>

        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Customer ID</th>
                <th>Email</th>
                <th>Mobile</th>
                <th>Status</th>
                <th>Joined</th>
              </tr>
            </thead>
            <tbody>
              {page?.items.map((c) => (
                <tr key={c.customer_id} className="clickable" onClick={() => navigate(`/admin/customers/${c.customer_id}`)}>
                  <td>{c.customer_id}</td>
                  <td>{c.email}</td>
                  <td>{c.mobile}</td>
                  <td>
                    <StatusBadge value={c.status} />
                  </td>
                  <td>{new Date(c.created_at).toLocaleDateString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {page === null && !error && <p>Loading...</p>}
        {page && page.items.length === 0 && <p className="hint">No customers match.</p>}
        {page && (
          <Pagination
            total={page.total}
            limit={page.limit}
            offset={page.offset}
            onOffsetChange={(next) => setSearchParams({ q, limit: String(limit), offset: String(next) })}
            onLimitChange={(next) => setSearchParams({ q, limit: String(next), offset: "0" })}
          />
        )}
      </div>
    </section>
  );
}
