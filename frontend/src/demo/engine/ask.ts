import { roundQty } from "../data/generate";
import { dayDate, addDays, money, pct, qty, rate } from "../lib/format";
import { act, agent, buildQuote, chaseOrder, me, nextQuoteNo, oldestLate, push, quoteActions, quoteTotals, shortName } from "./core";
import type { Action, Card, Customer, DemoState, Msg, Outcome, Product, ThreadId, World } from "./types";

/* ---------------------------------------------------------------------------
   Understanding the question
   --------------------------------------------------------------------------- */

const has = (t: string, words: string[]) => words.some((w) => t.includes(w));

/** Finds a product the visitor named, by alias or by any distinctive word. */
export function findProduct(w: World, text: string): Product | undefined {
  const t = text.toLowerCase();
  // Matches at the start of a word, so "putty" finds "putty" but "53" doesn't
  // find "530"; short words must also end there, longer ones may run on ("waterproofing").
  const has = (word: string) => {
    const esc = word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return new RegExp(`(^|[^a-z0-9])${esc}${word.length <= 3 ? "($|[^a-z0-9])" : ""}`).test(t);
  };
  let best: { p: Product; score: number } | undefined;
  for (const p of w.products) {
    // Saying the whole name settles it ("PPC cement", "Wall putty 40kg").
    let score = t.includes(p.name.toLowerCase()) ? 10 : 0;
    for (const alias of p.alias) {
      const a = alias.toLowerCase();
      if (!has(a)) continue;
      // A word another product's name also uses ("cement" in "PPC cement") only
      // breaks ties; a word only this product has decides.
      const shared = w.products.some((o) => o !== p && o.name.toLowerCase().includes(a));
      score += shared ? 1 : a.length > 3 ? 3 : 2;
    }
    for (const word of p.name.toLowerCase().split(/[\s×()/,]+/)) if (word.length > 3 && has(word)) score += 1;
    if (score > 0 && (!best || score > best.score)) best = { p, score };
  }
  return best?.p;
}

/** Finds a customer named in the text by their distinctive name. */
export function findCustomer(w: World, text: string): Customer | undefined {
  const t = text.toLowerCase();
  const full = w.customers.find((c) => t.includes(c.name.toLowerCase()));
  if (full) return full;
  return w.customers.find((c) => {
    const stem = c.name.toLowerCase().split(" ").slice(0, -1).join(" ");
    return stem.length > 2 && new RegExp(`\\b${stem}\\b`).test(t);
  });
}

/** "120 MT", "2,000 bags", "50" → 120 / 2000 / 50. */
export function findQty(text: string): number | undefined {
  const m = text.replace(/,/g, "").match(/(\d+(?:\.\d+)?)\s*(mt|ton|tonne|tons|bags?|pcs?|pieces?|coils?|m\b|meters?|metres?|kg|boxes?|box|rolls?|barrels?|cans?|sets?|lengths?|packs?|bottles?|pairs?|pkts?|kits?|buckets?)?/i);
  if (!m) return undefined;
  const n = Number(m[1]);
  // A number followed by "mm" or "w" is a size, not a quantity.
  const after = text.slice((m.index ?? 0) + m[0].length, (m.index ?? 0) + m[0].length + 3).toLowerCase();
  if (/^(mm|w\b|a\b|hp|"|sq)/.test(after.trim()) && !m[2]) return undefined;
  return n > 0 ? n : undefined;
}

/** "more than ₹50 lakh", "above 2 crore", "> 40L" → rupees. */
export function findAmount(text: string): number | undefined {
  const m = text.toLowerCase().replace(/,/g, "").match(/(\d+(?:\.\d+)?)\s*(cr|crore|crores|l|lakh|lakhs|lac|k|thousand)?\b/);
  if (!m || !m[2]) return undefined;
  const n = Number(m[1]);
  const unit = m[2];
  if (unit.startsWith("cr")) return n * 1e7;
  if (unit === "l" || unit.startsWith("la")) return n * 1e5;
  return n * 1e3;
}

type Intent =
  | "greet" | "help" | "quote" | "customer" | "product" | "overdue" | "inactive" | "top" | "margin"
  | "idle" | "reorder" | "sales" | "cash" | "payables" | "grade" | "promises" | "winrate" | "openquotes" | "thanks" | "today" | "unknown";

export function detectIntent(w: World, raw: string): Intent {
  const t = raw.toLowerCase().trim();
  if (/^(hi|hello|hey|namaste|namaskar|good morning|gm)\b/.test(t) && t.length < 30) return "greet";
  if (/^(thanks|thank you|thx|ok thanks|great|dhanyavaad|shukriya)/.test(t)) return "thanks";
  if (has(t, ["help", "what can you", "kya kar sakte", "how does this work", "what do you do"])) return "help";
  if (has(t, ["win rate", "conversion", "how many quotes"])) return "winrate";
  if (has(t, ["open quote", "quotes are still open", "pending quote", "quotes open", "still open"])) return "openquotes";
  const product = findProduct(w, t);
  if (has(t, ["quote", "quotation", "bhav", "bhaav", "chahiye", "need ", "enquiry", "inquiry", "price for", "rate for"]) && (product || findQty(t)))
    return "quote";
  if (has(t, ["grade", "score", "risky", "credit", "improved"])) return findCustomer(w, t) ? "customer" : "grade";
  if (has(t, ["promise"])) return "promises";
  if (has(t, ["stopped", "not bought", "inactive", "band kiya", "nahi khareed", "haven't bought", "not ordered", "lost customer"])) return "inactive";
  if (findCustomer(w, t)) return "customer";
  if (has(t, ["owe", "overdue", "outstanding", "baaki", "baki", "udhaar", "udhar", "receivable", "collect", "late pay", "pending payment", "dues"])) return "overdue";
  if (has(t, ["top", "best customer", "biggest", "largest customer"])) return "top";
  if (has(t, ["margin", "profit", "munafa", "gross"])) return "margin";
  if (has(t, ["idle", "dead", "slow", "not selling", "pada hai", "non-moving", "non moving"])) return "idle";
  if (has(t, ["reorder", "running out", "stock-out", "stockout", "khatam", "what should i buy", "purchase plan"])) return "reorder";
  if (product && has(t, ["stock", "maal", "how much", "inventory", "available"])) return "product";
  if (has(t, ["stock", "maal", "inventory", "godown"])) return product ? "product" : "reorder";
  if (has(t, ["cash", "bank", "paisa", "funds", "liquidity", "early"])) return "cash";
  if (has(t, ["payable", "supplier", "pay this week", "payments due", "to pay", "creditors", "dena hai"])) return "payables";
  if (has(t, ["sales", "sold", "bikri", "becha", "revenue", "turnover", "why are sales"])) return "sales";
  if (has(t, ["today", "needs me", "summary", "brief", "aaj"])) return "today";
  if (product) return "product";
  return "unknown";
}

/* ---------------------------------------------------------------------------
   Answering
   --------------------------------------------------------------------------- */

type Reply = { text?: string; card?: Card; actions?: Action[]; chips?: Action[] };

const chip = (q: string) => act("ask", q, { q });

function overdueReply(w: World, text: string): Reply {
  const min = findAmount(text);
  const list = chaseOrder(w)
    .filter((c) => (min ? c.outstanding >= min : true))
    .sort((a, b) => b.outstanding - a.outstanding)
    .slice(0, 6);
  if (!list.length) return { text: `Nobody owes you more than ${money(min ?? 0)} right now. The largest balance is ${money(chaseOrder(w)[0]!.outstanding)}.` };
  const total = list.reduce((a, c) => a + c.outstanding, 0);
  return {
    text: min ? `**${list.length} customers** owe more than ${money(min)}, ${money(total)} in total:` : `Your biggest balances, ${money(w.kpi.overdue)} overdue across ${w.kpi.overdueCount} customers:`,
    card: {
      kind: "table",
      cols: ["Customer", "Owes", "Late"],
      align: ["l", "r", "r"],
      rows: list.map((c) => [c.name, money(c.outstanding), `${oldestLate(c)} d`]),
    },
    actions: [act("go-thread", "Open today's call list", { id: "collect" }, true), act("send-all", "Send reminders to all of them")],
  };
}

function inactiveReply(w: World): Reply {
  const list = w.customers.filter((c) => c.lastBuyDays > 30);
  return {
    text: `**${list.length} regular customers** haven't bought in over 30 days:`,
    card: {
      kind: "table",
      cols: ["Customer", "Last order", "12-month sales"],
      align: ["l", "r", "r"],
      rows: list.map((c) => [c.name, `${c.lastBuyDays} days ago`, money(c.sales12m)]),
      footnote: "Both used to order every 2 to 3 weeks.",
    },
    actions: [act("winback", "Send them today's rates", undefined, true), act("go-thread", "Add to sales follow-ups", { id: "sales" })],
  };
}

function topReply(w: World): Reply {
  const list = [...w.customers].sort((a, b) => b.sales12m - a.sales12m).slice(0, 5);
  const share = Math.round((list.reduce((a, c) => a + c.sales12m, 0) / (w.kpi.salesMtd * 12 / 1.15)) * 100);
  return {
    text: `Your top 5 customers made about **${share}%** of sales in the last 12 months.`,
    card: {
      kind: "table",
      cols: ["Customer", "12-month sales", "Grade"],
      align: ["l", "r", "r"],
      rows: list.map((c) => [c.name, money(c.sales12m), c.grade]),
    },
  };
}

function marginReply(w: World): Reply {
  const m = w.margins;
  const last = m[m.length - 1]!;
  const first = m[0]!;
  const p0 = w.products[0]!;
  return {
    text: `Gross margin was **${pct(last.value)}** in ${last.label}, down from ${pct(first.value)} in ${first.label}.`,
    card: {
      kind: "bars",
      title: "Gross margin by month",
      unit: "%",
      bars: m.map((x) => ({ label: x.label, value: x.value, display: x.value.toFixed(1) })),
      highlight: m.length - 1,
      footnote: `Main reason: freight on ${shortName(p0)} went up and prices didn't follow.`,
    },
    chips: [chip("Margin by customer"), chip("Which items have the lowest margin?")],
  };
}

function idleReply(w: World): Reply {
  const items = w.products.slice(3);
  return {
    text: `**${money(w.kpi.idleValue)}** of stock hasn't sold in 60+ days. The biggest items:`,
    card: {
      kind: "table",
      cols: ["Item", "Stock", "Idle"],
      align: ["l", "r", "r"],
      rows: items.map((p, i) => [shortName(p), qty(roundQty(p.stock * 0.4, p.unit), p.unit), `${[64, 82, 100][i] ?? 70} d`]),
    },
    actions: [act("go-thread", "Plan to clear it", { id: "stock" }, true)],
  };
}

function reorderReply(w: World): Reply {
  return {
    text: "Days of stock left on your fastest-moving items, from Tally sales:",
    card: {
      kind: "table",
      cols: ["Item", "Stock", "Days left"],
      align: ["l", "r", "r"],
      rows: w.products.slice(0, 4).map((p) => [shortName(p), qty(p.stock, p.unit), `${Math.round(p.stock / p.perDay)} d`]),
      footnote: `Reorder ${shortName(w.products[0]!)} this week. Delivery takes 4 to 8 days.`,
    },
    actions: [act("go-thread", "Open the reorder", { id: "stock" }, true)],
  };
}

function productReply(p: Product): Reply {
  const days = Math.round(p.stock / p.perDay);
  return {
    text: `**${p.name}**`,
    card: {
      kind: "kpis",
      kpis: [
        { label: "In stock", value: qty(p.stock, p.unit) },
        { label: "Sells per day", value: qty(p.perDay, p.unit) },
        { label: "Days left", value: `${days} d`, tone: days < 12 ? "bad" : days < 20 ? "warn" : "good" },
        { label: "Selling rate", value: rate(p.rate, p.unit) },
        { label: "Your cost", value: rate(p.cost, p.unit) },
        { label: "Margin", value: pct(((p.rate - p.cost) / p.rate) * 100) },
      ],
    },
    chips: [chip(`Quote ${roundQty(p.qty[0], p.unit)} ${p.unit} ${shortName(p)}`), chip("What should I reorder this week?")],
  };
}

function salesReply(w: World): Reply {
  const total = w.sales7.reduce((a, d) => a + d.value, 0);
  return {
    text: `**${money(total)}** sold in the last 7 days. Yesterday was ${w.kpi.vsAverage}% above your daily average.`,
    card: {
      kind: "bars",
      title: "Sales, last 7 days",
      bars: w.sales7.map((d) => ({ label: d.label, value: d.value, display: money(d.value).replace("₹", "") })),
      highlight: w.sales7.length - 1,
      footnote: `Month to date: ${money(w.kpi.salesMtd)}, up ${w.kpi.mtdChange}% on last month.`,
    },
    chips: [chip("Top 5 customers"), chip("Margin by month")],
  };
}

function cashReply(w: World): Reply {
  return {
    text: "Cash for the next 4 weeks. Week 3 runs short because of a large supplier payment.",
    card: { kind: "cashweeks", weeks: w.cash },
    actions: [act("ask-early", "Ask customers to pay early", undefined, true), act("go-thread", "Open the cash chat", { id: "cash" })],
  };
}

function payablesReply(w: World): Reply {
  return {
    text: `You owe **${money(w.kpi.payables30)}** to ${w.kpi.payablesCount} suppliers in the next 30 days. Due soonest:`,
    card: {
      kind: "table",
      cols: ["Supplier", "Amount", "Due"],
      align: ["l", "r", "r"],
      rows: w.suppliers.map((s, i) => [s.name, money(w.kpi.payables7 * [1.3, 0.6, 0.45, 0.3][i]!), dayDate(addDays(w.today, [15, 4, 9, 12][i]!))]),
    },
  };
}

function gradeReply(w: World, text: string): Reply {
  const wantD = /\bd\b|risky/.test(text.toLowerCase());
  const list = w.customers.filter((c) => (wantD ? c.grade === "D" : c.grade === "C" || c.grade === "D"));
  return {
    text: wantD ? `**${list.length} customer** is grade D:` : `Customers to watch (grade C or D):`,
    card: {
      kind: "table",
      cols: ["Customer", "Grade", "Avg delay"],
      align: ["l", "r", "r"],
      rows: list.map((c) => [c.name, c.grade, `${c.avgDelay} d`]),
      footnote: "Grades update every Monday from how each customer actually pays.",
    },
  };
}

function customerReply(c: Customer): Reply {
  return {
    text: `**${c.name}** · ${c.contact} · customer since ${c.since}`,
    card: {
      kind: "kpis",
      kpis: [
        { label: "Owes you", value: money(c.outstanding), tone: oldestLate(c) > 10 ? "bad" : undefined },
        { label: "Grade", value: c.grade, tone: c.grade === "A" ? "good" : c.grade === "B" ? undefined : "warn" },
        { label: "Average delay", value: `${c.avgDelay} days` },
        { label: "12-month sales", value: money(c.sales12m) },
        { label: "Last order", value: `${c.lastBuyDays} days ago` },
        { label: "Promises kept", value: `${c.promisesKept} of ${c.promisesMade}` },
      ],
    },
    actions: [act("send-reminder", "Send statement link", { customerId: c.id }, true), act("view-statement", "See their statement", { customerId: c.id })],
  };
}

function promisesReply(w: World): Reply {
  const list = w.customers.slice(2, 6);
  return {
    text: "Payment promises due this week:",
    card: {
      kind: "table",
      cols: ["Customer", "Amount", "Promised for"],
      align: ["l", "r", "r"],
      rows: list.map((c, i) => [c.name, money(c.outstanding * 0.5), dayDate(addDays(w.today, i + 1))]),
      footnote: "I remind each customer the day before, and tell you if a promise is missed.",
    },
  };
}

function helpReply(w: World): Reply {
  return {
    text: `I run the desk work for ${w.biz.company} from your Tally: quotes, collections, stock, cash and customer credit. Tap any button, or ask me things like:`,
    chips: [chip("Who owes me the most?"), chip(`Quote ${roundQty(w.products[0]!.qty[0], w.products[0]!.unit)} ${w.products[0]!.unit} ${shortName(w.products[0]!)}`), chip("What should I reorder?"), chip("Cash this week")],
  };
}

function todayReply(w: World, s: DemoState): Reply {
  const waiting = s.approvals.filter((a) => a.status === "waiting").length;
  return {
    text: "Here's what needs you today:",
    card: {
      kind: "table",
      cols: ["", "What"],
      align: ["l", "l"],
      rows: [
        ["1", `Call ${chaseOrder(w)[0]!.name} (${money(chaseOrder(w)[0]!.outstanding)})`],
        ["2", `Reorder ${shortName(w.products[0]!)}`],
        ["3", `${waiting} approvals waiting`],
      ],
    },
    actions: [act("go-tab", "Open approvals", { tab: "approvals" }, true)],
  };
}

/** Builds the agent's answer to a typed question. Quotes are created as real
 *  quote cards with working buttons, everything else is read-only. */
export function answer(s: DemoState, text: string): { state: DemoState; msgs: Msg[] } {
  const w = s.world;
  const intent = detectIntent(w, text);
  let st = s;
  let reply: Reply;

  switch (intent) {
    case "greet":
      reply = { text: `Namaste ${w.firstName} ji. What would you like to know?`, chips: [chip("What needs me today?"), chip("Who owes me the most?"), chip("Sales this week")] };
      break;
    case "thanks":
      reply = { text: "Anytime. I'll keep an eye on things and message you here." };
      break;
    case "help":
      reply = helpReply(w);
      break;
    case "quote": {
      const p = findProduct(w, text) ?? (w.products[0] as Product);
      const c = findCustomer(w, text) ?? (w.customers[6] as Customer);
      const q = findQty(text) ?? roundQty((p.qty[0] + p.qty[1]) / 2, p.unit);
      const [no, next] = nextQuoteNo(st);
      st = next;
      const card = buildQuote(w, no, c, p, q);
      const t = quoteTotals(card);
      reply = {
        text: card.inBand
          ? `Quote for ${c.name}: ${qty(card.lines[0]!.qty, p.unit)} ${shortName(p)}, ${money(t.total)} with GST. ${p.stock >= card.lines[0]!.qty ? "In stock." : `Only ${qty(p.stock, p.unit)} in stock, the rest in 5 days.`}`
          : `This one is below your ${w.limits.marginFloor}% margin floor, so it needs your approval before it goes out.`,
        card,
        actions: quoteActions(card),
      };
      break;
    }
    case "customer":
      reply = customerReply(findCustomer(w, text) as Customer);
      break;
    case "product":
      reply = productReply(findProduct(w, text) as Product);
      break;
    case "overdue":
      reply = overdueReply(w, text);
      break;
    case "inactive":
      reply = inactiveReply(w);
      break;
    case "top":
      reply = topReply(w);
      break;
    case "margin":
      reply = marginReply(w);
      break;
    case "idle":
      reply = idleReply(w);
      break;
    case "reorder":
      reply = reorderReply(w);
      break;
    case "sales":
      reply = salesReply(w);
      break;
    case "cash":
      reply = cashReply(w);
      break;
    case "payables":
      reply = payablesReply(w);
      break;
    case "grade":
      reply = gradeReply(w, text);
      break;
    case "promises":
      reply = promisesReply(w);
      break;
    case "winrate":
      reply = {
        text: `This month: **${142 + s.seq.quote - 1187} quotes**, **${34 + (s.wonToday > 0 ? 1 : 0)} won** (24%), average quote time **7 minutes**.`,
        card: { kind: "kpis", kpis: [{ label: "Quotes", value: String(142 + s.seq.quote - 1187) }, { label: "Won", value: String(34 + (s.wonToday > 0 ? 1 : 0)), tone: "good" }, { label: "Lost on price", value: "11", tone: "warn" }] },
      };
      break;
    case "openquotes":
      reply = {
        text: "Quotes waiting for the customer:",
        card: {
          kind: "table",
          cols: ["Quote", "Customer", "Value"],
          align: ["l", "l", "r"],
          rows: w.customers.slice(2, 6).map((c, i) => [`Q-${1179 + i * 2}`, c.name, money(c.outstanding * 0.8)]),
          footnote: "I nudge each one after 2 days without a reply.",
        },
      };
      break;
    case "today":
      reply = todayReply(w, s);
      break;
    default:
      reply = {
        text: "I couldn't match that to your data. I can answer questions about customers, dues, stock, sales, margin and cash. Try one of these:",
        chips: [chip("Who owes me the most?"), chip("Show idle stock"), chip("Margin by month"), chip(`Quote ${roundQty(w.products[1]!.qty[0], w.products[1]!.unit)} ${w.products[1]!.unit} ${shortName(w.products[1]!)}`)],
      };
  }

  return { state: st, msgs: [agent(st.clock, reply)] };
}

/** A typed question: echo it now, answer after a short "typing…". */
export function ask(_s: DemoState, thread: ThreadId, text: string): Outcome {
  const clean = text.trim();
  return {
    now: (s) => push(s, thread, [me(s.clock, clean)]),
    later: [
      {
        delay: 700 + Math.min(900, clean.length * 12),
        thread,
        run: (s) => {
          const { state, msgs } = answer(s, clean);
          return push(state, thread, msgs);
        },
      },
    ],
  };
}
