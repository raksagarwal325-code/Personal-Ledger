import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
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

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Layout />}>
          <Route index element={<Dashboard />} />
          <Route path="orders" element={<Orders />} />
          <Route path="transactions" element={<Orders />} />
          <Route path="sales-payments" element={<SalesPayments />} />
          <Route path="payments" element={<Payments />} />
          <Route path="party-ledger" element={<PartyLedger />} />
          <Route path="accounts" element={<Accounts />} />
          <Route path="vendors" element={<Vendors />} />
          <Route path="purchases" element={<Purchases />} />
          <Route path="purchase-payments" element={<PurchasePayments />} />
          <Route path="quotations" element={<Quotations />} />
          <Route path="exports" element={<Exports />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
