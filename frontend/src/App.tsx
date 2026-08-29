import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { AdminLayout } from "./components/AdminLayout";
import { RequireAdmin, RequireCustomer } from "./components/ProtectedRoute";
import { PlansPage } from "./pages/public/PlansPage";
import { SubscribePage } from "./pages/public/SubscribePage";
import { PaymentReturnPage } from "./pages/public/PaymentReturnPage";
import { CustomerLoginPage } from "./pages/public/CustomerLoginPage";
import { PortalPage } from "./pages/customer/PortalPage";
import { AdminLoginPage } from "./pages/admin/AdminLoginPage";
import { AdminDashboardPage } from "./pages/admin/AdminDashboardPage";
import { AdminPlansPage } from "./pages/admin/AdminPlansPage";
import { AdminCustomersPage } from "./pages/admin/AdminCustomersPage";
import { AdminCustomerDetailPage } from "./pages/admin/AdminCustomerDetailPage";
import { AdminSubscriptionsPage } from "./pages/admin/AdminSubscriptionsPage";
import { AdminSubscriptionDetailPage } from "./pages/admin/AdminSubscriptionDetailPage";
import { AdminPaymentsPage } from "./pages/admin/AdminPaymentsPage";
import { AdminPaymentDetailPage } from "./pages/admin/AdminPaymentDetailPage";
import { AdminInvoicesPage } from "./pages/admin/AdminInvoicesPage";
import { AdminInvoiceDetailPage } from "./pages/admin/AdminInvoiceDetailPage";
import { AdminWebhooksPage } from "./pages/admin/AdminWebhooksPage";
import { AdminNotificationsPage } from "./pages/admin/AdminNotificationsPage";
import { AdminAuditLogsPage } from "./pages/admin/AdminAuditLogsPage";

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<PlansPage />} />
          <Route path="subscribe/:planCode" element={<SubscribePage />} />
          <Route path="payment/return" element={<PaymentReturnPage />} />
          <Route path="login" element={<CustomerLoginPage />} />
          <Route
            path="portal"
            element={
              <RequireCustomer>
                <PortalPage />
              </RequireCustomer>
            }
          />
          <Route path="admin/login" element={<AdminLoginPage />} />
        </Route>

        {/* The admin console gets its own sidebar shell (AdminLayout),
            entirely separate from the public site's header/footer. */}
        <Route
          path="admin"
          element={
            <RequireAdmin>
              <AdminLayout />
            </RequireAdmin>
          }
        >
          <Route index element={<AdminDashboardPage />} />
          <Route path="plans" element={<AdminPlansPage />} />
          <Route path="customers" element={<AdminCustomersPage />} />
          <Route path="customers/:customerId" element={<AdminCustomerDetailPage />} />
          <Route path="subscriptions" element={<AdminSubscriptionsPage />} />
          <Route path="subscriptions/:subscriptionId" element={<AdminSubscriptionDetailPage />} />
          <Route path="payments" element={<AdminPaymentsPage />} />
          <Route path="payments/:transactionId" element={<AdminPaymentDetailPage />} />
          <Route path="invoices" element={<AdminInvoicesPage />} />
          <Route path="invoices/:invoiceId" element={<AdminInvoiceDetailPage />} />
          <Route path="webhooks" element={<AdminWebhooksPage />} />
          <Route path="notifications" element={<AdminNotificationsPage />} />
          <Route path="audit" element={<AdminAuditLogsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
