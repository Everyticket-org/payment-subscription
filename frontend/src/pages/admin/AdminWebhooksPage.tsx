/** Admin Webhook Logs (spec sections 34-37, 51): recent events (with
 * their delivery attempts) and a standalone deliveries list with a
 * manual retry action. Retry only resets a delivery to PENDING - the
 * actual HTTP dispatch stays the Celery beat schedule's job. */
import { useCallback, useEffect, useState } from "react";
import { adminListWebhookDeliveries, adminListWebhookEvents, adminRetryWebhookDelivery } from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { StatusBadge } from "../../components/StatusBadge";
import { useAuth } from "../../context/AuthContext";
import type { WebhookDeliveryOut, WebhookEventOut } from "../../api/types";

export function AdminWebhooksPage() {
  const { adminToken } = useAuth();
  const [events, setEvents] = useState<WebhookEventOut[] | null>(null);
  const [deliveries, setDeliveries] = useState<WebhookDeliveryOut[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [retryingId, setRetryingId] = useState<number | null>(null);

  const reload = useCallback(() => {
    if (!adminToken) return;
    adminListWebhookEvents({ limit: 20, offset: 0 }, adminToken)
      .then((page) => setEvents(page.items))
      .catch(setError);
    adminListWebhookDeliveries({ limit: 20, offset: 0 }, adminToken)
      .then((page) => setDeliveries(page.items))
      .catch(setError);
  }, [adminToken]);

  useEffect(reload, [reload]);

  async function handleRetry(deliveryId: number) {
    if (!adminToken) return;
    setRetryingId(deliveryId);
    try {
      await adminRetryWebhookDelivery(deliveryId, adminToken);
      reload();
    } catch (err) {
      setError(err);
    } finally {
      setRetryingId(null);
    }
  }

  return (
    <section>
      <h1>Webhook logs</h1>
      <p className="lede">
        Outbound Everyticket webhook events and their delivery attempts. A retry only re-queues a delivery - the
        actual dispatch runs on the next scheduled sweep.
      </p>

      <ErrorBanner error={error} />

      <div className="admin-panel">
        <h2>Deliveries</h2>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Destination</th>
                <th>Status</th>
                <th className="numeric">Attempts</th>
                <th>HTTP</th>
                <th>Last attempt</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {deliveries?.map((d) => (
                <tr key={d.id}>
                  <td>{d.destination_url}</td>
                  <td>
                    <StatusBadge value={d.status} />
                  </td>
                  <td className="numeric">{d.attempt_count}</td>
                  <td>{d.http_status ?? "-"}</td>
                  <td>{d.last_attempt_at ? new Date(d.last_attempt_at).toLocaleString() : "-"}</td>
                  <td>
                    {(d.status === "FAILED" || d.status === "EXHAUSTED") && (
                      <button className="button button-secondary" disabled={retryingId === d.id} onClick={() => handleRetry(d.id)}>
                        Retry
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {deliveries === null && !error && <p>Loading...</p>}
        {deliveries && deliveries.length === 0 && <p className="hint">No webhook deliveries yet.</p>}
      </div>

      <div className="admin-panel">
        <h2>Events</h2>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Event</th>
                <th>Entity</th>
                <th>When</th>
                <th>Deliveries</th>
              </tr>
            </thead>
            <tbody>
              {events?.map((e) => (
                <tr key={e.event_id}>
                  <td>{e.event_type}</td>
                  <td>
                    {e.entity_type} {e.entity_id}
                  </td>
                  <td>{new Date(e.created_at).toLocaleString()}</td>
                  <td>
                    {e.deliveries.map((d) => (
                      <StatusBadge key={d.id} value={d.status} />
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {events === null && !error && <p>Loading...</p>}
        {events && events.length === 0 && <p className="hint">No webhook events yet.</p>}
      </div>
    </section>
  );
}
