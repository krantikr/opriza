import { Navigate, Route, Routes, useNavigate } from "react-router-dom";

import Shell from "./components/Shell";
import { ToastProvider } from "./components/Toasts";
import { Loading } from "./components/ui";
import { AuthProvider, useAuth } from "./lib/auth";
import Account from "./pages/Account";
import Activity from "./pages/Activity";
import Admin from "./pages/Admin";
import Customers from "./pages/Customers";
import Dashboard from "./pages/Dashboard";
import Inbox from "./pages/Inbox";
import FollowUps from "./pages/FollowUps";
import MailSchedule from "./pages/MailSchedule";
import Pricing from "./pages/Pricing";
import Quotations from "./pages/Quotations";
import Reports from "./pages/Reports";
import Settings from "./pages/Settings";
import { AcceptInvite, SignIn } from "./pages/SignIn";
import Stock from "./pages/Stock";
import Team from "./pages/Team";

/** The signed-in application. Nothing inside renders without a session. */
function Desk() {
  const { user, loading } = useAuth();
  const navigate = useNavigate();

  // Held until the stored token has been checked, so somebody with a valid
  // session never sees the sign-in page flash past on a refresh.
  if (loading) {
    return (
      <div className="grid min-h-screen place-items-center bg-ground">
        <Loading />
      </div>
    );
  }

  if (!user) return <Navigate to="/sign-in" replace />;

  // The platform operator belongs to no desk, so the trading screens have
  // nothing to show them - they get the console instead.
  if (user.is_super_admin) {
    return (
      <ToastProvider onOpenLink={navigate}>
        <Routes>
          <Route path="/admin" element={<Admin />} />
          {/* The operator has a password to change like anybody else. */}
          <Route path="/account" element={<Account />} />
          <Route path="*" element={<Navigate to="/admin" replace />} />
        </Routes>
      </ToastProvider>
    );
  }

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
          <Route path="/team" element={<Team />} />
          <Route path="/account" element={<Account />} />
          <Route path="/mail-schedule" element={<MailSchedule />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </Shell>
    </ToastProvider>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        {/* The two routes reachable without a session. */}
        <Route path="/sign-in" element={<SignIn />} />
        <Route path="/accept-invite" element={<AcceptInvite />} />
        <Route path="*" element={<Desk />} />
      </Routes>
    </AuthProvider>
  );
}
