/** Admin Invoices list (spec sections 45, 51) - read-only; PDF generation/
 * email delivery are a separate not-yet-built increment. */
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { adminListInvoices } from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Pagination } from "../../components/Pagination";
import { useAuth } from "../../context/AuthContext";
import type { InvoiceAdminOut, PageOut } from "../../api/types";

const LIMIT = 20;

export function AdminInvoicesPage() {
  const { adminToken } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [page, setPage] = useState<PageOut<InvoiceAdminOut> | null>(null);
  const [error, setError] = useState<unknown>(null);

  const offset = Number(searchParams.get("offset") ?? "0");

  const reload = useCallback(() => {
    if (!adminToken) return;
    adminListInvoices({ limit: LIMIT, offset }, adminToken).then(setPage).catch(setError);
  }, [adminToken, offset]);

  useEffect(reload, [reload]);

  return (
    <section>
      <h1>Invoices</h1>

      <ErrorBanner error={error} />

      <div className="admin-panel">
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Invoice</th>
                <th>Customer</th>
                <th>Date</th>
                <th className="numeric">Total</th>
              </tr>
            </thead>
            <tbody>
              {page?.items.map((inv) => (
                <tr key={inv.invoice_id} className="clickable" onClick={() => navigate(`/admin/invoices/${inv.invoice_id}`)}>
                  <td>{inv.invoice_id}</td>
                  <td>{inv.customer_id}</td>
                  <td>{inv.invoice_date}</td>
                  <td className="numeric">
                    {inv.currency} {inv.total_amount.toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {page === null && !error && <p>Loading...</p>}
        {page && page.items.length === 0 && <p className="hint">No invoices yet.</p>}
        {page && (
          <Pagination
            total={page.total}
            limit={page.limit}
            offset={page.offset}
            onOffsetChange={(next) => setSearchParams({ offset: String(next) })}
          />
        )}
      </div>
    </section>
  );
}
