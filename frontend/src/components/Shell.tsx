import { useEffect, useRef, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";

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
import { useAuth } from "../lib/auth";
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
  chevronLeft: (p: IconProps) => (
    <Icon {...p}>
      <path d="M15 5l-7 7 7 7" />
    </Icon>
  ),
};

const NAV = [
  { to: "/", label: "Home", end: true, icon: Icons.dashboard },
  { to: "/inbox", label: "Inbox", icon: Icons.inbox },
  { to: "/quotations", label: "Quotes", icon: Icons.quotations },
  { to: "/follow-ups", label: "Follow-ups", icon: Icons.followup },
  { to: "/stock", label: "Stock", icon: Icons.stock },
  { to: "/customers", label: "Clients", icon: Icons.customers },
  { to: "/pricing", label: "Pricing", icon: Icons.pricing },
  { to: "/reports", label: "Reports", icon: Icons.reports },
  { to: "/activity", label: "Activity", icon: Icons.activity },
  { to: "/team", label: "Team", icon: Icons.customers },
  { to: "/settings", label: "Settings", icon: Icons.settings },
];

/* What the top bar calls the current page.

   Separate from the rail labels on purpose: the rail is abbreviated where it
   needs to be to keep eleven destinations on one line each ("Quotes"), while
   the header is the page's own title and matches what the page used to print
   above its own content ("Quotations"). Longest prefix wins, so
   /quotations/17 still reads "Quotations". */
const PAGE_TITLES: [string, string][] = [
  ["/inbox", "Inbox"],
  ["/quotations", "Quotations"],
  ["/follow-ups", "Follow-ups"],
  ["/stock", "Stock"],
  ["/customers", "Clients"],
  ["/pricing", "Pricing"],
  ["/reports", "Reports"],
  ["/activity", "Activity"],
  ["/team", "Team"],
  ["/account", "Your account"],
  ["/mail-schedule", "Mail checking"],
  ["/settings", "Settings"],
];

export function pageTitle(pathname: string): string {
  const match = PAGE_TITLES.filter(([path]) => pathname.startsWith(path)).sort(
    (a, b) => b[0].length - a[0].length,
  )[0];
  return match ? match[1] : "Home";
}

/* The rail reads as three jobs rather than one list of eleven: the work that
   arrives, the reference data behind a quote, and the desk itself. Dividers
   cost nothing vertically and stop the eye from counting. */
const RAIL_GROUPS: { items: typeof NAV }[] = [
  { items: NAV.slice(0, 4) },   // Home, Inbox, Quotes, Follow-ups
  { items: NAV.slice(4, 8) },   // Stock, Clients, Pricing, Reports
  { items: NAV.slice(8) },      // Activity, Team, Settings
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

/* ---------------------------------------------------------------------------
   Rail collapse
   --------------------------------------------------------------------------- */

/** Collapsed is the default: the desk screens are wide tables, and the eleven
    destinations are learned in a day. The choice is remembered per browser so
    anyone who wants the labels back only asks once. */
function useRailCollapsed() {
  const [collapsed, setCollapsed] = useState(
    () => (localStorage.getItem("rail") ?? "collapsed") === "collapsed",
  );

  useEffect(() => {
    localStorage.setItem("rail", collapsed ? "collapsed" : "expanded");
  }, [collapsed]);

  return [collapsed, setCollapsed] as const;
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
              {/* Same construction as `Toggle` in ui.tsx - flex with padding,
                  so the knob is laid out inside the track rather than
                  positioned against a hand-matched width. Hand-rolled here
                  because this one sits on the dark rail, but the two must not
                  drift into looking like different controls. */}
              <span
                className={`relative flex h-5 w-9 items-center rounded-full p-0.5 transition-colors ${
                  wanted ? "bg-brand-ink" : "bg-rule-firm"
                }`}
              >
                <span
                  className={`size-4 rounded-full bg-white shadow-sm transition-transform duration-200 ${
                    wanted ? "translate-x-full" : "translate-x-0"
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
      className={`size-1.5 shrink-0 rounded-full ${ok ? "bg-settled" : "bg-attention"}`}
    />
  );
}

/** The five destinations a phone gets in its bottom bar. */
const MOBILE_NAV = NAV.filter((n) =>
  ["/", "/inbox", "/quotations", "/stock", "/customers"].includes(n.to),
);

/** Who is signed in, and the way out.

    On a shared trading-desk machine "whose account is this" has to be
    answerable at a glance, so the name is in the header rather than behind a
    menu, and signing out is one click from anywhere. */
function UserMenu() {
  const { user, signOut } = useAuth();
  const [open, setOpen] = useState(false);
  if (!user) return null;

  const initials = user.name
    .split(" ")
    .map((part) => part[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label="Your account"
        className="grid size-7 place-items-center rounded-full bg-brand-wash text-[11px] font-semibold text-brand"
      >
        {initials}
      </button>

      {open && (
        <>
          {/* Click anywhere to dismiss, without trapping focus. */}
          <button
            type="button"
            aria-hidden
            tabIndex={-1}
            className="fixed inset-0 z-40 cursor-default"
            onClick={() => setOpen(false)}
          />
          <div className="absolute right-0 z-50 mt-1.5 w-56 rounded-lg border border-rule bg-surface p-1 shadow-lg">
            <div className="border-b border-rule px-3 py-2">
              <p className="truncate text-sm font-medium text-ink">{user.name}</p>
              <p className="truncate text-xs text-ink-faint">{user.email}</p>
            </div>
            <NavLink
              to="/account"
              onClick={() => setOpen(false)}
              className="block rounded px-3 py-2 text-sm text-ink hover:bg-sunk"
            >
              Your account
            </NavLink>
            <NavLink
              to="/mail-schedule"
              onClick={() => setOpen(false)}
              className="block rounded px-3 py-2 text-sm text-ink hover:bg-sunk"
            >
              Mail checking
            </NavLink>
            <NavLink
              to="/team"
              onClick={() => setOpen(false)}
              className="block rounded px-3 py-2 text-sm text-ink hover:bg-sunk"
            >
              Team
            </NavLink>
            <button
              type="button"
              onClick={signOut}
              className="block w-full rounded px-3 py-2 text-left text-sm text-ink hover:bg-sunk"
            >
              Sign out
            </button>
          </div>
        </>
      )}
    </div>
  );
}


export default function Shell({ children }: { children: React.ReactNode }) {
  const { organisation } = useAuth();
  const { data: status } = useApi<SystemStatus>("/system/status", 60_000);
  const [menuOpen, setMenuOpen] = useState(false);
  const [collapsed, setCollapsed] = useRailCollapsed();
  const title = pageTitle(useLocation().pathname);


  return (
    <div className="flex h-full w-full overflow-hidden">
      {/* --- Rail: desktop only -------------------------------------------

          Fixed to the viewport height and never its own scroll container:
          eleven destinations have to fit, so the items are single-line rows
          rather than stacked icon-over-label tiles. Collapsed it is a 4rem
          icon strip; expanded it shows the labels and the health readout. */}
      <aside
        className={`hidden h-full shrink-0 flex-col bg-rail transition-[width] duration-200 md:flex ${
          collapsed ? "w-16" : "w-56"
        }`}
      >
        <div
          className={`flex h-14 shrink-0 items-center ${
            collapsed ? "justify-center px-2" : "gap-2.5 px-4"
          }`}
        >
          {/* The desk's own name, not the product's. A trader who has the
              app open all day knows what it is; what the corner has to
              confirm - especially for anyone who works across more than one
              desk - is whose books they are looking at. */}
          <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-brand text-sm font-bold text-white">
            {(organisation?.name ?? "Steel Desk").trim().charAt(0).toUpperCase()}
          </span>
          {!collapsed && (
            <span className="truncate text-sm font-semibold text-rail-ink-strong">
              {organisation?.name ?? "Steel Desk"}
            </span>
          )}
        </div>

        <nav className={`flex min-h-0 flex-1 flex-col gap-0.5 pb-2 ${collapsed ? "px-2" : "px-2.5"}`}>
          {RAIL_GROUPS.map((group, i) => (
            <div
              key={i}
              className={
                i > 0 ? "mt-1.5 flex flex-col gap-0.5 border-t border-white/8 pt-1.5" : "flex flex-col gap-0.5"
              }
            >
              {group.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  /* Collapsed, the label is gone - the native tooltip is the
                     only thing naming the destination, so it is not optional. */
                  title={collapsed ? item.label : undefined}
                  className={({ isActive }) =>
                    `group relative flex items-center rounded-lg py-1.5 text-[13px] font-medium transition-colors ${
                      collapsed ? "justify-center px-0" : "gap-2.5 px-2.5"
                    } ${
                      isActive
                        ? "bg-brand-soft/15 text-rail-ink-strong"
                        : "text-rail-ink hover:bg-rail-hover hover:text-rail-ink-strong"
                    }`
                  }
                >
                  {({ isActive }) => (
                    <>
                      {/* The active marker is a bar on the edge, not a fill:
                          it says "you are here" without competing with the
                          blue that means "this is an action". */}
                      <span
                        className={`absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-r-full bg-brand-soft transition-opacity ${
                          isActive ? "opacity-100" : "opacity-0"
                        }`}
                      />
                      <span className="relative shrink-0">
                        <item.icon className="size-[17px]" />
                      </span>
                      {!collapsed && (
                        <>
                          <span className="min-w-0 flex-1 truncate">{item.label}</span>
                        </>
                      )}
                    </>
                  )}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>

        {status && (
          <div
            className={`shrink-0 border-t border-white/8 py-2.5 ${collapsed ? "px-2" : "px-4"}`}
          >
            {/* Collapsed the labels go but the dots stay, laid out in a row -
                a red dot has to be visible whichever width the rail is at. */}
            {/* One line, and it answers the only question this corner was
                ever asked: is mail still coming in? The Gmail search string,
                the LLM key and the send policy are configuration - they
                belong on Settings, where they can be changed, not on every
                screen where they are read past. What cannot be found
                anywhere else is when the mailbox was last actually checked:
                a desk with no new enquiries needs to tell "nobody wrote"
                apart from "we stopped looking". */}
            <ul className={`flex ${collapsed ? "justify-center gap-1.5" : "flex-col gap-1.5"}`}>
              <li
                className="flex items-center gap-2 text-[11px] text-rail-ink"
                title={
                  status.last_polled_at
                    ? `Mail last checked ${new Date(status.last_polled_at).toLocaleString("en-IN")}` +
                      (status.poll_reason ? ` · ${status.poll_reason}` : "")
                    : status.poll_reason ?? "Mail has not been checked yet."
                }
              >
                <StatusDot
                  ok={status.email_source_available}
                  label={
                    status.last_polled_at
                      ? `Mail last checked ${ago(status.last_polled_at)}`
                      : "Mail has not been checked yet"
                  }
                />
                {!collapsed && (
                  <span className="truncate">
                    {status.last_polled_at
                      ? `Mail checked ${ago(status.last_polled_at)}`
                      : "Mail not checked yet"}
                  </span>
                )}
              </li>
            </ul>
          </div>
        )}

        <div className={`shrink-0 border-t border-white/8 py-1.5 ${collapsed ? "px-2" : "px-2.5"}`}>
          <button
            type="button"
            onClick={() => setCollapsed((v) => !v)}
            title={collapsed ? "Expand menu" : "Collapse menu"}
            aria-label={collapsed ? "Expand menu" : "Collapse menu"}
            aria-expanded={!collapsed}
            className={`flex w-full items-center rounded-lg py-1.5 text-[13px] font-medium text-rail-ink transition-colors hover:bg-rail-hover hover:text-rail-ink-strong ${
              collapsed ? "justify-center px-0" : "gap-2.5 px-2.5"
            }`}
          >
            <Icons.chevronLeft
              className={`size-[17px] shrink-0 transition-transform duration-200 ${
                collapsed ? "rotate-180" : ""
              }`}
            />
            {!collapsed && <span className="truncate">Collapse</span>}
          </button>
        </div>
      </aside>

      <div className="flex h-full min-w-0 flex-1 flex-col">
        {/* Matches the rail's 3.5rem masthead so the two line up across the
            seam, and sits outside the scroll region rather than relying on
            sticky - `main` is the only thing that scrolls now. */}
        <header
          data-print-hide
          className="z-20 flex h-14 shrink-0 items-center justify-between gap-3 border-b border-rule bg-surface px-4 md:px-5"
        >
          <div className="flex min-w-0 items-center gap-2">
            <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-brand text-xs font-bold text-white md:hidden">
              S
            </span>
            {/* The page's own title. The desk name moved to the rail, where
                it stays put; repeating it here would spend the header on a
                word that never changes. The pricing version went with it -
                it belongs on Pricing, where it can be acted on, not on every
                screen. The one case still worth interrupting for is pricing
                never having been set up, because nothing can be quoted until
                it is. */}
            <div className="flex min-w-0 items-baseline gap-2">
              <h1 className="truncate text-sm font-semibold text-ink">{title}</h1>
              {status?.pricing_version === null && (
                <NavLink
                  to="/pricing"
                  className="hidden text-[11px] text-attention hover:underline sm:inline"
                >
                  pricing not set up
                </NavLink>
              )}
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <NotificationBell />
            <ThemeToggle />
            <UserMenu />
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
          <nav className="grid shrink-0 grid-cols-3 gap-1 border-b border-rule bg-surface p-3 md:hidden">
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

        {/* The one scroll container in the app, which is what keeps the rail
            and the header fixed. Padded for the bottom bar on phones so the
            last row is never covered. */}
        <main className="min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden pb-16 md:pb-0">
          {children}
        </main>
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
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

export { Badge };
