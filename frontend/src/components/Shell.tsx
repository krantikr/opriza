import { useEffect, useRef, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";

import { api, useApi } from "../api/client";
import type { Page, SystemStatus } from "../api/types";
import {
  hasAsked,
  isWanted,
  needsHomeScreenInstall,
  permissionState,
  primeSeen,
  requestPermission,
  setWanted,
  systemNotify,
  takeUnseen,
} from "../lib/notifications";
import { useToast } from "./Toasts";
import { ago, Badge, Button } from "./ui";

/* ---------------------------------------------------------------------------
   Icons.

   Drawn inline as 1.5px strokes on a 24px grid rather than pulled from a set,
   so the weight matches the type and no CDN is involved.
   --------------------------------------------------------------------------- */

type IconProps = { className?: string };

const stroke = {
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.5,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

function Icon({ children, className = "size-4" }: { children: React.ReactNode; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden="true" {...stroke}>
      {children}
    </svg>
  );
}

export const Icons = {
  dashboard: (p: IconProps) => (
    <Icon {...p}>
      <rect x="3" y="3" width="7" height="9" rx="1" />
      <rect x="14" y="3" width="7" height="5" rx="1" />
      <rect x="14" y="12" width="7" height="9" rx="1" />
      <rect x="3" y="16" width="7" height="5" rx="1" />
    </Icon>
  ),
  inbox: (p: IconProps) => (
    <Icon {...p}>
      <path d="M3 12h4l2 3h6l2-3h4" />
      <path d="M4 5h16l1 7v6a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-6z" />
    </Icon>
  ),
  quotations: (p: IconProps) => (
    <Icon {...p}>
      <path d="M6 2h8l5 5v15a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z" />
      <path d="M14 2v5h5M9 13h6M9 17h4" />
    </Icon>
  ),
  stock: (p: IconProps) => (
    <Icon {...p}>
      <path d="M3 8l9-5 9 5-9 5-9-5z" />
      <path d="M3 12l9 5 9-5M3 16l9 5 9-5" />
    </Icon>
  ),
  customers: (p: IconProps) => (
    <Icon {...p}>
      <circle cx="9" cy="8" r="3.5" />
      <path d="M3 20a6 6 0 0 1 12 0M17 11a3 3 0 1 0-2-5.2M21 20a5 5 0 0 0-4-4.9" />
    </Icon>
  ),
  pricing: (p: IconProps) => (
    <Icon {...p}>
      <path d="M4 7h16M4 12h16M4 17h10" />
      <circle cx="17" cy="17" r="3.5" />
    </Icon>
  ),
  reports: (p: IconProps) => (
    <Icon {...p}>
      <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />
    </Icon>
  ),
  settings: (p: IconProps) => (
    <Icon {...p}>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M19.1 4.9L17 7M7 17l-2.1 2.1" />
    </Icon>
  ),
  bell: (p: IconProps) => (
    <Icon {...p}>
      <path d="M18 8a6 6 0 1 0-12 0c0 7-3 8-3 8h18s-3-1-3-8" />
      <path d="M13.7 21a2 2 0 0 1-3.4 0" />
    </Icon>
  ),
  sun: (p: IconProps) => (
    <Icon {...p}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </Icon>
  ),
  moon: (p: IconProps) => (
    <Icon {...p}>
      <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
    </Icon>
  ),
  activity: (p: IconProps) => (
    <Icon {...p}>
      <path d="M3 12h4l3-8 4 16 3-8h4" />
    </Icon>
  ),
  followup: (p: IconProps) => (
    <Icon {...p}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </Icon>
  ),
};

const NAV = [
  { to: "/", label: "Home", end: true, icon: Icons.dashboard },
  { to: "/inbox", label: "Inbox", icon: Icons.inbox },
  { to: "/quotations", label: "Quotes", icon: Icons.quotations },
  { to: "/follow-ups", label: "Chase", icon: Icons.followup },
  { to: "/stock", label: "Stock", icon: Icons.stock },
  { to: "/customers", label: "Clients", icon: Icons.customers },
  { to: "/pricing", label: "Pricing", icon: Icons.pricing },
  { to: "/reports", label: "Reports", icon: Icons.reports },
  { to: "/activity", label: "Activity", icon: Icons.activity },
  { to: "/settings", label: "Settings", icon: Icons.settings },
];

/* ---------------------------------------------------------------------------
   Theme
   --------------------------------------------------------------------------- */

type Theme = "light" | "dark" | "system";

function useTheme() {
  const [theme, setTheme] = useState<Theme>(
    () => (localStorage.getItem("theme") as Theme) || "system",
  );

  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    localStorage.setItem("theme", theme);
  }, [theme]);

  return { theme, setTheme };
}

function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const next: Record<Theme, Theme> = { system: "light", light: "dark", dark: "system" };
  const label = { system: "System theme", light: "Light theme", dark: "Dark theme" }[theme];

  return (
    <button
      type="button"
      onClick={() => setTheme(next[theme])}
      title={`${label} — click to change`}
      className="rounded p-1.5 text-ink-faint transition-colors hover:bg-sunk hover:text-ink"
    >
      {theme === "dark" ? <Icons.moon /> : <Icons.sun />}
    </button>
  );
}

/* ---------------------------------------------------------------------------
   Notifications
   --------------------------------------------------------------------------- */

interface NotificationRow {
  id: number;
  kind: string;
  title: string;
  body: string | null;
  link: string | null;
  created_at: string;
  read_at: string | null;
}

function NotificationBell() {
  const [open, setOpen] = useState(false);
  const panel = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();
  const toast = useToast();

  const [permission, setPermission] = useState(permissionState());
  const [wanted, setWantedState] = useState(isWanted());
  const primed = useRef(false);

  const { data: count, reload: reloadCount } = useApi<{ unread: number }>(
    "/notifications/unread-count",
    30_000,
  );

  // Polled whether or not the panel is open: the whole point is to notice
  // something arriving while you are looking at another screen.
  const { data: recent, reload: reloadRecent } = useApi<Page<NotificationRow>>(
    "/notifications?limit=15",
    30_000,
  );

  useEffect(() => {
    const items = recent?.items ?? [];
    if (items.length === 0) return;

    const announceable = items
      .filter((row) => !row.read_at)
      .map((row) => ({
        id: row.id,
        title: row.title,
        body: row.body,
        link: row.link,
        kind: row.kind,
      }));

    // The first poll records the backlog rather than announcing it, so opening
    // the app in the morning does not fire twenty alerts at once.
    if (!primed.current) {
      primed.current = true;
      primeSeen(announceable);
      return;
    }

    // In-app toasts fire regardless of browser permission - they are the
    // floor that works everywhere, including iOS Safari.
    const fresh = takeUnseen(announceable);
    for (const item of fresh.slice(0, 2)) {
      toast.push({
        title: item.title,
        body: item.body ?? undefined,
        tone: item.kind === "FOLLOW_UP_DUE" ? "attention" : "info",
        link: item.link ?? undefined,
      });
    }
    systemNotify(fresh, (link) => navigate(link));
  }, [recent, navigate, toast]);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (panel.current && !panel.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  // Alerts are on by default, so the browser prompt is raised at the first
  // real interaction - the earliest moment a gesture exists to attach it to.
  useEffect(() => {
    if (hasAsked() || !isWanted() || permissionState() !== "default") return;

    const ask = async () => {
      setPermission(await requestPermission());
    };
    window.addEventListener("pointerdown", ask, { once: true });
    window.addEventListener("keydown", ask, { once: true });
    return () => {
      window.removeEventListener("pointerdown", ask);
      window.removeEventListener("keydown", ask);
    };
  }, []);

  const unread = count?.unread ?? 0;

  async function toggleAlerts() {
    if (wanted) {
      setWanted(false);
      setWantedState(false);
      return;
    }
    setWanted(true);
    setWantedState(true);

    // Must run inside this click: browsers ignore a permission request made
    // outside a user gesture.
    const result = await requestPermission();
    setPermission(result);

    toast.push(
      result === "granted"
        ? {
            title: "Alerts on",
            body: "New enquiries will reach you even with this tab in the background.",
            tone: "settled",
          }
        : result === "denied"
          ? {
              title: "System alerts blocked",
              body: "Your browser is blocking them. In-app alerts still work.",
              tone: "attention",
            }
          : {
              title: "In-app alerts on",
              body: "This browser cannot show system notifications.",
              tone: "info",
            },
    );
  }

  async function openItem(row: NotificationRow) {
    await api.post(`/notifications/${row.id}/read`).catch(() => undefined);
    reloadCount();
    reloadRecent();
    setOpen(false);
    if (row.link) navigate(row.link);
  }

  return (
    <div className="relative" ref={panel}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        title="Notifications"
        className="relative rounded-lg p-1.5 text-ink-faint transition-colors hover:bg-sunk hover:text-ink"
      >
        <Icons.bell />
        {unread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex min-w-4 items-center justify-center rounded-full bg-danger px-1 text-[10px] font-semibold text-white">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 z-20 mt-2 w-[22rem] overflow-hidden rounded-card border border-rule bg-surface shadow-raised">
          <header className="flex items-center justify-between gap-2 border-b border-rule px-3 py-2">
            <span className="text-sm font-semibold text-ink">Notifications</span>
            {unread > 0 && (
              <Button
                variant="ghost"
                onClick={async () => {
                  await api.post("/notifications/read-all");
                  reloadCount();
                  reloadRecent();
                }}
              >
                Mark all read
              </Button>
            )}
          </header>

          {/* Alerts: the switch lives where the notifications are. */}
          <div className="flex items-start justify-between gap-3 border-b border-rule bg-sunk px-3 py-2.5">
            <div className="min-w-0">
              <p className="text-xs font-medium text-ink">Alerts</p>
              <p className="mt-0.5 text-[11px] leading-snug text-ink-faint">
                {!wanted
                  ? "Off. Only the bell will show new work."
                  : needsHomeScreenInstall()
                    ? "In-app alerts on. Add this to your home screen for alerts on your lock screen."
                    : permission === "granted"
                      ? "On. You will be told even with this app in the background."
                      : permission === "denied"
                        ? "In-app only — your browser is blocking system alerts."
                        : "In-app alerts on. Tap to also allow system alerts."}
              </p>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={wanted}
              aria-label="Alerts"
              onClick={toggleAlerts}
              className="mt-0.5 shrink-0"
            >
              <span
                className={`relative block h-5 w-9 rounded-full transition-colors ${
                  wanted ? "bg-brand" : "bg-rule-firm"
                }`}
              >
                <span
                  className={`absolute top-0.5 size-4 rounded-full bg-white transition-transform ${
                    wanted ? "translate-x-4.5" : "translate-x-0.5"
                  }`}
                />
              </span>
            </button>
          </div>

          <div className="max-h-80 overflow-y-auto">
            {!recent?.items.length && (
              <p className="p-6 text-center text-sm text-ink-faint">Nothing yet.</p>
            )}
            {recent?.items.map((row) => (
              <button
                key={row.id}
                type="button"
                onClick={() => openItem(row)}
                className={`flex w-full flex-col gap-0.5 border-b border-rule px-3 py-2.5 text-left transition-colors last:border-0 hover:bg-sunk ${
                  row.read_at ? "opacity-55" : ""
                }`}
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="truncate text-sm font-medium text-ink">{row.title}</span>
                  <span className="shrink-0 text-[11px] text-ink-faint">{ago(row.created_at)}</span>
                </div>
                {row.body && (
                  <span className="line-clamp-2 text-xs text-ink-soft">{row.body}</span>
                )}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------------------
   Shell
   --------------------------------------------------------------------------- */

/** Health, shown as a dot on the rail with the detail in the tooltip. */
function StatusDot({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      title={label}
      className={`size-2 rounded-full ${ok ? "bg-settled" : "bg-attention"}`}
    />
  );
}

/** The five destinations a phone gets in its bottom bar. */
const MOBILE_NAV = NAV.filter((n) =>
  ["/", "/inbox", "/quotations", "/stock", "/customers"].includes(n.to),
);

export default function Shell({ children }: { children: React.ReactNode }) {
  const { data: status } = useApi<SystemStatus>("/system/status", 60_000);
  const { data: queue } = useApi<{ id: number }[]>("/follow-ups/queue", 60_000);
  const [menuOpen, setMenuOpen] = useState(false);

  const dueCount = queue?.length ?? 0;

  return (
    <div className="flex min-h-full w-full overflow-x-hidden">
      {/* --- Rail: desktop only ------------------------------------------- */}
      <aside className="sticky top-0 hidden h-screen w-20 shrink-0 flex-col items-center bg-rail py-3 md:flex">
        <span className="mb-4 grid size-10 shrink-0 place-items-center rounded-xl bg-brand text-base font-bold text-white shadow-raised">
          S
        </span>

        <nav className="flex flex-1 flex-col items-center gap-1 overflow-y-auto">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              title={item.label}
              className={({ isActive }) =>
                `group relative flex w-16 flex-col items-center gap-1 rounded-xl px-1 py-2 transition-colors ${
                  isActive
                    ? "bg-brand-soft/15 text-brand-soft"
                    : "text-rail-ink hover:bg-rail-hover hover:text-rail-ink-strong"
                }`
              }
            >
              <item.icon className="size-[18px] shrink-0" />
              <span className="w-full truncate text-center text-[10px] font-medium leading-tight">
                {item.label}
              </span>
              {item.to === "/follow-ups" && dueCount > 0 && (
                <span className="absolute right-1.5 top-1 grid size-4 place-items-center rounded-full bg-attention text-[9px] font-bold text-white">
                  {dueCount}
                </span>
              )}
            </NavLink>
          ))}
        </nav>

        {status && (
          <div className="flex flex-col items-center gap-2 pt-3">
            <StatusDot ok={status.email_source_available} label={status.email_source} />
            <StatusDot
              ok={status.llm_configured}
              label={status.llm_configured ? "LLM configured" : "No API key"}
            />
            <StatusDot ok={!status.auto_send_enabled} label="Approval required to send" />
          </div>
        )}
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex items-center justify-between gap-3 border-b border-rule bg-surface px-4 py-2.5 md:px-5">
          <div className="flex min-w-0 items-center gap-2">
            <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-brand text-xs font-bold text-white md:hidden">
              S
            </span>
            <div className="flex min-w-0 items-baseline gap-2">
              <span className="truncate text-sm font-semibold text-ink">Steel Desk</span>
              <span className="hidden text-[11px] text-ink-faint sm:inline">
                pricing rules v{status?.rules_version ?? "—"}
              </span>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <NotificationBell />
            <ThemeToggle />
            {/* Everything not in the bottom bar lives behind this. */}
            <button
              type="button"
              onClick={() => setMenuOpen((v) => !v)}
              aria-label="More"
              className="rounded-lg p-1.5 text-ink-faint hover:bg-sunk hover:text-ink md:hidden"
            >
              <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="1.8">
                <path d="M4 7h16M4 12h16M4 17h16" strokeLinecap="round" />
              </svg>
            </button>
          </div>
        </header>

        {menuOpen && (
          <nav className="grid grid-cols-3 gap-1 border-b border-rule bg-surface p-3 md:hidden">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                onClick={() => setMenuOpen(false)}
                className={({ isActive }) =>
                  `flex items-center gap-2 rounded-lg px-2.5 py-2 text-[13px] font-medium ${
                    isActive ? "bg-brand-wash text-brand-soft-ink" : "text-ink-soft hover:bg-sunk"
                  }`
                }
              >
                <item.icon className="size-4 shrink-0" />
                <span className="truncate">{item.label}</span>
              </NavLink>
            ))}
          </nav>
        )}

        {/* Padded for the bottom bar so the last row is never covered. */}
        <main className="min-w-0 flex-1 overflow-x-hidden pb-16 md:pb-0">{children}</main>
      </div>

      {/* --- Bottom bar: phones only --------------------------------------- */}
      <nav className="fixed inset-x-0 bottom-0 z-20 flex border-t border-rule bg-surface md:hidden">
        {MOBILE_NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              `relative flex flex-1 flex-col items-center gap-0.5 py-2 text-[10px] font-medium transition-colors ${
                isActive ? "text-brand-soft-ink" : "text-ink-faint"
              }`
            }
          >
            <item.icon className="size-5" />
            <span className="truncate">{item.label}</span>
            {item.to === "/quotations" && dueCount > 0 && (
              <span className="absolute right-1/4 top-1 size-1.5 rounded-full bg-attention" />
            )}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

export { Badge };
