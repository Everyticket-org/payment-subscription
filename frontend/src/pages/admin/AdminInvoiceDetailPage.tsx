/** Admin Invoice detail (spec section 45) - read-only, with line items. */
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { adminGetInvoice } from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { useAuth } from "../../context/AuthContext";
import type { InvoiceAdminOut } from "../../api/types";

export function AdminInvoiceDetailPage() {
  const { invoiceId = "" } = useParams();
  const { adminToken } = useAuth();
  const [invoice, setInvoice] = useState<InvoiceAdminOut | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!adminToken) return;
    adminGetInvoice(invoiceId, adminToken).then(setInvoice).catch(setError);
  }, [adminToken, invoiceId]);

  return (
    <section>
      <p className="breadcrumb">
        <Link to="/admin/invoices">&larr; Invoices</Link>
      </p>
      <h1>{invoiceId}</h1>

      <ErrorBanner error={error} />

      {invoice === null && !error && <p>Loading...</p>}

      {invoice && (
        <>
          <div className="admin-panel">
            <dl className="summary-list">
              <dt>Customer</dt>
              <dd>
                <Link to={`/admin/customers/${invoice.customer_id}`}>{invoice.customer_id}</Link>
              </dd>
              <dt>Subscription</dt>
              <dd>
                <Link to={`/admin/subscriptions/${invoice.subscription_id}`}>{invoice.subscription_id}</Link>
              </dd>
              <dt>Transaction</dt>
              <dd>
                <Link to={`/admin/payments/${invoice.transaction_id}`}>{invoice.transaction_id}</Link>
              </dd>
              <dt>Invoice date</dt>
              <dd>{invoice.invoice_date}</dd>
              <dt>Billing period</dt>
              <dd>
                {invoice.billing_period_start} to {invoice.billing_period_end}
              </dd>
              {invoice.gst_number && (
                <>
                  <dt>GSTIN</dt>
                  <dd>{invoice.gst_number}</dd>
                </>
              )}
            </dl>
          </div>

          <div className="admin-panel">
            <h2>Line items</h2>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Description</th>
                    <th className="numeric">Qty</th>
                    <th className="numeric">Unit price</th>
                    <th className="numeric">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {invoice.items.map((item, i) => (
                    <tr key={i}>
                      <td>{item.description}</td>
                      <td className="numeric">{item.quantity}</td>
                      <td className="numeric">{item.unit_price.toFixed(2)}</td>
                      <td className="numeric">{item.amount.toFixed(2)}</td>
                    </tr>
                  ))}
                  <tr>
                    <td colSpan={3} style={{ textAlign: "right", fontWeight: 700 }}>
                      Tax
                    </td>
                    <td className="numeric">{invoice.tax_amount.toFixed(2)}</td>
                  </tr>
                  <tr>
                    <td colSpan={3} style={{ textAlign: "right", fontWeight: 700 }}>
                      Total
                    </td>
                    <td className="numeric">
                      {invoice.currency} {invoice.total_amount.toFixed(2)}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </section>
  );
}
