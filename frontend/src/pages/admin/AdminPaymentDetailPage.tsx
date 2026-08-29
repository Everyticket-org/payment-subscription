/** Admin Payment detail (spec sections 23-28, 51, 53) - read-only,
 * including the raw gateway response for troubleshooting a real PayU
 * callback. */
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { adminGetPayment } from "../../api/endpoints";
import { ErrorBanner } from "../../components/ErrorBanner";
import { StatusBadge } from "../../components/StatusBadge";
import { useAuth } from "../../context/AuthContext";
import type { PaymentAdminOut } from "../../api/types";

export function AdminPaymentDetailPage() {
  const { transactionId = "" } = useParams();
  const { adminToken } = useAuth();
  const [payment, setPayment] = useState<PaymentAdminOut | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    if (!adminToken) return;
    adminGetPayment(transactionId, adminToken).then(setPayment).catch(setError);
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
