import { PROBLEMS } from "../data/problems";
import { addDays, dayDate, money, qty, rate } from "../lib/format";
import { roundQty } from "../data/generate";
import { act, agent, buildQuote, chaseOrder, oldestLate, quoteActions, shortName } from "./core";
import type { Approval, Card, Customer, DemoState, Go, Msg, Thread, ThreadId, World } from "./types";

const META: Record<ThreadId, Pick<Thread, "name" | "sub" | "letter" | "bg" | "fg">> = {
  brief: { name: "Today's brief", sub: "Business manager", letter: "B", bg: "#8a2420", fg: "#ffffff" },
  sales: { name: "Sales & Quote", sub: "Rates and stock from Tally", letter: "Q", bg: "#2b5c8a", fg: "#ffffff" },
  collect: { name: "Collections", sub: "Bill-wise outstanding from Tally", letter: "C", bg: "#e8a33d", fg: "#3a1a05" },
  stock: { name: "Stock & Purchase", sub: "Stock summary from Tally", letter: "S", bg: "#17684a", fg: "#ffffff" },
  cash: { name: "Cash", sub: "Receivables, payables and bank", letter: "₹", bg: "#4e100e", fg: "#ffffff" },
  ask: { name: "Ask Oprisa", sub: "Answers from your Tally data", letter: "A", bg: "#231c18", fg: "#ffffff" },
  score: { name: "Customer Score", sub: "How each customer pays", letter: "G", bg: "#5a4a3e", fg: "#ffffff" },
};

const DEFAULT_ORDER: ThreadId[] = ["sales", "collect", "stock", "cash", "ask", "score"];

export const START_CLOCK = 10 * 60 + 15;

export function dueDraft(w: World, c: Customer): string {
  const amount = money(c.outstanding).replace("₹", "₹ ");
  return w.biz.language === "Hinglish"
    ? `Namaste ${c.contact} ji, ${amount} ke ${c.bills.length} bill pending hain. Link par payment date chun lijiye. Dhanyavaad.`
    : `Hello ${c.contact}, ${c.bills.length} bills totalling ${amount} are now due. Please pick a payment date on the link. Thank you.`;
}

export function dueCard(w: World, c: Customer): Card {
  const late = oldestLate(c);
  return {
    kind: "due",
    customerId: c.id,
    name: c.name,
    grade: c.grade,
    amount: c.outstanding,
    daysLate: late,
    bills: c.bills.length,
    habit: c.grade === "A" ? "Usually pays on time." : `Usually pays on day ${c.payDay}${c.grade === "C" ? ", faster after a call" : ""}.`,
    draft: dueDraft(w, c),
    language: w.biz.language,
  };
}

export function dueActions(c: Customer) {
  return [
    act("send-reminder", "Send reminder link", { customerId: c.id }, true),
    act("call", `Call ${c.contact}`, { customerId: c.id }),
    act("log-promise", "Log a promise to pay", { customerId: c.id }),
  ];
}

export function queueCard(w: World): Card {
  const list = chaseOrder(w).slice(0, 5);
  return {
    kind: "queue",
    total: w.kpi.overdue,
    count: w.kpi.overdueCount,
    rows: list.map((c, i) => {
      const late = oldestLate(c);
      const tone = late >= 15 ? "bad" : late > 0 ? "warn" : "info";
      return {
        name: c.name,
        amount: c.outstanding,
        tag: i === 2 ? "Promise today" : `${late}d late`,
        tone: i === 2 ? "info" : tone,
        hint: c.grade === "C" || c.grade === "D" ? "Call: pays after a call" : i === 2 ? "Check by 4 pm" : "Send statement link",
      };
    }),
  };
}

function briefTodos(s: { world: World; approvals: Approval[] }, problems: string[]): { text: string; go: Go }[] {
  const w = s.world;
  const top = chaseOrder(w)[0] as Customer;
  const p0 = w.products[0]!;
  const short = w.cash[2]!.outflow - w.cash[2]!.inflow;
  const items: Record<string, { text: string; go: Go }> = {
    quotes: { text: `Quote ready for ${w.customers[2]!.name}`, go: { to: "thread", id: "sales" } },
    approvals: { text: `${s.approvals.length} approvals waiting for you`, go: { to: "tab", tab: "approvals" } },
    collections: { text: `Call ${top.name}: ${money(top.outstanding)}, ${oldestLate(top)} day${oldestLate(top) === 1 ? "" : "s"} late`, go: { to: "thread", id: "collect" } },
    stock: { text: `Reorder ${shortName(p0)}: ${Math.round(p0.stock / p0.perDay)} days left`, go: { to: "thread", id: "stock" } },
    cash: { text: `Week 3 cash is ${money(short)} short`, go: { to: "thread", id: "cash" } },
    answers: { text: `${w.customers[1]!.name} hasn't bought in ${w.customers[1]!.lastBuyDays} days`, go: { to: "thread", id: "ask" } },
    risk: { text: `${w.customers[4]!.name} moved to grade C`, go: { to: "thread", id: "score" } },
  };
  const order = [...problems, ...["collections", "quotes", "stock", "approvals", "cash", "answers", "risk"].filter((x) => !problems.includes(x))];
  return order.map((k) => items[k]).filter((x): x is { text: string; go: Go } => !!x).slice(0, 3);
}

function makeApprovals(w: World): Approval[] {
  const c4 = w.customers[4]!;
  const p2 = w.products[2]!;
  const p0 = w.products[0]!;
  const s0 = w.suppliers[0]!;
  const suggest = roundQty(p0.perDay * 30, p0.unit);
  const poTotal = Math.max(w.limits.poLimit * 1.4, suggest * p0.lastBuys[0]!);
  const p5 = w.products[5]!;
  return [
    {
      id: "ap1",
      type: "Quote",
      who: `${w.team.sales[0]} · sales`,
      title: `${c4.name} · ${qty(roundQty((p2.qty[0] + p2.qty[1]) / 2, p2.unit), p2.unit)} ${shortName(p2)}`,
      detail: `${money(roundQty((p2.qty[0] + p2.qty[1]) / 2, p2.unit) * p2.rate * 0.985)} · margin 2.6%`,
      why: `Below your ${w.limits.marginFloor}% margin floor`,
      thread: "sales",
      after: `Quote link sent to ${c4.contact} at ${c4.name}.`,
      status: "waiting",
    },
    {
      id: "ap2",
      type: "Purchase order",
      who: `${w.team.purchase} · purchase`,
      title: `${s0.brand} · ${qty(suggest, p0.unit)} ${shortName(p0)}`,
      detail: `${money(poTotal)} · ${rate(p0.lastBuys[0]!, p0.unit)}`,
      why: `Above ${w.team.purchase}'s ${money(w.limits.poLimit)} limit`,
      thread: "stock",
      after: `PO posted in Tally and sent to ${s0.name}.`,
      status: "waiting",
    },
    {
      id: "ap3",
      type: "Credit limit",
      who: "Customer Score",
      title: `${c4.name} · lower credit limit`,
      detail: `${money(c4.outstanding * 2.4)} → ${money(c4.outstanding * 1.4)}`,
      why: `Paid ${c4.avgDelay} days late, 3 times in a row`,
      thread: "score",
      after: "Credit limit updated in Tally.",
      status: "waiting",
    },
    {
      id: "ap4",
      type: "Offer",
      who: "Stock agent",
      title: `${shortName(p5)} to 6 past buyers`,
      detail: `${rate(Math.round(p5.cost * 1.02), p5.unit)} · idle 100 days`,
      why: "Below list price",
      thread: "stock",
      after: "Offer link sent to 6 past buyers.",
      status: "waiting",
    },
  ];
}

/** The demo as it looks when the visitor first lands in it: a normal working
 *  morning, with the chats for their problems on top and already busy. */
export function createDemo(w: World): DemoState {
  const problems = w.biz.problems;
  const approvals = makeApprovals(w);
  const c2 = w.customers[2]!;
  const c3 = w.customers[3]!;
  const p0 = w.products[0]!;
  const p1 = w.products[1]!;
  const p5 = w.products[5]!;
  const sel = new Set(problems.map((id) => PROBLEMS.find((p) => p.id === id)?.thread).filter(Boolean) as ThreadId[]);

  /* --- brief ------------------------------------------------------------ */
  const brief: Msg[] = [
    agent(480, {
      text: `Good morning, ${w.firstName} ji. Your business in one minute.`,
      card: {
        kind: "brief",
        kpis: [
          { label: "Sold yesterday", value: money(w.kpi.salesYesterday), note: `▲ ${w.kpi.vsAverage}% vs average`, tone: "good" },
          { label: "Overdue", value: money(w.kpi.overdue), note: `${w.kpi.overdueCount} customers`, tone: "bad" },
          { label: "Coming in this week", value: money(w.kpi.inThisWeek), note: "expected" },
          { label: "To pay in 7 days", value: money(w.kpi.payables7), note: `${Math.min(4, w.kpi.payablesCount)} suppliers` },
        ],
        todo: briefTodos({ world: w, approvals }, problems),
      },
      actions: [act("go-tab", `Open ${approvals.length} approvals`, { tab: "approvals" }, true), act("go-thread", "Today's call list", { id: "collect" })],
    }),
  ];

  /* --- sales ------------------------------------------------------------ */
  const enqQty = roundQty((p0.qty[0] + p0.qty[1]) / 2, p0.unit);
  const enquiryText =
    w.biz.language === "Hinglish"
      ? `${c2.contact}: "${enqQty} ${p0.unit} ${shortName(p0)} chahiye, ${w.biz.city} site pe, agle hafte tak. 30 din credit."`
      : `${c2.contact}: "Need ${enqQty} ${p0.unit} ${shortName(p0)} at our ${w.biz.city} site by next week. 30 days credit."`;
  const q = buildQuote(w, "Q-1187", c2, p0, enqQty);
  const sales: Msg[] = [
    agent(598, {
      card: {
        kind: "enquiry",
        customer: c2.name,
        contact: c2.contact,
        channel: `Phone call · logged by ${w.team.sales[0]}`,
        text: enquiryText,
        fields: [
          ["Item", `${shortName(p0)} ✓ matched in Tally`],
          ["Quantity", qty(enqQty, p0.unit)],
          ["Deliver to", `${w.biz.city} site`],
          ["Credit", "30 days"],
          ["In stock", qty(p0.stock, p0.unit)],
        ],
      },
    }),
    agent(600, { card: q, actions: quoteActions(q), text: "Priced from the last rate, today's cost and how this customer pays." }),
    agent(605, {
      card: { kind: "alert", tone: "warn", title: `No reply · 2 days`, body: `${c3.name} hasn't opened quote Q-1179 (${money(roundQty((p1.qty[0] + p1.qty[1]) / 2, p1.unit) * p1.rate)}). They usually decide within a day.` },
      actions: [act("nudge", "Send a gentle nudge", { customerId: c3.id }, true), act("mark-lost", "Mark as lost")],
    }),
  ];

  /* --- collections ------------------------------------------------------ */
  const top = chaseOrder(w)[0] as Customer;
  const collect: Msg[] = [
    agent(450, { text: `${w.kpi.overdueCount} customers to follow up today.`, card: queueCard(w), actions: [act("next-due", `Start with ${top.name}`, undefined, true), act("send-all", "Send reminders to all due this week")] }),
    agent(452, { card: dueCard(w, top), actions: dueActions(top) }),
  ];

  /* --- stock ------------------------------------------------------------- */
  const daysLeft = Math.round(p0.stock / p0.perDay);
  const suggest = roundQty(p0.perDay * 30, p0.unit);
  const idleQty = roundQty((w.kpi.idleValue * 0.35) / p5.cost, p5.unit);
  const stock: Msg[] = [
    agent(600, {
      card: { kind: "reorder", product: p0.name, unit: p0.unit, stock: p0.stock, perDay: p0.perDay, daysLeft, suggest, lastBuys: p0.lastBuys },
      actions: [act("ask-rates", "Ask 3 suppliers for today's rate", undefined, true), act("order-last", "Order at last rate"), act("remind-tomorrow", "Remind me tomorrow")],
    }),
    agent(601, {
      card: {
        kind: "idle",
        product: p5.name,
        qty: idleQty,
        unit: p5.unit,
        value: idleQty * p5.cost,
        days: 100,
        cost: p5.cost,
        market: Math.round(p5.rate * 1.02),
        offer: Math.round(p5.cost * 1.02),
        buyers: [w.customers[3]!.name, w.customers[6]!.name, w.customers[8]!.name],
      },
      actions: [act("send-offer", "Send offer to 6 past buyers", undefined, true), act("offer-price", "Change the price")],
    }),
  ];

  /* --- cash ------------------------------------------------------------- */
  const shortfall = w.cash[2]!.outflow - w.cash[2]!.inflow;
  const s0 = w.suppliers[0]!;
  const cash: Msg[] = [
    agent(481, { text: "Cash for the next 4 weeks, from receivables, payables and your bank balance in Tally.", card: { kind: "cashweeks", weeks: w.cash } }),
    agent(482, {
      card: {
        kind: "alert",
        tone: "bad",
        title: `Week 3 is ${money(shortfall)} short`,
        body: `${s0.brand} payment of ${money(w.kpi.payables7 * 1.3)} falls due on ${dayDate(addDays(w.today, 15))}. 4 customers who usually pay early could bring in ${money(shortfall * 1.35)}.`,
      },
      actions: [act("ask-early", "Ask 4 to pay early", undefined, true), act("delay-payment", `Move ${s0.brand} payment by 5 days`)],
    }),
  ];

  /* --- ask --------------------------------------------------------------- */
  const ask: Msg[] = [
    agent(470, {
      text: `Ask me anything about ${w.biz.company}. I read your Tally, so every answer uses your own numbers. Type in English or Hinglish.`,
      chips: [
        act("ask", "Who owes me the most?", { q: "Who owes me the most?" }),
        act("ask", "Who stopped buying?", { q: "Who stopped buying?" }),
        act("ask", "Margin by month", { q: "Margin by month" }),
        act("ask", "Sales this week", { q: "Sales this week" }),
      ],
    }),
  ];

  /* --- score ------------------------------------------------------------- */
  const c4 = w.customers[4]!;
  const counts = { A: 0, B: 0, C: 0, D: 0 } as Record<string, number>;
  const scale = Math.round(w.kpi.overdueCount * 18);
  const shares = { A: 0.28, B: 0.45, C: 0.21, D: 0.06 };
  for (const g of ["A", "B", "C", "D"]) counts[g] = Math.round(scale * shares[g as keyof typeof shares]);
  const score: Msg[] = [
    agent(475, {
      card: {
        kind: "score",
        name: c4.name,
        grade: "C",
        from: "B",
        reasons: [
          { up: false, text: `Paid ${c4.avgDelay} days late on the last 3 bills (was 9)` },
          { up: false, text: "Missed 2 payment promises this quarter" },
          { up: true, text: `Still buys every month · ${money(c4.sales12m)} in 12 months` },
        ],
        suggestion: `Lower the credit limit to ${money(c4.outstanding * 1.4)} and ask 25% advance on new orders until they catch up.`,
      },
      actions: [act("score-apply", "Apply both", undefined, true), act("score-keep", "Keep current terms")],
    }),
    agent(476, {
      card: {
        kind: "kpis",
        title: `All ${scale} customers by grade`,
        kpis: [
          { label: "A · pays on time", value: String(counts.A), tone: "good" },
          { label: "B · a little late", value: String(counts.B) },
          { label: "C · often late", value: String(counts.C), tone: "warn" },
          { label: "D · risky", value: String(counts.D), tone: "bad" },
        ],
      },
    }),
  ];

  const order: ThreadId[] = ["brief", ...DEFAULT_ORDER.filter((t) => sel.has(t)), ...DEFAULT_ORDER.filter((t) => !sel.has(t))];

  const mk = (id: ThreadId, messages: Msg[], suggestions: string[]): Thread => ({
    id,
    ...META[id],
    messages,
    unread: id === "brief" ? 1 : sel.has(id) ? messages.length : 0,
    typing: false,
    suggestions,
  });

  const big = money(Math.round(w.kpi.overdue / w.kpi.overdueCount / 1e5) * 1e5 * 1.5);
  return {
    world: w,
    order,
    approvals,
    clock: START_CLOCK,
    seq: { quote: 1187, po: 873 },
    collectedToday: 0,
    wonToday: 0,
    queueIndex: 0,
    threads: {
      brief: mk("brief", brief, ["Why are sales up?", "What needs me today?", "Cash this week"]),
      sales: mk("sales", sales, [`Quote ${roundQty(p1.qty[0], p1.unit)} ${p1.unit} ${shortName(p1)} for ${w.customers[6]!.name}`, "Which quotes are still open?", "What's my win rate this month?"]),
      collect: mk("collect", collect, ["Who owes me the most?", "Promises due this week", `Statement for ${w.customers[1]!.name}`]),
      stock: mk("stock", stock, ["What should I reorder this week?", "Show idle stock", `Stock of ${shortName(p1)}`]),
      cash: mk("cash", cash, ["Cash position today", "Who can pay early?", "Payments due this week"]),
      ask: mk("ask", ask, [`Who owes me more than ${big}?`, "Top 5 customers", "Kaun se customer ne kharidna band kiya?"]),
      score: mk("score", score, ["Which customers are grade D?", `Score of ${w.customers[0]!.name}`, "Who improved this month?"]),
    },
  };
}
