import { roundQty } from "../data/generate";
import { addDays, dayDate, inr, money, qty, rate } from "../lib/format";
import { ask } from "./ask";
import {
  act,
  agent,
  buildQuote,
  chaseOrder,
  customerById,
  findMsg,
  me,
  nextPoNo,
  nextQuoteNo,
  push,
  quoteActions,
  quoteTotals,
  shortName,
  updateMsg,
  type QuoteCard,
} from "./core";
import { dueActions, dueCard } from "./seed";
import type { Action, Approval, Card, DemoState, Msg, Outcome, Tab, ThreadId } from "./types";

type Step = NonNullable<Outcome["later"]>[number];

/** One agent reply, landing after `delay` ms of "typing…". */
function say(thread: ThreadId, delay: number, build: (s: DemoState) => Msg[] | [DemoState, Msg[]]): Step {
  return {
    delay,
    thread,
    run: (s) => {
      const out = build(s);
      const [st, msgs] = Array.isArray(out) && out.length === 2 && !("id" in (out[0] as object)) ? (out as [DemoState, Msg[]]) : [s, out as Msg[]];
      return msgs.length ? push(st, thread, msgs, { unread: true }) : st;
    },
  };
}

/** Marks the tapped button as chosen and echoes it as the visitor's reply,
 *  the way a quick reply reads in a chat. */
function chooseAndEcho(thread: ThreadId, msgId: string, label: string, echo = true) {
  return (s: DemoState) => {
    const marked = updateMsg(s, thread, msgId, (m) => ({ ...m, chosen: label }));
    return echo ? push(marked, thread, [me(s.clock, label)]) : marked;
  };
}

const text = (s: DemoState, t: string, extra: Partial<Msg> = {}) => agent(s.clock, { text: t, ...extra });

function addApproval(s: DemoState, a: Omit<Approval, "id" | "status">): DemoState {
  return { ...s, approvals: [{ ...a, id: `ap${Date.now().toString(36)}`, status: "waiting" }, ...s.approvals] };
}

/* ---------------------------------------------------------------------------
   Taps on buttons and chips
   --------------------------------------------------------------------------- */

export function tap(s0: DemoState, thread: ThreadId, msgId: string, a: Action): Outcome {
  const w = s0.world;
  const d = a.data ?? {};
  const cust = () => customerById(w, String(d.customerId ?? chaseOrder(w)[0]!.id));

  switch (a.id) {
    /* --- navigation ------------------------------------------------------ */
    case "go-thread":
      return { ui: { type: "openThread", id: String(d.id) as ThreadId } };
    case "go-tab":
      return { ui: { type: "tab", tab: String(d.tab) as Tab } };
    case "ask":
      return { ...ask(s0, thread, String(d.q ?? a.label)), now: (s) => push(updateMsg(s, thread, msgId, (m) => ({ ...m, chosen: a.label })), thread, [me(s.clock, String(d.q ?? a.label))]) };
    case "view-quote":
      return { ui: { type: "customerQuote", thread, msgId: String(d.ref) } };
    case "view-statement":
      return { ui: { type: "customerStatement", customerId: String(d.customerId) } };
    case "view-supplier":
      return { ui: { type: "supplierRate", product: String(d.product ?? w.products[0]!.name) } };

    /* --- sales ------------------------------------------------------------ */
    case "quote-share": {
      const m = findMsg(s0, thread, msgId);
      const q = m?.card as QuoteCard | undefined;
      const c = w.customers.find((x) => x.name === q?.customer) ?? w.customers[2]!;
      return {
        now: (s) => updateMsg(chooseAndEcho(thread, msgId, a.label, false)(s), thread, msgId, (mm) => ({ ...mm, card: { ...(mm.card as QuoteCard), status: "sent" }, status: `Link sent to ${c.contact} · ${c.phone}` })),
        later: [
          say(thread, 900, (s) => [
            text(s, `Sent to ${c.contact} by SMS and email. The link opens in any browser, so ${c.name} doesn't need an app. I'll tell you the moment they open it.`, {
              actions: [act("view-quote", "See what the customer sees", { ref: msgId }, true)],
            }),
          ]),
          // Skipped if the visitor already accepted from the customer's view.
          say(thread, 4200, (s) =>
            (findMsg(s, thread, msgId)?.card as QuoteCard | undefined)?.status === "won"
              ? []
              : [text(s, `${c.contact} opened ${q?.no ?? "the quote"} just now.`, { actions: [act("view-quote", "Open their view and accept it", { ref: msgId }, true)] })],
          ),
        ],
      };
    }
    case "quote-edit": {
      const q = findMsg(s0, thread, msgId)?.card as QuoteCard | undefined;
      if (!q) return {};
      const r0 = q.lines[0]!.rate;
      const unit = q.lines[0]!.unit;
      const opts = [-1.5, -0.75, 0.5].map((p) => (r0 >= 1000 ? Math.round((r0 * (1 + p / 100)) / 10) * 10 : Math.round(r0 * (1 + p / 100) * 10) / 10));
      return {
        now: chooseAndEcho(thread, msgId, a.label),
        later: [
          say(thread, 800, (s) => [
            text(s, `What rate for ${q.customer}? Now ${rate(r0, unit)}. Last rate to them was ${rate(q.lastRate ?? r0, unit)}.`, {
              chips: opts.map((o) => act("quote-rate", rate(o, unit), { rate: o, ref: msgId })),
            }),
          ]),
        ],
      };
    }
    case "quote-rate": {
      const src = s0.threads[thread].messages.find((m) => m.id === String(d.ref))?.card as QuoteCard | undefined;
      if (!src) return {};
      const c = w.customers.find((x) => x.name === src.customer) ?? w.customers[2]!;
      const p = w.products.find((x) => x.name === src.lines[0]!.name) ?? w.products[0]!;
      return {
        now: chooseAndEcho(thread, msgId, a.label),
        later: [
          say(thread, 900, (s) => {
            const [no, st] = nextQuoteNo(s);
            const card = buildQuote(w, no, c, p, src.lines[0]!.qty, Number(d.rate));
            return [st, [text(st, card.inBand ? `Revised. Margin is now ${card.margin}%, still inside your price band.` : `At this rate the margin is ${card.margin}%, below your ${w.limits.marginFloor}% floor.`, { card, actions: quoteActions(card) })]];
          }),
        ],
      };
    }
    case "quote-approval": {
      const q = findMsg(s0, thread, msgId)?.card as QuoteCard | undefined;
      return {
        now: (s) => {
          let st = chooseAndEcho(thread, msgId, a.label, false)(s);
          st = updateMsg(st, thread, msgId, (m) => ({ ...m, card: { ...(m.card as QuoteCard), status: "waiting" } }));
          if (q) {
            const t = quoteTotals(q);
            st = addApproval(st, {
              type: "Quote",
              who: `${w.team.sales[0]} · sales`,
              title: `${q.customer} · ${qty(q.lines[0]!.qty, q.lines[0]!.unit)} ${q.lines[0]!.name}`,
              detail: `${money(t.total)} · margin ${q.margin}%`,
              why: `Below your ${w.limits.marginFloor}% margin floor`,
              thread,
              after: `Quote link sent to ${q.customer}.`,
              ref: q.no,
            });
          }
          return st;
        },
        later: [say(thread, 700, (s) => [text(s, "It's in Approvals. Everything inside your price band goes out without you, so only quotes like this one wait.", { actions: [act("go-tab", "Open approvals", { tab: "approvals" }, true)] })])],
      };
    }
    case "quote-hold":
      return { now: chooseAndEcho(thread, msgId, a.label), later: [say(thread, 700, (s) => [text(s, "Held. I'll keep this rate for 2 days and remind you tomorrow at 10:00.")])] };
    case "nudge": {
      const c = cust();
      return {
        now: chooseAndEcho(thread, msgId, a.label),
        later: [
          say(thread, 900, (s) => [text(s, `Sent to ${c.contact}: "Rates are holding till tomorrow. Shall I book your order?"`)]),
          say(thread, 4500, (s) => [text(s, `${c.contact} replied: "Will confirm by evening, send one revised rate."`, { actions: [act("quote-edit-from-nudge", "Make a revised quote", { customerId: c.id }, true)] })]),
        ],
      };
    }
    case "quote-edit-from-nudge": {
      const c = cust();
      const p = w.products[1]!;
      return {
        now: chooseAndEcho(thread, msgId, a.label),
        later: [
          say(thread, 900, (s) => {
            const [no, st] = nextQuoteNo(s);
            const card = buildQuote(w, no, c, p, roundQty((p.qty[0] + p.qty[1]) / 2, p.unit), p.rate * 0.993);
            return [st, [text(st, `Revised 0.7% lower for ${c.name}. Margin ${card.margin}%.`, { card, actions: quoteActions(card) })]];
          }),
        ],
      };
    }
    case "mark-lost":
      return {
        now: chooseAndEcho(thread, msgId, a.label),
        later: [
          say(thread, 700, (s) => [
            text(s, "What was the reason?", { chips: ["Price", "Delivery time", "Bought elsewhere", "Project delayed"].map((r) => act("lost-reason", r, { r })) }),
          ]),
        ],
      };
    case "lost-reason":
      return {
        now: chooseAndEcho(thread, msgId, a.label),
        later: [
          say(thread, 800, (s) => [
            text(s, `Logged as lost: ${String(d.r).toLowerCase()}. This month 11 quotes were lost on price, 4 on delivery. Should I warn you before a quote goes out above today's market rate?`, {
              actions: [act("flag-yes", "Yes, warn me", undefined, true), act("noop", "Not now")],
            }),
          ]),
        ],
      };
    case "flag-yes":
      return { now: chooseAndEcho(thread, msgId, a.label), later: [say(thread, 600, (s) => [text(s, "Done. Quotes more than 1% above market will show a warning before you share them.")])] };
    case "noop":
      return { now: chooseAndEcho(thread, msgId, a.label), later: [say(thread, 500, (s) => [text(s, "Okay.")])] };
    case "post-so":
      return {
        now: (s) => updateMsg(chooseAndEcho(thread, msgId, a.label, false)(s), thread, msgId, (m) => ({ ...m, card: { ...(m.card as Extract<Card, { kind: "won" }>), posted: true } })),
        later: [say(thread, 900, (s) => [agent(s.clock, { card: { kind: "alert", tone: "good", title: `Sales order SO-${2290 + s.seq.quote - 1186} posted in Tally`, body: `${w.team.sales[1]} in dispatch has it for ${dayDate(addDays(w.today, 2))}. Follow-ups for this quote have stopped.` } })])],
      };
    case "tell-dispatch":
      return { now: chooseAndEcho(thread, msgId, a.label), later: [say(thread, 700, (s) => [text(s, `Told ${w.team.sales[1]}: load on ${dayDate(addDays(w.today, 2))}, deliver to ${w.biz.city} site.`)])] };
    case "winback": {
      const list = w.customers.filter((c) => c.lastBuyDays > 30);
      return {
        now: chooseAndEcho(thread, msgId, a.label),
        later: [
          say(thread, 900, (s) => [text(s, `Sent today's rates to ${list.map((c) => c.name).join(" and ")}, with a link to order.`)]),
          say(thread, 4200, (s) => [text(s, `${list[0]!.contact} at ${list[0]!.name} replied: "Send rate for ${roundQty(w.products[0]!.qty[0], w.products[0]!.unit)} ${w.products[0]!.unit}, we have a new project."`, { actions: [act("ask", "Make that quote", { q: `quote ${roundQty(w.products[0]!.qty[0], w.products[0]!.unit)} ${w.products[0]!.unit} ${shortName(w.products[0]!)} for ${list[0]!.name}` }, true)] })]),
        ],
      };
    }

    /* --- collections ------------------------------------------------------ */
    case "send-reminder": {
      const c = cust();
      return {
        now: chooseAndEcho(thread, msgId, a.label, false),
        later: [
          say(thread, 800, (s) => [
            text(s, `Sent to ${c.contact} with a statement link${w.biz.language === "Hinglish" ? ", in Hinglish" : ""}. They can see every open bill and pick a payment date.`, {
              status: `Delivered · ${c.phone}`,
              actions: [act("view-statement", "See what the customer sees", { customerId: c.id }, true)],
            }),
          ]),
        ],
      };
    }
    case "call": {
      const c = cust();
      return {
        now: chooseAndEcho(thread, msgId, a.label),
        later: [
          say(thread, 900, (s) => [
            text(s, `${c.contact}'s number is ${c.phone}. How did the call go?`, {
              chips: [act("call-promise", "Promised to pay", { customerId: c.id }), act("call-nr", "Not reachable", { customerId: c.id }), act("call-dispute", "Disputes a bill", { customerId: c.id })],
            }),
          ]),
        ],
      };
    }
    case "call-promise":
    case "log-promise": {
      const c = cust();
      const dates = [3, 6, 10].map((n) => dayDate(addDays(w.today, n)));
      return {
        now: chooseAndEcho(thread, msgId, a.label),
        later: [
          say(thread, 700, (s) => [
            text(s, `When will ${c.name} pay, and how much?`, {
              chips: [
                act("promise-date", `${money(c.outstanding)} on ${dates[0]}`, { customerId: c.id, amount: c.outstanding, date: dates[0]! }),
                act("promise-date", `${money(c.outstanding / 2)} on ${dates[1]}`, { customerId: c.id, amount: c.outstanding / 2, date: dates[1]! }),
                act("promise-date", `${money(c.outstanding)} on ${dates[2]}`, { customerId: c.id, amount: c.outstanding, date: dates[2]! }),
              ],
            }),
          ]),
        ],
      };
    }
    case "promise-date": {
      const c = cust();
      return {
        now: chooseAndEcho(thread, msgId, a.label),
        later: [say(thread, 800, (s) => promiseLogged(s, c.id, Number(d.amount), String(d.date), "you"))],
      };
    }
    case "call-nr": {
      const c = cust();
      return {
        now: chooseAndEcho(thread, msgId, a.label),
        later: [say(thread, 700, (s) => [text(s, `I'll remind you to try ${c.contact} again at 3 pm, and I've sent the statement link meanwhile.`, { actions: [act("next-due", "Next customer", undefined, true)] })])],
      };
    }
    case "call-dispute": {
      const c = cust();
      return {
        now: chooseAndEcho(thread, msgId, a.label),
        later: [say(thread, 700, (s) => [text(s, "Which bill?", { chips: c.bills.map((b) => act("dispute-bill", `${b.no} · ${money(b.amount)}`, { customerId: c.id, bill: b.no, amount: b.amount })) })])],
      };
    }
    case "dispute-bill": {
      const c = cust();
      return {
        now: chooseAndEcho(thread, msgId, a.label),
        later: [say(thread, 800, (s) => [text(s, `Flagged ${d.bill} for ${w.team.accounts} in accounts to check. The other ${money(c.outstanding - Number(d.amount))} stays due and I'll keep following up on it.`, { actions: [act("next-due", "Next customer", undefined, true)] })])],
      };
    }
    case "next-due": {
      const list = chaseOrder(w);
      return {
        now: chooseAndEcho(thread, msgId, a.label, false),
        later: [
          say(thread, 700, (s) => {
            const i = s.queueIndex + (a.label.startsWith("Start") ? 0 : 1);
            const c = list[i];
            const st = { ...s, queueIndex: i };
            if (!c) return [st, [text(st, `That's everyone for today. ${money(st.collectedToday)} promised or collected so far.`)]];
            return [st, [agent(st.clock, { card: dueCard(w, c), actions: dueActions(c) })]];
          }),
        ],
      };
    }
    case "send-all":
      return {
        now: chooseAndEcho(thread, msgId, a.label),
        later: [
          say(thread, 900, (s) => [text(s, `Sent reminders with statement links to 6 customers, ${money(w.kpi.overdue * 0.42)} in total. I'll post here as each one opens their link or picks a date.`)]),
          say(thread, 5000, (s) => {
            const c = w.customers[6]!;
            return promiseLogged(s, c.id, c.outstanding, dayDate(addDays(w.today, 4)), "customer");
          }),
        ],
      };

    /* --- stock ------------------------------------------------------------- */
    case "ask-rates": {
      const p = w.products[0]!;
      const q = roundQty(p.perDay * 30, p.unit);
      return {
        now: chooseAndEcho(thread, msgId, a.label),
        later: [
          say(thread, 800, (s) => [
            text(s, `Sent rate requests to ${w.suppliers.slice(0, 3).map((x) => x.name).join(", ")} for ${qty(q, p.unit)} ${shortName(p)}. Each gets a link to type their rate.`, {
              actions: [act("view-supplier", "See the supplier's page", { product: p.name }, true)],
            }),
          ]),
          say(thread, 4200, (s) => [ratesMsg(s)]),
        ],
      };
    }
    case "draft-po":
    case "order-last": {
      const p = w.products[0]!;
      const q = roundQty(p.perDay * 30, p.unit);
      const sup = w.suppliers[Number(d.sup ?? 0)]!;
      const r = Number(d.rate ?? p.lastBuys[0]);
      const total = r * q;
      const over = total > w.limits.poLimit;
      return {
        now: chooseAndEcho(thread, msgId, a.label),
        later: [
          say(thread, 900, (s) => {
            const [no, st0] = nextPoNo(s);
            let st = st0;
            if (over) {
              st = { ...st, approvals: st.approvals.filter((x) => !(x.type === "Purchase order" && x.status === "waiting")) };
              st = addApproval(st, {
                type: "Purchase order",
                who: `${w.team.purchase} · purchase`,
                title: `${sup.brand} · ${qty(q, p.unit)} ${shortName(p)}`,
                detail: `${money(total)} · ${rate(r, p.unit)}`,
                why: `Above ${w.team.purchase}'s ${money(w.limits.poLimit)} limit`,
                thread: "stock",
                after: `${no} posted in Tally and sent to ${sup.name}.`,
                ref: no,
              });
            }
            return [
              st,
              [
                agent(st.clock, {
                  card: { kind: "po", no, supplier: sup.name, product: p.name, qty: q, unit: p.unit, rate: r, status: over ? "waiting" : "posted" },
                  text: over ? `${money(total)} is above ${w.team.purchase}'s ${money(w.limits.poLimit)} limit, so it's waiting for your approval.` : `${no} posted in Tally and sent to ${sup.name}.`,
                  actions: over ? [act("go-tab", "Open approvals", { tab: "approvals" }, true)] : undefined,
                }),
              ],
            ];
          }),
        ],
      };
    }
    case "negotiate": {
      const sup = w.suppliers[Number(d.sup ?? 0)]!;
      const p = w.products[0]!;
      const target = Math.round((Number(d.rate) * 0.996) / 10) * 10;
      return {
        now: chooseAndEcho(thread, msgId, a.label),
        later: [
          say(thread, 800, (s) => [text(s, `Asked ${sup.name} to come down to ${rate(target, p.unit)}.`)]),
          say(thread, 4000, (s) => [text(s, `${sup.name} agreed to ${rate(target, p.unit)}. That saves ${money((Number(d.rate) - target) * roundQty(p.perDay * 30, p.unit))} on this order.`, { actions: [act("draft-po", `Draft PO at ${rate(target, p.unit)}`, { sup: d.sup ?? 0, rate: target }, true)] })]),
        ],
      };
    }
    case "remind-tomorrow":
      return { now: chooseAndEcho(thread, msgId, a.label), later: [say(thread, 600, (s) => [text(s, `I'll bring this up tomorrow at 10:00. You'll have ${Math.round(w.products[0]!.stock / w.products[0]!.perDay) - 1} days of stock left then.`)])] };
    case "send-offer":
    case "offer-send": {
      const p = w.products[5]!;
      const buyer = w.customers[3]!;
      const offer = Number(d.offer ?? Math.round(p.cost * 1.02));
      const n = roundQty(p.qty[1] * 0.6, p.unit);
      return {
        now: chooseAndEcho(thread, msgId, a.label),
        later: [
          say(thread, 800, (s) => [text(s, `Offer sent to 6 past buyers at ${rate(offer, p.unit)}, valid for 3 days.`)]),
          say(thread, 4500, (s) => [
            text(s, `${buyer.contact} at ${buyer.name} wants ${qty(n, p.unit)} at the offer price: ${money(n * offer)}.`, {
              actions: [act("offer-confirm", "Book the order", { n, offer }, true), act("noop", "Ask for a higher quantity")],
            }),
          ]),
        ],
      };
    }
    case "offer-price": {
      const p = w.products[5]!;
      const opts = [1.01, 1.03, 1.05].map((f) => Math.round(p.cost * f));
      return {
        now: chooseAndEcho(thread, msgId, a.label),
        later: [say(thread, 700, (s) => [text(s, `Your cost is ${rate(p.cost, p.unit)} and the market is about ${rate(Math.round(p.rate * 1.02), p.unit)}. Offer at:`, { chips: opts.map((o) => act("offer-send", rate(o, p.unit), { offer: o })) })])],
      };
    }
    case "offer-confirm": {
      const p = w.products[5]!;
      const buyer = w.customers[3]!;
      const value = Number(d.n) * Number(d.offer);
      return {
        now: chooseAndEcho(thread, msgId, a.label),
        later: [
          say(thread, 900, (s) => [
            { ...s, wonToday: s.wonToday + value },
            [agent(s.clock, { card: { kind: "alert", tone: "good", title: `Order booked · ${money(value)}`, body: `${qty(Number(d.n), p.unit)} ${shortName(p)} for ${buyer.name}. Sales order posted in Tally. ${money(value)} of idle stock turned into a sale.` } })],
          ]),
        ],
      };
    }

    /* --- cash ---------------------------------------------------------------- */
    case "ask-early": {
      const list = w.customers.filter((c) => c.grade === "A" || c.grade === "B").slice(0, 4);
      return {
        now: chooseAndEcho(thread, msgId, a.label),
        later: [
          say(thread, 900, (s) => [
            text(s, "These 4 usually pay on time and have bills due in the next 3 weeks:", {
              card: { kind: "table", cols: ["Customer", "Due soon", "Grade"], align: ["l", "r", "r"], rows: list.map((c) => [c.name, money(c.outstanding), c.grade]) },
              actions: [act("early-send", "Ask them to pay this week", undefined, true)],
            }),
          ]),
        ],
      };
    }
    case "early-send": {
      const c = w.customers.filter((x) => x.grade === "A")[0] ?? w.customers[3]!;
      const gap = w.cash[2]!.outflow - w.cash[2]!.inflow;
      return {
        now: chooseAndEcho(thread, msgId, a.label),
        later: [
          say(thread, 800, (s) => [text(s, "Requests sent. I'll update the cash view as they reply.")]),
          say(thread, 4500, (s) => [
            { ...s, collectedToday: s.collectedToday + c.outstanding },
            [agent(s.clock, { card: { kind: "alert", tone: "good", title: `${c.name} will pay ${money(c.outstanding)} on Thursday`, body: `Week 3 gap is now ${money(Math.max(0, gap - c.outstanding))}.` } })],
          ]),
        ],
      };
    }
    case "delay-payment": {
      const sup = w.suppliers[0]!;
      return {
        now: chooseAndEcho(thread, msgId, a.label),
        later: [
          say(thread, 800, (s) => [text(s, `Asked ${sup.name} to move the payment by 5 days. They've agreed before when asked a week ahead.`)]),
          say(thread, 4000, (s) => [agent(s.clock, { card: { kind: "alert", tone: "good", title: `${sup.name} agreed`, body: `The payment moves to ${dayDate(addDays(w.today, 20))}. Week 3 is now positive.` } })]),
        ],
      };
    }

    /* --- score --------------------------------------------------------------- */
    case "score-apply": {
      const c = w.customers[4]!;
      return {
        now: chooseAndEcho(thread, msgId, a.label),
        later: [say(thread, 900, (s) => [text(s, `Done. ${c.name}'s credit limit is now ${money(c.outstanding * 1.4)} in Tally, and new quotes for them will ask 25% advance. I'll tell you when they're back to grade B.`)])],
      };
    }
    case "score-keep":
      return { now: chooseAndEcho(thread, msgId, a.label), later: [say(thread, 600, (s) => [text(s, "Okay, terms unchanged. I'll alert you if they slip further.")])] };

    default:
      return { now: chooseAndEcho(thread, msgId, a.label), later: [say(thread, 600, (s) => [text(s, "Done.")])] };
  }
}

function ratesMsg(s: DemoState): Msg {
  const w = s.world;
  const p = w.products[0]!;
  const q = roundQty(p.perDay * 30, p.unit);
  const base = p.lastBuys[0]!;
  const rows = w.suppliers.slice(0, 3).map((x) => ({
    supplier: x.name,
    brand: x.brand,
    rate: base >= 1000 ? Math.round((base * (1 + x.delta)) / 10) * 10 : Math.round(base * (1 + x.delta) * 10) / 10,
    days: x.days,
    onTime: x.onTime,
    best: false,
  }));
  // Best value: cheapest among suppliers that deliver on time at least 90% of the time.
  const reliable = rows.filter((r) => r.onTime >= 90).sort((a, b) => a.rate - b.rate)[0]!;
  reliable.best = true;
  const cheapest = [...rows].sort((a, b) => a.rate - b.rate)[0]!;
  const idx = rows.indexOf(reliable);
  return agent(s.clock, {
    card: {
      kind: "rates",
      product: p.name,
      qty: q,
      unit: p.unit,
      rows,
      note: cheapest === reliable ? `${reliable.supplier} is cheapest and reliable.` : `${cheapest.supplier} is cheapest but delivers on time only ${cheapest.onTime}% of the time.`,
    },
    actions: [
      act("draft-po", `Draft PO · ${reliable.supplier} · ${money(reliable.rate * q)}`, { sup: idx, rate: reliable.rate }, true),
      act("negotiate", `Ask ${reliable.supplier} for a lower rate`, { sup: idx, rate: reliable.rate }),
    ],
  });
}

/** Days from today for a "Thu 22 Oct" label the agents wrote. */
function daysFromLabel(s: DemoState, label: string): number {
  for (let n = -7; n <= 60; n++) if (dayDate(addDays(s.world.today, n)) === label) return n;
  return 3;
}

/** Adds a line to the agents' work log the desk shows. */
export function logWork(s: DemoState, agent: ThreadId, text: string, count = 1, customerId?: string): DemoState {
  const entry = { id: `l${Date.now().toString(36)}${s.desk.log.length}`, at: s.clock, agent, text, count, customerId };
  return { ...s, desk: { ...s.desk, log: [entry, ...s.desk.log] } };
}

export function promiseLogged(s: DemoState, customerId: string, amount: number, date: string, by: "you" | "customer"): [DemoState, Msg[]] {
  const w = s.world;
  const c = customerById(w, customerId);
  const rec = { id: `pr-${customerId}-${s.clock}`, customerId, amount, date, inDays: daysFromLabel(s, date), by, status: "due" as const };
  let st: DemoState = { ...s, collectedToday: s.collectedToday + amount, desk: { ...s.desk, promises: [rec, ...s.desk.promises.filter((p) => !(p.customerId === customerId && p.status === "due"))] } };
  st = logWork(st, "collect", `${by === "customer" ? `${c.name} picked a payment date` : `Logged a promise from ${c.name}`}: ${money(amount)} on ${date}`, 1, customerId);
  return [
    st,
    [
      agent(st.clock, {
        card: {
          kind: "alert",
          tone: "good",
          title: `${by === "customer" ? `${c.name} picked a date` : "Promise logged"}: ${money(amount)} on ${date}`,
          body: `I'll remind ${c.contact} the day before, and tell you at once if it's missed.`,
        },
        actions: [act("next-due", "Next customer", undefined, true)],
      }),
    ],
  ];
}

/* ---------------------------------------------------------------------------
   Things that happen outside a chat button
   --------------------------------------------------------------------------- */

export function approve(s0: DemoState, id: string): Outcome {
  const a = s0.approvals.find((x) => x.id === id);
  if (!a) return {};
  return {
    now: (s) => {
      const st: DemoState = logWork({ ...s, approvals: s.approvals.map((x) => (x.id === id ? { ...x, status: "approved" } : x)) }, a.thread, `Approved by ${s.world.firstName}: ${a.type.toLowerCase()} · ${a.title}`);
      if (!a.ref) return st;
      const t = st.threads[a.thread];
      const messages = t.messages.map((m) => {
        const c = m.card;
        if (c?.kind === "po" && c.no === a.ref) return { ...m, card: { ...c, status: "posted" as const }, actions: undefined };
        if (c?.kind === "quote" && c.no === a.ref) return { ...m, card: { ...c, status: "sent" as const }, chosen: m.chosen ?? "Send for approval", status: "Approved · link sent to customer" };
        return m;
      });
      return { ...st, threads: { ...st.threads, [a.thread]: { ...t, messages } } };
    },
    later: [say(a.thread, 600, (s) => [agent(s.clock, { card: { kind: "alert", tone: "good", title: `Approved by ${s.world.firstName}`, body: `${a.type}: ${a.title}. ${a.after}` } })])],
  };
}

export function changeApproval(s0: DemoState, id: string): Outcome {
  const a = s0.approvals.find((x) => x.id === id);
  if (!a) return {};
  return {
    now: (s) => logWork({ ...s, approvals: s.approvals.map((x) => (x.id === id ? { ...x, status: "changed" } : x)) }, a.thread, `Sent back to ${a.who.split(" · ")[0]}: ${a.title}`),
    later: [say(a.thread, 600, (s) => [text(s, `Sent back to ${a.who.split(" · ")[0]} with your note: "${a.why}. Please revise."`)])],
  };
}

/** The customer tapped Accept on their quote page. */
export function customerAccepted(s0: DemoState, thread: ThreadId, msgId: string): Outcome {
  const q = findMsg(s0, thread, msgId)?.card as QuoteCard | undefined;
  if (!q || q.status === "won") return {};
  const t = quoteTotals(q);
  return {
    now: (s) => updateMsg({ ...s, wonToday: s.wonToday + t.total }, thread, msgId, (m) => ({ ...m, card: { ...(m.card as QuoteCard), status: "won" }, status: `Accepted by ${q.customer}` })),
    later: [
      say(thread, 900, (s) => [
        agent(s.clock, {
          card: { kind: "won", customer: q.customer, amount: t.total, quoteNo: q.no, minutes: 6, posted: false },
          actions: [act("post-so", "Post sales order to Tally", undefined, true), act("tell-dispatch", "Tell dispatch")],
        }),
      ]),
    ],
  };
}

/** The customer picked a payment date on their statement page. */
export function customerPromised(_s: DemoState, customerId: string, amount: number, date: string): Outcome {
  return { later: [say("collect", 800, (s) => promiseLogged(s, customerId, amount, date, "customer"))] };
}

/** A supplier typed a rate on their page. */
export function supplierQuoted(_s: DemoState, supplierName: string, value: number): Outcome {
  return {
    later: [say("stock", 800, (s) => [text(s, `${supplierName} sent ${inr(value)} per ${s.world.products[0]!.unit} from their link.`)])],
  };
}

