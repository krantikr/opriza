import { NavLink, Route, Routes } from "react-router-dom";

import { useApi } from "./api/client";
import type { SystemStatus } from "./api/types";
import Customers from "./pages/Customers";
import Dashboard from "./pages/Dashboard";
import QuotationDetail from "./pages/QuotationDetail";
import Quotations from "./pages/Quotations";
import Stock from "./pages/Stock";

const NAV = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/quotations", label: "Quotations" },
  { to: "/stock", label: "Stock" },
  { to: "/customers", label: "Customers" },
];

function StatusDot({ ok, label }: { ok: boolean; label: string }) {
  return (
    <div className="flex items-center gap-2 text-xs text-ink-500">
      <span className={`size-1.5 rounded-full ${ok ? "bg-emerald-500" : "bg-amber-500"}`} />
      {label}
    </div>
  );
}

export default function App() {
  const { data: status } = useApi<SystemStatus>("/system/status", 60_000);

  return (
    <div className="flex min-h-full">
      <aside className="flex w-60 shrink-0 flex-col border-r border-ink-200 bg-white">
        <div className="border-b border-ink-200 px-5 py-4">
          <p className="text-sm font-semibold text-ink-900">Sales Quotation Copilot</p>
          <p className="mt-0.5 text-xs text-ink-500">
            {status?.environment ?? "…"} · rules v{status?.rules_version ?? "—"}
          </p>
        </div>

        <nav className="flex-1 space-y-1 p-3">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `block rounded-lg px-3 py-2 text-sm font-medium transition ${
                  isActive ? "bg-ink-900 text-white" : "text-ink-700 hover:bg-ink-100"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        {status && (
          <div className="space-y-2 border-t border-ink-200 px-5 py-4">
            <StatusDot ok={status.email_source_available} label={status.email_source} />
            <StatusDot
              ok={status.llm_configured}
              label={status.llm_configured ? "LLM configured" : "No OPENROUTER_API_KEY"}
            />
            {/* Spec Rule 4 - visible on every screen, not buried in a config file. */}
            <StatusDot ok={!status.auto_send_enabled} label="Approval required to send" />
          </div>
        )}
      </aside>

      <main className="min-w-0 flex-1 overflow-x-hidden">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/quotations" element={<Quotations />} />
          <Route path="/quotations/:id" element={<QuotationDetail />} />
          <Route path="/stock" element={<Stock />} />
          <Route path="/customers" element={<Customers />} />
        </Routes>
      </main>
    </div>
  );
}
