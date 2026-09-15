/**
 * Admin dashboard (spec section 52): active/new subscriptions, revenue,
 * failed payments, expiring/expired subscriptions, provisioning
 * failures, webhook failures - backed by GET /api/v1/admin/dashboard.
 *
 * 2026-09-15 follow-up ("suggest better design of admin panel... start
 * with dashboard design"): redesigned per the approved mockup - trend
 * chips on the headline KPIs, a "needs attention" panel, a revenue
 * trend chart, a plan-mix breakdown, and a recent-subscriptions table.
 * Every number here comes from the backend's real, additive
 * DashboardStatsOut fields (see admin_dashboard.py) - nothing in this
 * page is fabricated the way the review mockup's placeholder numbers
 * were, and the mockup's "Export report" button was dropped since there
 * is no real export feature behind it yet.
 */
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getAdminDashboard } from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { StatusBadge } from "../../components/StatusBadge";
import { useAuth } from "../../context/AuthContext";
import type { DashboardStatsOut } from "../../api/types";

const PLAN_MIX_COLORS = ["#d50355", "#7c3aed", "#0891b2", "#ca8a04", "#16a34a", "#64748b"];

function Stat({
  label,
  value,
  trend,
}: {
  label: string;
  value: string | number;
  trend?: { current: number; previous: number; invert?: boolean };
}) {
  return (
    <div className="stat-card">
      <p className="stat-label">{label}</p>
      <p className="stat-value">{value}</p>
      {trend && <TrendChip current={trend.current} previous={trend.previous} invert={trend.invert} />}
    </div>
  );
}

/** A trend chip comparing the current 30-day window to the one before it.
 * `invert` flips good/bad coloring for metrics where a rise is bad news
 * (failed payments) rather than good news (new subscriptions, revenue). */
function TrendChip({ current, previous, invert = false }: { current: number; previous: number; invert?: boolean }) {
  if (previous === 0 && current === 0) {
    return <span className="trend-chip trend-flat">No change</span>;
  }
  if (previous === 0) {
    return <span className="trend-chip trend-neutral">New</span>;
  }
  const pct = Math.round(((current - previous) / previous) * 1000) / 10;
  const isFlat = pct === 0;
  const isUp = pct > 0;
  const isGood = isFlat ? true : invert ? !isUp : isUp;
  const arrow = isFlat ? "→" : isUp ? "↑" : "↓";
  const cls = isFlat ? "trend-flat" : isGood ? "trend-good" : "trend-bad";
  return (
    <span className={`trend-chip ${cls}`}>
      {arrow} {Math.abs(pct)}% <span className="trend-chip-context">vs prior 30d</span>
    </span>
  );
}

export function AdminDashboardPage() {
  const { adminToken } = useAuth();
  const navigate = useNavigate();
  const [stats, setStats] = useState<DashboardStatsOut | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!adminToken) return;
    getAdminDashboard(adminToken).then(setStats).catch(setError);
  }, [adminToken]);

  return (
    <section className="admin-dashboard">
      <h1>Dashboard</h1>
      <p className="lede">Everyticket subscriptions at a glance - last 30 days unless noted.</p>

      <ErrorBanner error={error} />

      {stats === null && !error && <p>Loading...</p>}

      {stats && (
        <>
          <div className="stat-grid">
            <Stat label="Active subscriptions" value={stats.active_subscriptions} />
            <Stat
              label="New subscriptions (30d)"
              value={stats.new_subscriptions_30d}
              trend={{ current: stats.new_subscriptions_30d, previous: stats.new_subscriptions_30d_prev }}
            />
            <Stat
              label="Revenue (30d)"
              value={`${stats.revenue_currency} ${stats.revenue_30d.toFixed(2)}`}
              trend={{ current: stats.revenue_30d, previous: stats.revenue_30d_prev }}
            />
            <Stat
              label="Failed payments (30d)"
              value={stats.failed_payments_30d}
              trend={{ current: stats.failed_payments_30d, previous: stats.failed_payments_30d_prev, invert: true }}
            />
          </div>

          <div className="admin-panel dash-attention-panel">
            <h2>Needs attention</h2>
            <div className="dash-attention-grid">
              <Link to="/admin/subscriptions" className="dash-attention-item">
                <span className={`dash-attention-value ${stats.expiring_within_7d > 0 ? "is-warning" : ""}`}>
                  {stats.expiring_within_7d}
                </span>
                <span className="dash-attention-label">Expiring within 7 days</span>
              </Link>
              <Link to="/admin/subscriptions?status=EXPIRED" className="dash-attention-item">
                <span className={`dash-attention-value ${stats.expired_total > 0 ? "is-warning" : ""}`}>
                  {stats.expired_total}
                </span>
                <span className="dash-attention-label">Expired subscriptions</span>
              </Link>
              <Link to="/admin/subscriptions" className="dash-attention-item">
                <span className={`dash-attention-value ${stats.provisioning_failures > 0 ? "is-danger" : ""}`}>
                  {stats.provisioning_failures}
                </span>
                <span className="dash-attention-label">Provisioning failures</span>
              </Link>
              <Link to="/admin/webhooks" className="dash-attention-item">
                <span className={`dash-attention-value ${stats.webhook_failures > 0 ? "is-danger" : ""}`}>
                  {stats.webhook_failures}
                </span>
                <span className="dash-attention-label">Webhook failures</span>
              </Link>
            </div>
          </div>

          <div className="dash-grid-2">
            <div className="admin-panel">
              <h2>Revenue trend</h2>
              <p className="hint">Successful payments by month, in {stats.revenue_currency}.</p>
              {(() => {
                const maxRevenue = Math.max(1, ...stats.revenue_by_month.map((m) => m.amount));
                return (
                  <div className="dash-chart-bars">
                    {stats.revenue_by_month.map((point) => (
                      <div key={point.month} className="dash-chart-col" title={`${point.month_label}: ${stats.revenue_currency} ${point.amount.toFixed(2)}`}>
                        <span className="dash-chart-col-value">{Math.round(point.amount)}</span>
                        <div className="dash-chart-bar-track">
                          <div className="dash-chart-bar" style={{ height: `${(point.amount / maxRevenue) * 100}%` }} />
                        </div>
                        <span className="dash-chart-col-label">{point.month_label}</span>
                      </div>
                    ))}
                  </div>
                );
              })()}
            </div>

            <div className="admin-panel">
              <h2>Plan mix</h2>
              <p className="hint">Active subscriptions by plan.</p>
              {stats.plan_mix.length === 0 && <p className="hint">No active subscriptions yet.</p>}
              <div className="dash-planmix-list">
                {stats.plan_mix.map((item, idx) => {
                  const color = PLAN_MIX_COLORS[idx % PLAN_MIX_COLORS.length];
                  return (
                    <div key={item.plan_code} className="dash-planmix-row">
                      <span className="dash-planmix-dot" style={{ background: color }} />
                      <span className="dash-planmix-name">{item.plan_name}</span>
                      <div className="dash-planmix-bar-track">
                        <div className="dash-planmix-bar" style={{ width: `${item.percentage}%`, background: color }} />
                      </div>
                      <span className="dash-planmix-pct">{item.percentage}%</span>
                      <span className="dash-planmix-count">{item.count}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          <div className="admin-panel">
            <div className="dash-panel-head">
              <h2>Recent subscriptions</h2>
              <Link to="/admin/subscriptions" className="button button-secondary">
                View all
              </Link>
            </div>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Customer</th>
                    <th>Plan</th>
                    <th>Status</th>
                    <th>Amount</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {stats.recent_subscriptions.map((row) => (
                    <tr
                      key={row.subscription_id}
                      className="clickable"
                      onClick={() => navigate(`/admin/subscriptions/${row.subscription_id}`)}
                    >
                      <td>
                        <div>{row.customer_email}</div>
                        <div className="dash-table-subtle">{row.customer_id}</div>
                      </td>
                      <td>{row.plan_name}</td>
                      <td>
                        <StatusBadge value={row.status} />
                      </td>
                      <td>{row.amount !== null ? `${row.currency} ${row.amount.toFixed(2)}` : "-"}</td>
                      <td>{new Date(row.created_at).toLocaleDateString()}</td>
                    </tr>
                  ))}
                  {stats.recent_subscriptions.length === 0 && (
                    <tr>
                      <td colSpan={5} className="hint">
                        No subscriptions yet.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>

          <div className="admin-panel">
            <h2>Quick actions</h2>
            <div className="dash-quick-actions">
              <Link to="/admin/plans" className="button button-secondary">
                Manage plans
              </Link>
              <Link to="/admin/config/integration" className="button button-secondary">
                Integrations
              </Link>
              <Link to="/admin/testing" className="button button-secondary">
                Testing console
              </Link>
              <Link to="/admin/audit" className="button button-secondary">
                Audit logs
              </Link>
            </div>
          </div>
        </>
      )}
    </section>
  );
}
