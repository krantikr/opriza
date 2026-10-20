/* ---------------------------------------------------------------------------
   Data for the Oprisa desk: the shapes the /api/v1/app routes return, and one
   hook to read them.

   Every screen reads with `useData(path)`. After anything changes - an
   approval, a reminder, a chat answer - the shell bumps a version number and
   every open screen refetches, so what the agents did shows up at once.
   --------------------------------------------------------------------------- */

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import type { Card, Msg } from "../demo/engine/types";

export type Role = "owner" | "accounts" | "sales" | "purchase";

export interface Me {
  user: { id: number; name: string; email: string; role: string; desk_role: Role; can_approve: boolean };
  organisation: { id: number; name: string; slug: string } | null;
  business: null | {
    trade: string; city: string | null; language: string; tally_version: string; source: string; mock: boolean;
    as_of: string | null; now: string; last_sync_at: string | null; last_sync_status: string | null;
    last_sync_error: string | null; bank_balance: number;
  };
  brain: "rules" | "llm"; channel: string; team: { id: number; name: string; desk_role: Role }[];
}

export interface Task {
  id: number; agent: string; kind: string; title: string; detail: string | null; entity_type: string | null;
  entity_id: number | null; amount: number | null; priority: number; role: string; status: string; created_at: string;
  why: string[];
}

export interface Approval {
  id: number; agent: string; agent_label: string; action: string; title: string; reason: string; amount: number | null;
  status: string; requested_at: string; requested_by: string | null; decided_at: string | null; decided_by: string | null;
  note: string | null; details: Record<string, any>; payload: Record<string, any>;
}

export interface Week { week_start: string; opening: number; inflow: number; outflow: number; closing: number;
  in_top: { name: string; amount: number }[]; out_top: { name: string; amount: number }[] }

export interface AgentActivity { agent: string; label: string; last_run_at: string | null; last_status: string | null;
  runs_today: number; messages_today: number; open_tasks: number; waiting: number }

export interface Home {
  today: string; now: string;
  money_waiting: { open_quotes: number; open_quote_count: number; overdue: number; overdue_customers: number; idle_stock: number; promised_this_week: number };
  kpis: { sales_7d: number; sales_7d_change: number | null; sales_mtd: number; receivable: number; dso: number | null; stock_value: number; payables_7d: number; bank: number | null };
  cash: { weeks: Week[]; short: Week | null; floor: number };
  sales_series: { day: string; value: number }[]; collections_series: { day: string; value: number }[];
  inbox: Task[]; brief: ChatMsg | null; approvals_waiting: number; agents: AgentActivity[];
}

export type ChatMsg = Msg & { ts: string; ref: Record<string, any> | null };

export interface Thread { id: string; name: string; sub: string; letter: string; bg: string; fg: string; unread: number; last: ChatMsg | null }

export interface QuoteRow { id: number; number: string; party: string; party_id: number; status: string; total: number; margin: number;
  created_at: string; sent_at: string | null; opened_at: string | null; decided_at: string | null; valid_until: string | null; nudged_at: string | null }

export interface Sales {
  enquiries: { id: number; party: string | null; party_id: number | null; channel: string; text: string; received_at: string; status: string;
    quote: { id: number; number: string; status: string } | null }[];
  quotes: QuoteRow[];
  stats: { open_value: number; win_rate: number | null; won_value: number; quotes_30d: number; avg_minutes_to_quote: number | null };
}

export interface MessageRow { id: number; agent: string; purpose: string; channel: string; to: string | null; body: string; status: string; created_at: string; error: string | null; party?: string }

export interface QuoteDetail extends QuoteRow {
  freight: number; tax: number; subtotal: number; lost_reason: string | null;
  lines: { id: number; item_id: number; item: string; unit: string; qty: number; rate: number; last_rate: number | null; margin: number }[];
  enquiry: { text: string; channel: string; received_at: string; parsed: any } | null;
  messages: MessageRow[]; timeline: { at: string; type: string; source: string }[];
  links: { purpose: string; created_at: string; opened: string | null; responded: string | null; response: any }[];
}

export interface Due { party_id: number; name: string; area: string | null; grade: string | null; amount: number; overdue: number; bills: number;
  oldest: number; bucket: string; pay_day: number | null; last_message_at: string | null; phone: string | null }

export interface Collections {
  buckets: { key: string; label: string; amount: number; count: number }[];
  dues: Due[];
  promises: { id: number; party_id: number; party: string; amount: number; made_on: string; due_date: string; status: string; source: string; settled: number }[];
  calls: Task[];
}

export interface CustomerRow { party_id: number; name: string; area: string | null; contact: string | null; phone: string | null; grade: string;
  previous_grade: string | null; outstanding: number; overdue: number; sales_12m: number; trend: string; last_order_on: string | null;
  credit_limit: number | null; avg_days_late: number }

export interface CustomerDetail {
  party: { id: number; name: string; kind: string; contact: string | null; phone: string | null; email: string | null; gstin: string | null;
    city: string | null; area: string | null; credit_days: number; credit_limit: number | null; since: string | null };
  profile: null | { grade: string; previous_grade: string | null; avg_days_late: number; usual_pay_day: number; sales_12m: number; sales_90d: number;
    outstanding: number; overdue: number; oldest: number; last_order_on: string | null; gap: number | null; trend: string;
    suggested_limit: number | null; reasons: string[]; promises_made: number; promises_kept: number };
  bills: { id: number; ref: string; date: string; due: string; amount: number; pending: number; days_late: number; direction: string }[];
  vouchers: { type: string; number: string; date: string; amount: number }[];
  quotes: { id: number; number: string; status: string; total: number; created_at: string }[];
  promises: { id: number; amount: number; due_date: string; status: string }[];
  messages: MessageRow[];
  memories: { id: number; kind: string; content: string; valid_from: string; valid_to: string | null; source: string }[];
}

export interface StockItem { item_id: number; name: string; group: string; unit: string; status: string; stock: number; value: number; per_day: number;
  days_left: number | null; idle_days: number; last_sale_on: string | null; sold_28d: number; reorder_qty: number | null; rate: number }

export interface Stock {
  items: StockItem[];
  purchase_orders: { id: number; number: string; supplier: string; status: string; created_at: string; total: number;
    lines: { item: string; qty: number; unit: string; rate: number }[] }[];
  rfqs: { id: number; item: string; unit: string; qty: number; created_at: string; quotes: { supplier: string; rate: number; days: number; received_at: string }[] }[];
  totals: { value: number; idle: number; reorder: number };
}

export interface ItemDetail {
  item: { id: number; name: string; unit: string; group: string; gst: number; list: number; aliases: string[] };
  metrics: null | { status: string; stock: number; value: number; per_day: number; days_left: number | null; idle_days: number; sold_7d: number; sold_28d: number };
  prices: { week: string; sale?: number; purchase?: number; quote?: number; supplier_quote?: number }[];
  supplier_quotes: { supplier: string; rate: number; days: number; received_at: string }[];
}

export interface Cash { bank: number; bank_at: string | null; floor: number; weeks: Week[];
  payables: { id: number; party: string; ref: string; due: string; amount: number }[] }

export interface Reports { grades: Record<string, number>; sales_by_month: { month: string; value: number }[];
  receivable: { day: string; value: number }[]; overdue: { day: string; value: number }[];
  top_customers: { name: string; sales_12m: number; grade: string }[] }

export interface Rule { agent: string; key: string; label: string; kind: string; help: string; choices: string[]; value: any; default: any; updated_at: string | null }

export interface Agents {
  agents: AgentActivity[]; rules: Rule[];
  runs: { id: number; agent: string; trigger: string; ref: string | null; status: string; started_at: string; brain: string;
    llm_calls: number; tokens: number; cost_usd: number; error: string | null; outcome: any }[];
  postings: { id: number; kind: string; status: string; payload: any; created_at: string }[];
  brain: string; channel: string;
}

export type { Card, Msg };

/* ---------------------------------------------------------------------------
   Refreshing after changes
   --------------------------------------------------------------------------- */

export const VersionContext = createContext<{ version: number; bump: () => void }>({ version: 0, bump: () => {} });

export function useVersion() {
  return useContext(VersionContext);
}

/** GET a path, refetching when the desk changes or on a timer.
 *  Keeps the last good data while refetching, so screens never flash empty. */
export function useData<T>(path: string | null, pollMs?: number) {
  const { version } = useVersion();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const live = useRef(true);
  const reload = useCallback(() => setTick((n) => n + 1), []);

  useEffect(() => {
    live.current = true;
    if (!path) return;
    api
      .get<T>(path)
      .then((d) => {
        if (live.current) {
          setData(d);
          setError(null);
        }
      })
      .catch((e: Error) => live.current && setError(e.message));
    return () => {
      live.current = false;
    };
  }, [path, version, tick]);

  useEffect(() => {
    if (!pollMs || !path) return;
    const t = window.setInterval(reload, pollMs);
    return () => window.clearInterval(t);
  }, [pollMs, path, reload]);

  return { data, error, reload, loading: data === null && !error };
}

/* ---------------------------------------------------------------------------
   Formatting (same rules as the demo and the backend's app.kb.fmt)
   --------------------------------------------------------------------------- */

export { inr, money, qty } from "../demo/lib/format";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-10-19" or an ISO timestamp → "19 Oct". */
export function day(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return "—";
  return `${d} ${MONTHS[m - 1]}`;
}

/** An ISO timestamp → "10:42" in the business's time zone (IST). */
export function time(iso: string | null | undefined): string {
  if (!iso) return "";
  const t = new Date(iso);
  return t.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Kolkata" });
}

/** "19 Oct, 10:42". */
export function stamp(iso: string | null | undefined): string {
  if (!iso) return "—";
  return `${day(new Date(iso).toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" }))}, ${time(iso)}`;
}

/** Days between two ISO dates (b − a). */
export function daysBetween(a: string, b: string): number {
  return Math.round((Date.parse(b.slice(0, 10)) - Date.parse(a.slice(0, 10))) / 864e5);
}

export function rate(n: number, unit?: string): string {
  const v = n >= 100 ? `₹${Math.round(n).toLocaleString("en-IN")}` : `₹${n.toFixed(2)}`;
  return unit ? `${v}/${unit}` : v;
}

export const AGENT_NAMES: Record<string, string> = {
  sales: "Sales & Quote", collect: "Collections", stock: "Stock & Purchase", cash: "Cash", brief: "Business Manager",
  score: "Customer Score", ask: "Ask Oprisa",
};

export const STATUS_LABEL: Record<string, string> = {
  draft: "Draft", pending_approval: "Waiting for you", sent: "Sent", opened: "Opened", negotiating: "In talks",
  won: "Won", lost: "Lost", expired: "Expired", new: "New", quoted: "Quoted", waiting: "Waiting for you",
  needs_review: "Needs a person", open: "Open", kept: "Kept", part_kept: "Part kept", missed: "Missed",
  received: "Received", reorder: "Reorder", watch: "Watch", idle: "Idle", ok: "OK",
};
