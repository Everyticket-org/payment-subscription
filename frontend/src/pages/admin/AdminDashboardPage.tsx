/**
 * Admin dashboard (spec section 52): active/new subscriptions, revenue,
 * failed payments, expiring/expired subscriptions, provisioning
 * failures, webhook failures - backed by GET /api/v1/admin/dashboard.
 */
import { useEffect, useState } from "react";
import { getAdminDashboard } from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { useAuth } from "../../context/AuthContext";
import type { DashboardStatsOut } from "../../api/types";

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="stat-card">
      <p className="stat-label">{label}</p>
      <p className="stat-value">{value}</p>
    </div>
  );
}

export function AdminDashboardPage() {
  const { adminToken } = useAuth();
  const [stats, setStats] = useState<DashboardStatsOut | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!adminToken) return;
    getAdminDashboard(adminToken).then(setStats).catch(setError);
  }, [adminToken]);

  return (
    <section>
      <h1>Dashboard</h1>
      <p className="lede">Everyticket subscriptions at a glance - last 30 days unless noted.</p>

      <ErrorBanner error={error} />

      {stats === null && !error && <p>Loading...</p>}

      {stats && (
        <div className="stat-grid">
          <Stat label="Active subscriptions" value={stats.active_subscriptions} />
          <Stat label="New subscriptions (30d)" value={stats.new_subscriptions_30d} />
          <Stat label="Revenue (30d)" value={`${stats.revenue_currency} ${stats.revenue_30d.toFixed(2)}`} />
          <Stat label="Failed payments (30d)" value={stats.failed_payments_30d} />
          <Stat label="Expiring within 7 days" value={stats.expiring_within_7d} />
          <Stat label="Expired subscriptions" value={stats.expired_total} />
          <Stat label="Provisioning failures" value={stats.provisioning_failures} />
          <Stat label="Webhook failures" value={stats.webhook_failures} />
        </div>
      )}
    </section>
  );
}
