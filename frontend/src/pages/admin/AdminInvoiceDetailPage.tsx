/** Admin Invoice detail (spec section 45) - line items plus PDF download
 * and email resend actions. */
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { adminDownloadInvoicePdf, adminGetInvoice, adminSendInvoiceEmail } from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { useAuth } from "../../context/AuthContext";
import type { InvoiceAdminOut } from "../../api/types";

export function AdminInvoiceDetailPage() {
  const { invoiceId = "" } = useParams();
  const { adminToken } = useAuth();
  const [invoice, setInvoice] = useState<InvoiceAdminOut | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [downloading, setDownloading] = useState(false);
  const [sending, setSending] = useState(false);
  const [emailResult, setEmailResult] = useState<string | null>(null);

  useEffect(() => {
    if (!adminToken) return;
    adminGetInvoice(invoiceId, adminToken).then(setInvoice).catch(setError);
  }, [adminToken, invoiceId]);

  const downloadPdf = async () => {
    if (!adminToken) return;
    setDownloading(true);
    setError(null);
    try {
      await adminDownloadInvoicePdf(invoiceId, adminToken);
    } catch (err) {
      setError(err);
    } finally {
      setDownloading(false);
    }
  };

  const resendEmail = async () => {
    if (!adminToken) return;
    setSending(true);
    setError(null);
    setEmailResult(null);
    try {
      const result = await adminSendInvoiceEmail(invoiceId, adminToken);
      setEmailResult(result.sent ? `Sent to ${result.to}.` : "Could not send - check notification logs.");
    } catch (err) {
      setError(err);
    } finally {
      setSending(false);
    }
  };

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
            <div className="button-row">
              <button className="button button-primary" disabled={downloading} onClick={() => void downloadPdf()}>
                {downloading ? "Downloading..." : "Download PDF"}
              </button>
              <button className="button button-secondary" disabled={sending} onClick={() => void resendEmail()}>
                {sending ? "Sending..." : "Resend invoice email"}
              </button>
            </div>
            {emailResult && <p className="hint">{emailResult}</p>}
          </div>

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
