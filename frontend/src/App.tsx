import { BrowserRouter, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { RequireAdmin, RequireCustomer } from "./components/ProtectedRoute";
import { PlansPage } from "./pages/public/PlansPage";
import { SubscribePage } from "./pages/public/SubscribePage";
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
          <Route
            path="admin"
            element={
              <RequireAdmin>
                <AdminDashboardPage />
              </RequireAdmin>
            }
          />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
