import { marginAt, roundQty } from "../data/generate";
import type { Action, Card, Customer, DemoState, Msg, Product, QuoteLine, ThreadId, World } from "./types";

let counter = 0;
export const uid = (p = "m") => `${p}${Date.now().toString(36)}${(counter++).toString(36)}`;

export function agent(at: number, m: Omit<Msg, "id" | "from" | "at">): Msg {
  return { id: uid(), from: "agent", at, ...m };
}

export function me(at: number, text: string): Msg {
  return { id: uid(), from: "me", at, text };
}

export const act = (id: string, label: string, data?: Action["data"], primary = false): Action => ({ id, label, data, primary });

/** Appends messages to a thread and moves the demo clock on a minute. */
export function push(s: DemoState, id: ThreadId, msgs: Msg[], opts: { unread?: boolean } = {}): DemoState {
  const clock = s.clock + 1;
  const t = s.threads[id];
  const stamped = msgs.map((m) => ({ ...m, at: clock }));
  return {
    ...s,
    clock,
    threads: {
      ...s.threads,
      [id]: { ...t, messages: [...t.messages, ...stamped], unread: t.unread + (opts.unread ? stamped.length : 0) },
    },
  };
}

export function updateMsg(s: DemoState, id: ThreadId, msgId: string, fn: (m: Msg) => Msg): DemoState {
  const t = s.threads[id];
  return { ...s, threads: { ...s.threads, [id]: { ...t, messages: t.messages.map((m) => (m.id === msgId ? fn(m) : m)) } } };
}

export function findMsg(s: DemoState, id: ThreadId, msgId: string): Msg | undefined {
  return s.threads[id].messages.find((m) => m.id === msgId);
}

export function setTyping(s: DemoState, id: ThreadId, typing: boolean): DemoState {
  return { ...s, threads: { ...s.threads, [id]: { ...s.threads[id], typing } } };
}

/* ---------------------------------------------------------------------------
   Quotes
   --------------------------------------------------------------------------- */

export type QuoteCard = Extract<Card, { kind: "quote" }>;

export function quoteTotals(q: QuoteCard) {
  const sub = q.lines.reduce((a, l) => a + l.qty * l.rate, 0) + q.freight;
  const gst = Math.round(sub * 0.18);
  return { sub, gst, total: sub + gst };
}

/** Freight per unit: heavier, bulkier trades pay more per unit moved. */
function freightFor(p: Product, quantity: number): number {
  const perUnit = p.unit === "MT" ? 1200 : p.rate >= 5000 ? p.rate * 0.012 : p.rate * 0.02;
  return Math.round((perUnit * quantity) / 100) * 100;
}

export function buildQuote(w: World, no: string, c: Customer, p: Product, quantity: number, rateOverride?: number): QuoteCard {
  const q = roundQty(quantity, p.unit);
  const gradeAdj = c.grade === "A" ? -0.004 : c.grade === "C" ? 0.006 : c.grade === "D" ? 0.012 : 0;
  const raw = rateOverride ?? p.rate * (1 + gradeAdj);
  const r = raw >= 1000 ? Math.round(raw / 10) * 10 : Math.round(raw * 10) / 10;
  const margin = Math.round(marginAt(p, r) * 10) / 10;
  const lines: QuoteLine[] = [{ name: p.name, qty: q, unit: p.unit, rate: r }];
  return {
    kind: "quote",
    no,
    customer: c.name,
    grade: c.grade,
    lines,
    freight: freightFor(p, q),
    margin,
    inBand: margin >= w.limits.marginFloor,
    status: "ready",
    lastRate: Math.round(p.rate * (1 - 0.006)),
    terms: w.pack.terms,
  };
}

export function nextQuoteNo(s: DemoState): [string, DemoState] {
  const n = s.seq.quote + 1;
  return [`Q-${n}`, { ...s, seq: { ...s.seq, quote: n } }];
}

export function nextPoNo(s: DemoState): [string, DemoState] {
  const n = s.seq.po + 1;
  return [`PO-0${n}`, { ...s, seq: { ...s.seq, po: n } }];
}

/** Actions a quote card offers, depending on whether it fits the price band. */
export function quoteActions(q: QuoteCard): Action[] {
  return q.inBand
    ? [act("quote-share", "Share quote link with customer", undefined, true), act("quote-edit", "Change the price"), act("quote-hold", "Hold")]
    : [act("quote-approval", "Send for approval", undefined, true), act("quote-edit", "Change the price")];
}

/* ---------------------------------------------------------------------------
   Lookups
   --------------------------------------------------------------------------- */

export function customerById(w: World, id: string): Customer {
  return w.customers.find((c) => c.id === id) ?? (w.customers[0] as Customer);
}

/** Customers in the order Collections would chase them today. */
export function chaseOrder(w: World): Customer[] {
  return [...w.customers]
    .filter((c) => c.bills.some((b) => b.daysLate > 0))
    .sort((a, b) => b.outstanding * (1 + Math.max(...b.bills.map((x) => x.daysLate)) / 30) - a.outstanding * (1 + Math.max(...a.bills.map((x) => x.daysLate)) / 30));
}

export function oldestLate(c: Customer): number {
  return Math.max(0, ...c.bills.map((b) => b.daysLate));
}

export function shortName(p: Product): string {
  return p.name.replace(/\s*\(.*?\)\s*/g, " ").trim();
}
