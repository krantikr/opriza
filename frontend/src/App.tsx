import { Suspense, lazy, useEffect } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";

import Shell from "./components/Shell";
import { ToastProvider, useToast } from "./components/Toasts";
import { Loading } from "./components/ui";
import { AuthProvider, useAuth } from "./lib/auth";
import { enablePush, listenInForeground } from "./lib/push";
import Account from "./pages/Account";
import Activity from "./pages/Activity";
import Admin from "./pages/Admin";
import Customers from "./pages/Customers";
import Dashboard from "./pages/Dashboard";
import Inbox from "./pages/Inbox";
import FollowUps from "./pages/FollowUps";
import MarketingLayout from "./marketing/Layout";
import MarketingHome from "./marketing/Home";
import MarketingProduct from "./marketing/Product";
import MarketingPricing from "./marketing/Pricing";
import MarketingAbout from "./marketing/About";
import MarketingContact from "./marketing/Contact";
import MailSchedule from "./pages/MailSchedule";
import Pricing from "./pages/Pricing";
import Quotations from "./pages/Quotations";
import Reports from "./pages/Reports";
import Settings from "./pages/Settings";
import { AcceptInvite, SignIn } from "./pages/SignIn";
import Stock from "./pages/Stock";
import Team from "./pages/Team";

/* The public demo is its own small app with its own styles, so it loads only
   when somebody opens /demo and adds nothing to the desk or marketing bundle. */
const DemoApp = lazy(() => import("./demo/DemoApp"));

/** Keeps this browser registered for push, and routes foreground messages
 *  to the toast layer.
 *
 *  Runs on every load rather than once: Firebase rotates registration tokens
 *  on its own schedule, so a device that registered a month ago and never
 *  re-registered would have quietly stopped receiving anything.
 *
 *  Silent on failure by design. Push not being configured, permission never
 *  granted, an unsupported browser - none of those are problems the trader
 *  asked about while opening the dashboard, and Settings is where the state
 *  is explained and fixed. */
function PushBridge() {
  const toast = useToast();

  useEffect(() => {
    let stop = () => {};
    let cancelled = false;

    // Only re-register where permission already exists. Prompting on load is
    // the pattern browsers penalise and people reflexively dismiss; the ask
    // lives behind a button in Settings.
    if (typeof Notification !== "undefined" && Notification.permission === "granted") {
      void enablePush();
    }

    void listenInForeground((title, body, link) => {
      // The tab is open, so the OS notification is suppressed and this shows
      // instead - otherwise the app buzzes about something already on screen.
      if (!cancelled) toast.push({ title, body, tone: "info", link });
    }).then((teardown) => {
      if (cancelled) teardown();
      else stop = teardown;
    });

    return () => {
      cancelled = true;
      stop();
    };
  }, [toast]);

  return null;
}

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
      <PushBridge />
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

/** The public marketing site, reachable without a session.
 *
 *  A signed-in trader who lands on a marketing URL is sent straight to the
 *  desk — they already bought what the page is selling. `/` is special: it is
 *  the trader's daily habit, so a signed-in visitor there goes to the desk and
 *  a visitor without a session gets the marketing home. */
function PublicSite() {
  const { user, loading } = useAuth();

  // Same hold as `Desk`: without it somebody with a valid session sees the
  // marketing page flash past on every refresh.
  if (loading) {
    return (
      <div className="grid min-h-screen place-items-center bg-ground">
        <Loading />
      </div>
    );
  }

  if (user) return <Desk />;

  return (
    <Routes>
      <Route element={<MarketingLayout />}>
        <Route path="/" element={<MarketingHome />} />
        <Route path="/product" element={<MarketingProduct />} />
        <Route path="/pricing" element={<MarketingPricing />} />
        <Route path="/about" element={<MarketingAbout />} />
        <Route path="/contact" element={<MarketingContact />} />
      </Route>
      {/* Anything else public falls through to the sign-in-gated desk. */}
      <Route path="*" element={<Desk />} />
    </Routes>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        {/* The live demo: public, no session, mock data only. */}
        <Route
          path="/demo/*"
          element={
            <Suspense fallback={<div className="grid min-h-screen place-items-center bg-ground"><Loading /></div>}>
              <DemoApp />
            </Suspense>
          }
        />
        {/* Auth screens stand alone, outside the marketing frame. */}
        <Route path="/sign-in" element={<SignIn />} />
        <Route path="/accept-invite" element={<AcceptInvite />} />
        {/* Everything else: public marketing when logged out, the desk when in. */}
        <Route path="/*" element={<PublicSite />} />
      </Routes>
    </AuthProvider>
  );
}
