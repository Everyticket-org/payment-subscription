/** Admin Invoices list (spec sections 45, 51) - includes the GST/tax-rate
 * configuration used when new invoices are generated. Per-invoice PDF
 * download and email resend live on the detail page. */
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { adminGetInvoiceTaxConfig, adminListInvoices, adminUpdateInvoiceTaxConfig } from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Pagination } from "../../components/Pagination";
import { useAuth } from "../../context/AuthContext";
import { useToast } from "../../context/ToastContext";
import { parsePageLimit } from "../../utils/pagination";
import type { InvoiceAdminOut, PageOut, TaxConfigOut } from "../../api/types";

function TaxConfigPanel() {
  const { adminToken } = useAuth();
  const toast = useToast();
  const [config, setConfig] = useState<TaxConfigOut | null>(null);
  const [rate, setRate] = useState("0");
  const [gstin, setGstin] = useState("");
  const [label, setLabel] = useState("GST");
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!adminToken) return;
    adminGetInvoiceTaxConfig(adminToken)
      .then((cfg) => {
        setConfig(cfg);
        setRate(String(cfg.gst_rate_percent));
        setGstin(cfg.seller_gstin ?? "");
        setLabel(cfg.tax_label);
      })
      .catch(setError);
  }, [adminToken]);

  const save = async () => {
    if (!adminToken) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await adminUpdateInvoiceTaxConfig(
        { gst_rate_percent: Number(rate), seller_gstin: gstin || null, tax_label: label },
        adminToken,
      );
      setConfig(updated);
      setSavedAt(Date.now());
      toast.success("Tax configuration saved");
    } catch (err) {
      setError(err);
      toast.error(err);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="admin-panel">
      <h2>Tax / GST configuration</h2>
      <p className="hint">
        Applied to every invoice generated after saving - already-issued invoices keep the amounts they were
        generated with.
      </p>
      <ErrorBanner error={error} />
      {config === null && !error && <p>Loading...</p>}
      {config && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <div className="inline-form">
            <label>
              GST rate (%)
              <input type="number" min="0" max="100" step="0.01" value={rate} onChange={(e) => setRate(e.target.value)} />
            </label>
            <label>
              Seller GSTIN
              <input value={gstin} onChange={(e) => setGstin(e.target.value)} placeholder="e.g. 27AAAAA0000A1Z5" />
            </label>
            <label>
              Tax label
              <input value={label} onChange={(e) => setLabel(e.target.value)} />
            </label>
            <button className="button button-primary" type="submit" disabled={saving}>
              {saving ? "Saving..." : "Save"}
            </button>
          </div>
          {savedAt && <p className="hint">Saved.</p>}
        </form>
      )}
    </div>
  );
}

export function AdminInvoicesPage() {
  const { adminToken } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [page, setPage] = useState<PageOut<InvoiceAdminOut> | null>(null);
  const [error, setError] = useState<unknown>(null);

  const limit = parsePageLimit(searchParams.get("limit"));
  const offset = Number(searchParams.get("offset") ?? "0");

  const reload = useCallback(() => {
    if (!adminToken) return;
    adminListInvoices({ limit, offset }, adminToken).then(setPage).catch(setError);
  }, [adminToken, limit, offset]);

  useEffect(reload, [reload]);

  return (
    <section>
      <h1>Invoices</h1>

      <TaxConfigPanel />

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
            onOffsetChange={(next) => setSearchParams({ limit: String(limit), offset: String(next) })}
            onLimitChange={(next) => setSearchParams({ limit: String(next), offset: "0" })}
          />
        )}
      </div>
    </section>
  );
}
