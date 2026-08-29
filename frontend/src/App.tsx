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
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
