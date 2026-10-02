/** Admin Payment detail (spec sections 23-28, 51, 53) - read-only,
 * including the raw gateway response and the payment's event history
 * (where it was started, the surl/furl sent to PayU, and every browser
 * return / webhook / reconciliation check) for troubleshooting a real
 * PayU payment. */
import { Fragment, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { adminGetPayment, adminListPaymentEvents } from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { StatusBadge } from "../../components/StatusBadge";
import { useAuth } from "../../context/AuthContext";
import type { PaymentAdminOut, PaymentEventOut } from "../../api/types";

const EVENT_LABELS: Record<string, string> = {
  INITIATED: "Payment started",
  BROWSER_RETURN: "Browser return (surl/furl)",
  WEBHOOK: "PayU webhook",
  STATUS_CHECK: "Result page check",
  RECONCILE: "Reconciliation check",
};

// Results that need a person to look at them.
const ATTENTION_RESULTS = new Set(["LATE_SUCCESS_IGNORED", "AMOUNT_MISMATCH", "HASH_FAILED", "ERROR"]);

function resultBadgeClass(result: string): string {
  if (ATTENTION_RESULTS.has(result)) return "badge badge-danger";
  if (result === "PROCESSED" || result === "CREATED") return "badge badge-success";
  if (result === "STILL_PENDING" || result === "EXPIRED") return "badge badge-warning";
  return "badge badge-neutral";
}

function EventDetails({ event }: { event: PaymentEventOut }) {
  const rows: [string, string | null | undefined][] = [
    ["Started from", event.initiated_from],
    ["Channel", event.channel],
    ["surl sent", event.surl_sent],
    ["furl sent", event.furl_sent],
    ["Return page", event.return_url],
    ["Endpoint", event.endpoint],
    ["PayU status", event.gateway_status],
    ["PayU ID (mihpayid)", event.gateway_transaction_id],
    ["Hash verified", event.hash_verified == null ? null : event.hash_verified ? "Yes" : "No"],
    ["Source IP", event.source_ip],
    ["User agent", event.user_agent],
  ];
  const present = rows.filter(([, value]) => value);
  return (
    <>
      {present.length > 0 && (
        <dl className="summary-list payment-event-details">
          {present.map(([label, value]) => (
            <Fragment key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </Fragment>
          ))}
        </dl>
      )}
      {event.payload && (
        <pre className="payment-event-payload">{JSON.stringify(event.payload, null, 2)}</pre>
      )}
    </>
  );
}

export function AdminPaymentDetailPage() {
  const { transactionId = "" } = useParams();
  const { adminToken } = useAuth();
  const [payment, setPayment] = useState<PaymentAdminOut | null>(null);
  const [events, setEvents] = useState<PaymentEventOut[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [eventsError, setEventsError] = useState<unknown>(null);
  const [openEventId, setOpenEventId] = useState<number | null>(null);

  useEffect(() => {
    if (!adminToken) return;
    adminGetPayment(transactionId, adminToken).then(setPayment).catch(setError);
    adminListPaymentEvents(transactionId, adminToken).then(setEvents).catch(setEventsError);
  }, [adminToken, transactionId]);

  return (
    <section>
      <p className="breadcrumb">
        <Link to="/admin/payments">&larr; Payments</Link>
      </p>
      <h1>{transactionId}</h1>

      <ErrorBanner error={error} />

      {payment === null && !error && <p>Loading...</p>}

      {payment && (
        <>
          <div className="admin-panel">
            <dl className="summary-list">
              <dt>Customer</dt>
              <dd>
                <Link to={`/admin/customers/${payment.customer_id}`}>{payment.customer_id}</Link>
              </dd>
              <dt>Subscription</dt>
              <dd>
                <Link to={`/admin/subscriptions/${payment.subscription_id}`}>{payment.subscription_id}</Link>
              </dd>
              <dt>Plan</dt>
              <dd>{payment.plan_code}</dd>
              <dt>Gateway</dt>
              <dd>{payment.gateway}</dd>
              <dt>Gateway transaction ID</dt>
              <dd>{payment.gateway_transaction_id ?? "-"}</dd>
              <dt>Amount</dt>
              <dd>
                {payment.currency} {payment.amount.toFixed(2)}
              </dd>
              <dt>Type</dt>
              <dd>{payment.payment_type}</dd>
              <dt>Status</dt>
              <dd>
                <StatusBadge value={payment.status} />
              </dd>
              {payment.failure_reason && (
                <>
                  <dt>Failure reason</dt>
                  <dd>{payment.failure_reason}</dd>
                </>
              )}
            </dl>
          </div>

          <div className="admin-panel">
            <h2>Payment history</h2>
            <ErrorBanner error={eventsError} />
            {events === null && !eventsError && <p>Loading...</p>}
            {events && events.length === 0 && (
              <p className="hint">
                No history recorded for this payment. Payments made before the history log was added, and test
                payments from the Testing tools, have none.
              </p>
            )}
            {events && events.length > 0 && (
              <div className="table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Time</th>
                      <th>Event</th>
                      <th>Result</th>
                      <th>PayU status</th>
                      <th>Source</th>
                      <th aria-label="Details" />
                    </tr>
                  </thead>
                  <tbody>
                    {events.map((event) => {
                      const open = openEventId === event.id;
                      return (
                        <Fragment key={event.id}>
                          <tr>
                            <td>{new Date(event.created_at).toLocaleString()}</td>
                            <td>{EVENT_LABELS[event.event_type] ?? event.event_type}</td>
                            <td>
                              <span className={resultBadgeClass(event.result)}>{event.result.replace(/_/g, " ")}</span>
                            </td>
                            <td>{event.gateway_status ?? "-"}</td>
                            <td>{event.initiated_from ?? event.endpoint ?? "-"}</td>
                            <td>
                              <button
                                className="button button-secondary payment-event-toggle"
                                onClick={() => setOpenEventId(open ? null : event.id)}
                                aria-expanded={open}
                              >
                                {open ? "Hide" : "Details"}
                              </button>
                            </td>
                          </tr>
                          {open && (
                            <tr>
                              <td colSpan={6}>
                                <EventDetails event={event} />
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {payment.raw_gateway_response && (
            <div className="admin-panel">
              <h2>Raw gateway response</h2>
              <pre style={{ overflowX: "auto", fontSize: 13 }}>
                {JSON.stringify(payment.raw_gateway_response, null, 2)}
              </pre>
            </div>
          )}
        </>
      )}
    </section>
  );
}
