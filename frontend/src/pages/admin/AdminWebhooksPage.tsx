/** Admin Webhook Logs (spec sections 34-37, 51): recent events (with
 * their delivery attempts) and a standalone deliveries list with a
 * manual retry action. Retry only resets a delivery to PENDING - the
 * actual HTTP dispatch stays the Celery beat schedule's job.
 *
 * Per Vishal's follow-up ("I want to have response into webhook logs"):
 * every delivery row - success or failure - already stored the
 * destination's raw response (or, for a network/timeout failure, the
 * error message) in response_body, but this screen never showed it.
 * Click a delivery row (or an event's row) to expand it and see the
 * response text, same click-to-expand pattern the Audit Logs page
 * already uses for old/new values.
 *
 * Per Vishal's next follow-up ("Webhook API is not getting reached or
 * logging headers, statuscode, etc.. from API... please give button as
 * well near log to click and verify that its calling properly or
 * not.."): the expanded view below now also shows the actual request
 * and response HTTP headers for every delivery (real or ad-hoc), and a
 * "Verify connectivity" button sends a small signed ping to the
 * configured destination right now and reports back immediately -
 * without needing TEST_MODE or the separate Testing module page - then
 * reloads so the attempt is visible in the log below. */
import { Fragment, useCallback, useEffect, useState } from "react";
import type { CSSProperties } from "react";
import {
  adminListWebhookDeliveries,
  adminListWebhookEvents,
  adminRetryWebhookDelivery,
  adminVerifyWebhookConnectivity,
} from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { StatusBadge } from "../../components/StatusBadge";
import { useAuth } from "../../context/AuthContext";
import { useToast } from "../../context/ToastContext";
import type { TestWebhookSendResult, WebhookDeliveryOut, WebhookEventOut } from "../../api/types";

function formatHeaders(headers: Record<string, string> | null | undefined): string {
  if (!headers || Object.keys(headers).length === 0) return "(none captured)";
  return Object.entries(headers)
    .map(([key, value]) => `${key}: ${value}`)
    .join("\n");
}

function DeliveryDetail({ delivery }: { delivery: WebhookDeliveryOut }) {
  const preStyle: CSSProperties = {
    whiteSpace: "pre-wrap",
    wordBreak: "break-all",
    overflowX: "auto",
    fontSize: 12,
    margin: 0,
  };
  return (
    <div style={{ display: "grid", gap: 8 }}>
      <div>
        <p className="hint" style={{ marginBottom: 2 }}>
          Request headers sent
        </p>
        <pre style={preStyle}>{formatHeaders(delivery.request_headers)}</pre>
      </div>
      <div>
        <p className="hint" style={{ marginBottom: 2 }}>
          Response headers received
        </p>
        <pre style={preStyle}>{formatHeaders(delivery.response_headers)}</pre>
      </div>
      <div>
        <p className="hint" style={{ marginBottom: 2 }}>
          Response body / error
        </p>
        <pre style={preStyle}>{delivery.response_body || "(no response body was returned)"}</pre>
      </div>
    </div>
  );
}

export function AdminWebhooksPage() {
  const { adminToken } = useAuth();
  const toast = useToast();
  const [events, setEvents] = useState<WebhookEventOut[] | null>(null);
  const [deliveries, setDeliveries] = useState<WebhookDeliveryOut[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [retryingId, setRetryingId] = useState<number | null>(null);
  const [expandedDeliveryId, setExpandedDeliveryId] = useState<number | null>(null);
  const [expandedEventId, setExpandedEventId] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [verifyResult, setVerifyResult] = useState<TestWebhookSendResult | null>(null);

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
      toast.success("Delivery re-queued");
      reload();
    } catch (err) {
      setError(err);
      toast.error(err);
    } finally {
      setRetryingId(null);
    }
  }

  async function handleVerify() {
    if (!adminToken) return;
    setVerifying(true);
    setVerifyResult(null);
    try {
      const result = await adminVerifyWebhookConnectivity(adminToken);
      setVerifyResult(result);
      if (result.sent) {
        toast.success(`Reached destination (HTTP ${result.http_status})`);
      } else {
        toast.error(`Could not reach destination${result.error ? `: ${result.error}` : ""}`);
      }
      reload();
    } catch (err) {
      setError(err);
      toast.error(err);
    } finally {
      setVerifying(false);
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
        <h2>Connectivity check</h2>
        <p className="hint">
          Sends a small, harmless signed ping to the currently-configured webhook destination right now and reports
          back immediately - useful when deliveries aren't showing up and you want to know if the destination is
          even reachable. The attempt is also recorded below like any other delivery.
        </p>
        <button className="button button-secondary" disabled={verifying} onClick={handleVerify}>
          {verifying ? "Verifying..." : "Verify connectivity"}
        </button>
        {verifyResult && (
          <div style={{ marginTop: 12 }}>
            <p>
              {verifyResult.sent ? (
                <span className="field-hint-ok">Reached - HTTP {verifyResult.http_status}</span>
              ) : (
                <span className="field-hint-error">Not reached{verifyResult.error ? `: ${verifyResult.error}` : ""}</span>
              )}
            </p>
            <pre
              style={{
                whiteSpace: "pre-wrap",
                wordBreak: "break-all",
                overflowX: "auto",
                fontSize: 12,
                margin: 0,
              }}
            >
              {`Request headers:\n${formatHeaders(verifyResult.request?.headers)}\n\nResponse headers:\n${formatHeaders(
                verifyResult.response_headers,
              )}`}
            </pre>
          </div>
        )}
      </div>

      <div className="admin-panel">
        <h2>Deliveries</h2>
        <p className="hint">Click a row to see the request/response headers and body (or error) that came back.</p>
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
                <Fragment key={d.id}>
                  <tr className="clickable" onClick={() => setExpandedDeliveryId(expandedDeliveryId === d.id ? null : d.id)}>
                    <td>{d.destination_url}</td>
                    <td>
                      <StatusBadge value={d.status} />
                    </td>
                    <td className="numeric">{d.attempt_count}</td>
                    <td>{d.http_status ?? "-"}</td>
                    <td>{d.last_attempt_at ? new Date(d.last_attempt_at).toLocaleString() : "-"}</td>
                    <td>
                      {(d.status === "FAILED" || d.status === "EXHAUSTED") && (
                        <button
                          className="button button-secondary"
                          disabled={retryingId === d.id}
                          onClick={(e) => {
                            e.stopPropagation();
                            handleRetry(d.id);
                          }}
                        >
                          Retry
                        </button>
                      )}
                    </td>
                  </tr>
                  {expandedDeliveryId === d.id && (
                    <tr>
                      <td colSpan={6}>
                        <DeliveryDetail delivery={d} />
                      </td>
                    </tr>
                  )}
                </Fragment>
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
                <Fragment key={e.event_id}>
                  <tr className="clickable" onClick={() => setExpandedEventId(expandedEventId === e.event_id ? null : e.event_id)}>
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
                  {expandedEventId === e.event_id && (
                    <tr>
                      <td colSpan={4}>
                        {e.deliveries.length === 0 && <p className="hint">No delivery attempts recorded.</p>}
                        {e.deliveries.map((d) => (
                          <div key={d.id} style={{ marginBottom: 8 }}>
                            <p className="hint">
                              Attempt to {d.destination_url} - <StatusBadge value={d.status} /> - HTTP {d.http_status ?? "-"}
                            </p>
                            <DeliveryDetail delivery={d} />
                          </div>
                        ))}
                      </td>
                    </tr>
                  )}
                </Fragment>
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
