import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import Layout from "@/components/Layout";
import Dashboard from "@/pages/Dashboard";
import Orders from "@/pages/Orders";
import Payments from "@/pages/Payments";
import PartyLedger from "@/pages/PartyLedger";
import SalesPayments from "@/pages/SalesPayments";
import Accounts from "@/pages/Accounts";
import Exports from "@/pages/Exports";
import Vendors from "@/pages/Vendors";
import Purchases from "@/pages/Purchases";
import PurchasePayments from "@/pages/PurchasePayments";
import Quotations from "@/pages/Quotations";
import Login from "@/pages/Login";
import AdminDataManagement from "@/pages/AdminDataManagement";
import { AuthProvider, useAuth } from "@/lib/auth";

function ProtectedRoute({ children, adminOnly = false }) {
  const { user, ready } = useAuth();
  if (!ready) {
    return (
      <div className="min-h-screen flex items-center justify-center text-xs"
           style={{ color: "var(--muted)" }} data-testid="auth-loading">
        Loading…
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  if (adminOnly && user.role !== "admin") return <Navigate to="/" replace />;
  return children;
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="orders" element={<Orders />} />
        <Route path="transactions" element={<Orders />} />
        <Route path="sales-payments" element={<SalesPayments />} />
        <Route path="payments" element={<Payments />} />
        <Route path="transfers" element={<Payments />} />
        <Route path="party-ledger" element={<PartyLedger />} />
        <Route path="accounts" element={<Accounts />} />
        <Route path="vendors" element={<Vendors />} />
        <Route path="purchases" element={<Purchases />} />
        <Route path="purchase-payments" element={<PurchasePayments />} />
        <Route path="quotations" element={<Quotations />} />
        <Route path="exports" element={<Exports />} />
        <Route
          path="settings/admin/data-management"
          element={
            <ProtectedRoute adminOnly>
              <AdminDataManagement />
            </ProtectedRoute>
          }
        />
      </Route>
    </Routes>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </BrowserRouter>
  );
}

export default App;
