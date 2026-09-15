/**
 * Admin Customers list (spec sections 51, 53) - search + paginate, click
 * a row to drill into AdminCustomerDetailPage.
 *
 * 2026-09-15 follow-up ("Change Customer Page now" - implementing the
 * third and final piece of the approved admin-panel mockup, after the
 * Dashboard and sidebar menu): restyled per the mockup's visual language
 * (avatar-led customer cell, plan pill, trailing chevron), but every
 * number/label is real. Two things the mockup conflated into one
 * "Status" column are kept separate here since they're genuinely
 * different concepts: `current_subscription_status` (ACTIVE/
 * PENDING_PAYMENT/PAYMENT_FAILED/CANCELLED/EXPIRED/ARCHIVED - the
 * customer's current subscription, new field from the backend) and
 * `status` (the existing account-level ACTIVE/SUSPENDED flag the
 * suspend/activate action on the detail page already uses - unchanged).
 * The mockup's "Export CSV" button was dropped - no real export feature
 * exists yet.
 */
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { adminListCustomers, adminListPlans } from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { Pagination } from "../../components/Pagination";
import { StatusBadge } from "../../components/StatusBadge";
import { useAuth } from "../../context/AuthContext";
import { parsePageLimit } from "../../utils/pagination";
// 2026-09-15 follow-up (Customer detail page redesign): moved to a shared
// util so the Customer detail page's avatar/plan-pill colors stay
// identical to this list's, instead of each page growing its own copy.
import { PLAN_COLORS, avatarColorFor, initialsFor } from "../../utils/customerDisplay";
import type { CustomerAdminListItem, PageOut, PlanAdminOut } from "../../api/types";

const ACCOUNT_STATUSES = ["", "ACTIVE", "SUSPENDED"];

export function AdminCustomersPage() {
  const { adminToken } = useAuth();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [page, setPage] = useState<PageOut<CustomerAdminListItem> | null>(null);
  const [plans, setPlans] = useState<PlanAdminOut[]>([]);
  const [error, setError] = useState<unknown>(null);

  const q = searchParams.get("q") ?? "";
  const status = searchParams.get("status") ?? "";
  const planCode = searchParams.get("plan_code") ?? "";
  const limit = parsePageLimit(searchParams.get("limit"));
  const offset = Number(searchParams.get("offset") ?? "0");

  const reload = useCallback(() => {
    if (!adminToken) return;
    adminListCustomers(
      { q: q || undefined, status: status || undefined, plan_code: planCode || undefined, limit, offset },
      adminToken,
    )
      .then(setPage)
      .catch(setError);
  }, [adminToken, q, status, planCode, limit, offset]);

  useEffect(reload, [reload]);

  useEffect(() => {
    if (!adminToken) return;
    adminListPlans(adminToken)
      .then(setPlans)
      .catch(() => setPlans([]));
  }, [adminToken]);

  function updateParams(next: { q?: string; status?: string; plan_code?: string; limit?: number; offset?: number }) {
    setSearchParams({
      q: next.q ?? q,
      status: next.status ?? status,
      plan_code: next.plan_code ?? planCode,
      limit: String(next.limit ?? limit),
      offset: String(next.offset ?? offset),
    });
  }

  const planColorByCode = Object.fromEntries(plans.map((p, i) => [p.plan_code, PLAN_COLORS[i % PLAN_COLORS.length]]));

  return (
    <section className="admin-customers-page">
      <h1>Customers</h1>
      <p className="lede">Everyone who has subscribed to an Everyticket plan, across every status.</p>

      <ErrorBanner error={error} />

      <div className="admin-panel">
        <div className="admin-toolbar">
          <form
            className="admin-toolbar-search"
            onSubmit={(e) => {
              e.preventDefault();
              const value = new FormData(e.currentTarget).get("q");
              updateParams({ q: String(value ?? ""), offset: 0 });
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
          <label>
            Account status
            <select value={status} onChange={(e) => updateParams({ status: e.target.value, offset: 0 })}>
              {ACCOUNT_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s || "All"}
                </option>
              ))}
            </select>
          </label>
          <label>
            Plan
            <select value={planCode} onChange={(e) => updateParams({ plan_code: e.target.value, offset: 0 })}>
              <option value="">All</option>
              {plans.map((p) => (
                <option key={p.plan_code} value={p.plan_code}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="table-wrap">
          <table className="data-table admin-customers-table">
            <thead>
              <tr>
                <th>Customer</th>
                <th>Mobile</th>
                <th>Plan</th>
                <th>Subscription</th>
                <th>Account</th>
                <th>Joined</th>
                <th aria-hidden="true"></th>
              </tr>
            </thead>
            <tbody>
              {page?.items.map((c) => (
                <tr key={c.customer_id} className="clickable" onClick={() => navigate(`/admin/customers/${c.customer_id}`)}>
                  <td>
                    <div className="cust-cell">
                      <span className="cust-avatar" style={{ background: avatarColorFor(c.customer_id) }}>
                        {initialsFor(c.email)}
                      </span>
                      <span className="cust-cell-text">
                        <b>{c.email}</b>
                        <span>{c.customer_id}</span>
                      </span>
                    </div>
                  </td>
                  <td>{c.mobile}</td>
                  <td>
                    {c.current_plan_name ? (
                      <span className="plan-pill">
                        <span
                          className="plan-pill-dot"
                          style={{ background: (c.current_plan_code && planColorByCode[c.current_plan_code]) || "#9ca3af" }}
                        />
                        {c.current_plan_name}
                      </span>
                    ) : (
                      <span className="hint">&mdash;</span>
                    )}
                  </td>
                  <td>
                    {c.current_subscription_status ? (
                      <StatusBadge value={c.current_subscription_status} />
                    ) : (
                      <span className="hint">&mdash;</span>
                    )}
                  </td>
                  <td>
                    <StatusBadge value={c.status} />
                  </td>
                  <td>{new Date(c.created_at).toLocaleDateString()}</td>
                  <td className="cust-chevron" aria-hidden="true">
                    &rsaquo;
                  </td>
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
            onOffsetChange={(next) => updateParams({ offset: next })}
            onLimitChange={(next) => updateParams({ limit: next, offset: 0 })}
          />
        )}
      </div>
    </section>
  );
}
