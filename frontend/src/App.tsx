import { Route, Routes, useNavigate } from "react-router-dom";

import Shell from "./components/Shell";
import { ToastProvider } from "./components/Toasts";
import Activity from "./pages/Activity";
import Customers from "./pages/Customers";
import Dashboard from "./pages/Dashboard";
import Inbox from "./pages/Inbox";
import FollowUps from "./pages/FollowUps";
import Pricing from "./pages/Pricing";
import Quotations from "./pages/Quotations";
import Reports from "./pages/Reports";
import Settings from "./pages/Settings";
import Stock from "./pages/Stock";

export default function App() {
  const navigate = useNavigate();

  return (
    <ToastProvider onOpenLink={navigate}>
      <Shell>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/inbox" element={<Inbox />} />
          <Route path="/activity" element={<Activity />} />
          <Route path="/quotations" element={<Quotations />} />
          <Route path="/quotations/:id" element={<Quotations />} />
          <Route path="/follow-ups" element={<FollowUps />} />
          <Route path="/stock" element={<Stock />} />
          <Route path="/customers" element={<Customers />} />
          <Route path="/pricing" element={<Pricing />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </Shell>
    </ToastProvider>
  );
}
