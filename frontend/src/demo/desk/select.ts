import { chaseOrder, customerById, oldestLate, quoteTotals, shortName, type QuoteCard } from "../engine/core";
import { openQuoteValue } from "../engine/desk";
import type { Action, Approval, Customer, DemoState, Msg, PipeQuote, Product, Stage, ThreadId } from "../engine/types";

/* ---------------------------------------------------------------------------
   Read-only views of DemoState for the desk screens. Nothing here changes
   state; the screens call engine/desk.ts for that.
   --------------------------------------------------------------------------- */

const LIVE_STAGE: Record<QuoteCard["status"], Stage> = { ready: "draft", waiting: "draft", sent: "sent", held: "talks", won: "won" };

/** Quotes made in the Sales chat, as board cards. */
export function liveQuotes(s: DemoState): PipeQuote[] {
  const w = s.world;
  const out: PipeQuote[] = [];
  for (const m of s.threads.sales.messages) {
    if (m.card?.kind !== "quote") continue;
    const q = m.card;
    const c = w.customers.find((x) => x.name === q.customer) ?? w.customers[0]!;
    const line = q.lines[0]!;
    out.push({ no: q.no, customerId: c.id, product: line.name, qty: line.qty, unit: line.unit, value: quoteTotals(q).total, margin: q.margin, stage: LIVE_STAGE[q.status], ageH: Math.max(0, Math.round((s.clock - m.at) / 60)), rep: c.rep, msgId: m.id });
  }
  // A revised quote replaces the one before it for the same customer and item.
  const seen = new Set<string>();
  return out.reverse().filter((q) => {
    const k = `${q.customerId}|${q.product}`;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}

export function allQuotes(s: DemoState): PipeQuote[] {
  const live = liveQuotes(s);
  const liveNos = new Set(live.map((q) => q.no));
  return [...live, ...s.desk.pipeline.filter((q) => !liveNos.has(q.no))];
}

export function moneyWaiting(s: DemoState) {
  const w = s.world;
  const quotes = openQuoteValue(allQuotes(s));
  const collectable = chaseOrder(w)
    .filter((c) => c.grade !== "D")
    .reduce((a, c) => a + c.bills.filter((b) => b.daysLate > 0).reduce((x, b) => x + b.amount, 0), 0);
  return { quotes, collectable: Math.round(collectable * 0.55), idle: w.kpi.idleValue };
}

/* --- inbox ------------------------------------------------------------------ */

export type InboxItem =
  | { key: string; kind: "approval"; group: "Approvals"; approval: Approval; amount: number }
  | { key: string; kind: "msg"; group: "Waiting for your tap" | "Replies"; thread: ThreadId; msg: Msg; actions: Action[] };

const isNav = (a: Action) => a.id.startsWith("go-") || a.id.startsWith("view-");

/** Everything that needs a person: approvals first, then any agent card in
 *  any chat still waiting for a tap. */
export function inboxItems(s: DemoState): InboxItem[] {
  const out: InboxItem[] = [];
  for (const a of s.approvals) {
    if (a.status !== "waiting") continue;
    const m = /₹[\d.,]+\s*(Cr|L)?/.exec(a.detail);
    const amount = m ? parseFloat(m[0].replace(/[₹,]/g, "")) * (m[1] === "Cr" ? 1e7 : m[1] === "L" ? 1e5 : 1) : 0;
    out.push({ key: `a-${a.id}`, kind: "approval", group: "Approvals", approval: a, amount });
  }
  for (const id of s.order) {
    if (id === "brief" || id === "ask") continue;
    const msgs = s.threads[id].messages;
    msgs.forEach((m, i) => {
      if (m.from !== "agent" || m.chosen || !m.actions?.length) return;
      const actions = m.actions.filter((a) => !isNav(a));
      if (!actions.length) return;
      // A quote waiting for approval is already listed under Approvals.
      if (m.card?.kind === "quote" && m.card.status !== "ready") return;
      if (m.card?.kind === "po") return;
      const isReply = /replied|opened|wants|agreed/.test(m.text ?? "") || i > 3;
      out.push({ key: `m-${m.id}`, kind: "msg", group: isReply ? "Replies" : "Waiting for your tap", thread: id, msg: m, actions });
    });
  }
  return out;
}

export function inboxTitle(s: DemoState, it: InboxItem): { title: string; sub: string } {
  if (it.kind === "approval") return { title: it.approval.title, sub: `${it.approval.type} · ${it.approval.detail}` };
  const c = it.msg.card;
  const t = s.threads[it.thread];
  if (c?.kind === "quote") return { title: `Quote ${c.no} for ${c.customer}`, sub: `${t.name} · ready to share` };
  if (c?.kind === "due") return { title: `${c.name} · ${c.daysLate} day${c.daysLate === 1 ? "" : "s"} late`, sub: `${t.name} · reminder ready` };
  if (c?.kind === "queue") return { title: `${c.count} customers to follow up`, sub: `${t.name} · today's list` };
  if (c?.kind === "reorder") return { title: `Reorder ${c.product.replace(/\s*\(.*?\)\s*/g, " ").trim()}`, sub: `${t.name} · ${c.daysLeft} days left` };
  if (c?.kind === "idle") return { title: `Idle stock offer`, sub: `${t.name} · ${c.product}` };
  if (c?.kind === "alert") return { title: c.title, sub: t.name };
  if (c?.kind === "score") return { title: `${c.name} moved to grade ${c.grade}`, sub: t.name };
  if (c?.kind === "rates") return { title: `Supplier rates in`, sub: `${t.name} · ${c.product}` };
  if (c?.kind === "won") return { title: `Order won · ${c.customer}`, sub: t.name };
  return { title: (it.msg.text ?? "").replace(/\*\*/g, "").slice(0, 90), sub: t.name };
}

/* --- collections ------------------------------------------------------------- */

export const BUCKETS = [
  { key: "b1", label: "1–7 days", min: 1, max: 7 },
  { key: "b2", label: "8–15 days", min: 8, max: 15 },
  { key: "b3", label: "16–30 days", min: 16, max: 30 },
  { key: "b4", label: "30+ days", min: 31, max: 9999 },
] as const;

export type BucketKey = (typeof BUCKETS)[number]["key"];

export function bucketOf(c: Customer): BucketKey | null {
  const d = oldestLate(c);
  if (d <= 0) return null;
  return BUCKETS.find((b) => d >= b.min && d <= b.max)!.key;
}

export function ageing(s: DemoState) {
  return BUCKETS.map((b) => {
    let amount = 0;
    let count = 0;
    for (const c of s.world.customers) {
      const late = c.bills.filter((x) => x.daysLate >= b.min && x.daysLate <= b.max);
      if (late.length) count++;
      amount += late.reduce((a, x) => a + x.amount, 0);
    }
    return { ...b, amount, count };
  });
}

/** What to say on the call, from how the customer usually pays. */
export function callScript(s: DemoState, c: Customer): string {
  const hi = s.world.biz.language === "Hinglish";
  const promise = s.desk.promises.find((p) => p.customerId === c.id);
  if (promise?.status === "missed") return hi ? `"${promise.date} ka promise miss hua. Aaj kitna bhej sakte hain?"` : `"You'd promised ${promise.date}. How much can you send today?"`;
  if (c.grade === "C" || c.grade === "D") return hi ? `"${c.bills.length} bill pending hain. Aaj aadha bhej dijiye, baaki is hafte."` : `"${c.bills.length} bills are pending. Can you clear half today and the rest this week?"`;
  return hi ? `"Statement bhej diya hai — payment date link par chun lijiye."` : `"I've sent the statement — please pick a payment date on the link."`;
}

export function callWhy(c: Customer): string {
  if (c.grade === "A") return "Pays on time — a reminder is enough";
  if (c.grade === "B") return `Usually pays on day ${c.payDay}`;
  if (c.grade === "C") return `Pays on day ${c.payDay}, faster after a call`;
  return `Risky — ${c.promisesKept} of ${c.promisesMade} promises kept`;
}

/* --- stock --------------------------------------------------------------------- */

export function stockRows(s: DemoState) {
  return s.world.products.map((p: Product, i) => {
    const days = Math.round(p.stock / p.perDay);
    const status: "reorder" | "watch" | "ok" | "idle" = i === 5 ? "idle" : days < s.desk.rules.reorderDays ? "reorder" : days < 20 ? "watch" : "ok";
    return { p, i, days, status, value: p.stock * p.cost, short: shortName(p) };
  });
}

/* --- customers --------------------------------------------------------------- */

export function customerQuotes(s: DemoState, id: string) {
  return allQuotes(s).filter((q) => q.customerId === id);
}

export function trendOf(c: Customer): "up" | "flat" | "down" {
  if (c.lastBuyDays > 30) return "down";
  return c.grade === "A" || (c.grade === "B" && c.lastBuyDays < 10) ? "up" : "flat";
}

export { chaseOrder, customerById, oldestLate };
