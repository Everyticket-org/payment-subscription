/** Admin Subscription detail + append-only history trail (spec sections
 * 46, 53). Read-only: state transitions only ever happen through real
 * payment events, never a direct admin edit here. */
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { adminGetSubscription } from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { StatusBadge } from "../../components/StatusBadge";
import { useAuth } from "../../context/AuthContext";
import type { SubscriptionDetailAdminOut } from "../../api/types";

export function AdminSubscriptionDetailPage() {
  const { subscriptionId = "" } = useParams();
  const { adminToken } = useAuth();
  const [detail, setDetail] = useState<SubscriptionDetailAdminOut | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!adminToken) return;
    adminGetSubscription(subscriptionId, adminToken).then(setDetail).catch(setError);
  }, [adminToken, subscriptionId]);

  return (
    <section>
      <p className="breadcrumb">
        <Link to="/admin/subscriptions">&larr; Subscriptions</Link>
      </p>
      <h1>{subscriptionId}</h1>

      <ErrorBanner error={error} />

      {detail === null && !error && <p>Loading...</p>}

      {detail && (
        <>
          <div className="admin-panel">
            <dl className="summary-list">
              <dt>Customer</dt>
              <dd>
                <Link to={`/admin/customers/${detail.subscription.customer_id}`}>{detail.subscription.customer_id}</Link>
              </dd>
              <dt>Plan</dt>
              <dd>{detail.subscription.plan_name}</dd>
              <dt>Status</dt>
              <dd>
                <StatusBadge value={detail.subscription.status} />
              </dd>
              <dt>Provisioning</dt>
              <dd>
                <StatusBadge value={detail.subscription.provisioning_status} />
              </dd>
              <dt>Starts</dt>
              <dd>{detail.subscription.starts_at ? new Date(detail.subscription.starts_at).toLocaleString() : "-"}</dd>
              <dt>Expires</dt>
              <dd>{detail.subscription.expires_at ? new Date(detail.subscription.expires_at).toLocaleString() : "-"}</dd>
              {detail.subscription.cancellation_reason && (
                <>
                  <dt>Cancellation reason</dt>
                  <dd>{detail.subscription.cancellation_reason}</dd>
                </>
              )}
            </dl>
          </div>

          <div className="admin-panel">
            <h2>History</h2>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Event</th>
                    <th>When</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.history.map((h, i) => (
                    <tr key={i}>
                      <td>
                        <StatusBadge value={h.event_type} />
                      </td>
                      <td>{new Date(h.occurred_at).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </section>
  );
}
