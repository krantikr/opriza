import { roundQty } from "../data/generate";
import { addDays, dayDate, money, qty, rate } from "../lib/format";
import { ask } from "./ask";
import { act, agent, customerById, me, nextPoNo, push, shortName } from "./core";
import { approve, logWork, promiseLogged, tap } from "./respond";
import type { DemoState, Msg, Outcome, PipeQuote, Rules, Stage, ThreadId } from "./types";

/* ---------------------------------------------------------------------------
   What the desktop screens can do.

   Every action here is the same kind of Outcome a chat tap returns, and each
   one also says what happened in the matching chat. So a reminder sent from
   the Collections table shows up in the Collections chat on the phone, and
   the agents stay one brain whichever screen the visitor uses.
   --------------------------------------------------------------------------- */

type Step = NonNullable<Outcome["later"]>[number];

const say = (thread: ThreadId, delay: number, run: (s: DemoState) => DemoState): Step => ({ delay, thread, run });
const post = (thread: ThreadId, text: string, extra: Partial<Msg> = {}) => (s: DemoState) => push(s, thread, [agent(s.clock, { text, ...extra })], { unread: true });

/** Several outcomes played as one: changes in order, replies in time order. */
export function combine(...outs: Outcome[]): Outcome {
  return {
    now: (s) => outs.reduce((st, o) => (o.now ? o.now(st) : st), s),
    later: outs.flatMap((o) => o.later ?? []).sort((a, b) => a.delay - b.delay),
    ui: outs.find((o) => o.ui)?.ui,
  };
}

const names = (s: DemoState, ids: string[]) => {
  const list = ids.map((id) => customerById(s.world, id).name);
  return list.length <= 2 ? list.join(" and ") : `${list.slice(0, 2).join(", ")} and ${list.length - 2} more`;
};

/* --- collections ---------------------------------------------------------- */

/** Statement links to one or many customers at once. One of them picks a
 *  payment date a few seconds later, as customers do. */
export function remindMany(s0: DemoState, ids: string[]): Outcome {
  if (!ids.length) return {};
  const w = s0.world;
  const total = ids.reduce((a, id) => a + customerById(w, id).outstanding, 0);
  // The customer who answers: a good payer without a promise already open.
  const open = new Set(s0.desk.promises.filter((p) => p.status === "due").map((p) => p.customerId));
  const fresh = ids.map((id) => customerById(w, id)).filter((c) => !open.has(c.id));
  const picker = fresh.find((c) => c.grade === "A" || c.grade === "B") ?? fresh[0];
  return {
    now: (s) => {
      const reminded = { ...s.desk.reminded };
      for (const id of ids) reminded[id] = s.clock;
      const tour = ids.length >= 2 ? { ...s.desk.tour, remind: true } : s.desk.tour;
      return logWork({ ...s, desk: { ...s.desk, reminded, tour } }, "collect", `Sent statement links to ${names(s, ids)} · ${money(total)}`, ids.length, ids.length === 1 ? ids[0] : undefined);
    },
    later: [
      say("collect", 700, post("collect", `Sent statement links${w.biz.language === "Hinglish" ? " in Hinglish" : ""} to ${names(s0, ids)}, ${money(total)} in total. Each one can see their open bills and pick a payment date. I'll post here as they reply.`, { status: `Delivered · ${ids.length} customer${ids.length === 1 ? "" : "s"}` })),
      ...(picker
        ? [
            say("collect", 4200, (s) => {
              const [st, msgs] = promiseLogged(s, picker.id, picker.outstanding, dayDate(addDays(w.today, 3)), "customer");
              return push(st, "collect", msgs, { unread: true });
            }),
          ]
        : []),
    ],
  };
}

/** The result of a call, logged from the call list. */
export function callResult(s0: DemoState, customerId: string, result: "promise" | "half" | "nr" | "dispute"): Outcome {
  const w = s0.world;
  const c = customerById(w, customerId);
  if (result === "promise" || result === "half") {
    const amount = result === "half" ? Math.round(c.outstanding / 2 / 1e4) * 1e4 : c.outstanding;
    const date = dayDate(addDays(w.today, result === "half" ? 2 : 4));
    return {
      now: (s) => {
        const [st, msgs] = promiseLogged(s, customerId, amount, date, "you");
        return push(st, "collect", [me(st.clock, `Called ${c.contact}: promised ${money(amount)} on ${date}`), ...msgs]);
      },
    };
  }
  if (result === "nr") {
    return {
      now: (s) => {
        const st = logWork({ ...s, desk: { ...s.desk, reminded: { ...s.desk.reminded, [customerId]: s.clock } } }, "collect", `${c.contact} at ${c.name} not reachable — statement link sent, retry at 3 pm`, 1, customerId);
        return push(st, "collect", [agent(st.clock, { text: `${c.contact} didn't pick up. I've sent the statement link and will remind you to call again at 3 pm.` })]);
      },
    };
  }
  const bill = c.bills[0]!;
  return {
    now: (s) => {
      const st = logWork(s, "collect", `${c.name} disputes ${bill.no} — flagged for ${w.team.accounts} in accounts`, 1, customerId);
      return push(st, "collect", [agent(st.clock, { text: `Flagged ${bill.no} (${money(bill.amount)}) for ${w.team.accounts} to check. The rest of ${c.name}'s dues stay on the list.` })]);
    },
  };
}

/* --- sales ----------------------------------------------------------------- */

const STAGE_WORD: Record<Stage, string> = { draft: "draft", sent: "sent", opened: "opened", talks: "in talks", won: "won", lost: "lost" };

export function moveQuote(s0: DemoState, no: string, stage: Stage): Outcome {
  const q = s0.desk.pipeline.find((x) => x.no === no);
  if (!q || q.stage === stage) return {};
  const c = customerById(s0.world, q.customerId);
  return {
    now: (s) => {
      const pipeline = s.desk.pipeline.map((x) => (x.no === no ? { ...x, stage, ageH: 0 } : x));
      let st: DemoState = { ...s, desk: { ...s.desk, pipeline }, wonToday: s.wonToday + (stage === "won" ? q.value : 0) };
      st = logWork(st, "sales", `${no} for ${c.name} moved to ${STAGE_WORD[stage]}${stage === "won" ? ` · ${money(q.value)}` : ""}`, 1, c.id);
      return stage === "won" || stage === "lost"
        ? push(st, "sales", [agent(st.clock, stage === "won" ? { card: { kind: "won", customer: c.name, amount: q.value, quoteNo: no, minutes: 9, posted: false }, actions: [act("post-so", "Post sales order to Tally", undefined, true), act("tell-dispatch", "Tell dispatch")] } : { text: `${no} for ${c.name} marked lost. I'll ask why next time I talk to ${c.contact}.` })], { unread: true })
        : st;
    },
  };
}

/** A gentle nudge on a quote that has gone quiet. The customer opens it. */
export function nudgeQuote(s0: DemoState, no: string): Outcome {
  const q = s0.desk.pipeline.find((x) => x.no === no);
  if (!q) return {};
  const c = customerById(s0.world, q.customerId);
  return {
    now: (s) => logWork({ ...s, desk: { ...s.desk, pipeline: s.desk.pipeline.map((x) => (x.no === no ? { ...x, ageH: 0 } : x)) } }, "sales", `Nudged ${c.name} on ${no}`, 1, c.id),
    later: [
      say("sales", 700, post("sales", `Sent ${c.contact} a nudge on ${no}: "Rates are holding till tomorrow. Shall I book your order?"`)),
      say("sales", 4000, (s) => {
        const st = { ...s, desk: { ...s.desk, pipeline: s.desk.pipeline.map((x) => (x.no === no && x.stage === "sent" ? { ...x, stage: "opened" as Stage } : x)) } };
        return post("sales", `${c.contact} opened ${no} just now.`)(st);
      }),
    ],
  };
}

/** Turns a waiting enquiry into a priced quote in the Sales chat. */
export function quoteEnquiry(s0: DemoState, enquiryId: string): Outcome {
  const e = s0.desk.enquiries.find((x) => x.id === enquiryId);
  if (!e) return {};
  const c = customerById(s0.world, e.customerId);
  const o = ask(s0, "sales", `${e.text} for ${c.name}`.replace(/\s+/g, " "));
  return {
    ...o,
    now: (s) => {
      const st = { ...s, desk: { ...s.desk, enquiries: s.desk.enquiries.map((x) => (x.id === enquiryId ? { ...x, quoted: true } : x)) } };
      return logWork(o.now ? o.now(st) : st, "sales", `Priced ${c.name}'s ${e.channel.split(" ")[0]} enquiry`, 1, c.id);
    },
  };
}

/** Today's rates to customers who stopped buying. One replies. */
export function winBack(s0: DemoState, ids: string[]): Outcome {
  if (!ids.length) return {};
  const w = s0.world;
  const first = customerById(w, ids[0]!);
  const p = w.products[0]!;
  return {
    now: (s) => logWork(s, "sales", `Sent today's rates to ${names(s, ids)} to win them back`, ids.length),
    later: [
      say("sales", 700, post("sales", `Sent today's rates with an order link to ${names(s0, ids)}.`)),
      say("sales", 4300, post("sales", `${first.contact} at ${first.name} replied: "Send rate for ${roundQty(p.qty[0], p.unit)} ${p.unit}, we have a new project."`, { actions: [act("ask", "Make that quote", { q: `quote ${roundQty(p.qty[0], p.unit)} ${p.unit} ${shortName(p)} for ${first.name}` }, true)] })),
    ],
  };
}

/* --- stock ------------------------------------------------------------------ */

/** Supplier rates for one item: last buy rate moved by each supplier's usual gap. */
export function supplierRates(s: DemoState, productIdx: number) {
  const w = s.world;
  const p = w.products[productIdx]!;
  const base = p.lastBuys[0]!;
  const rows = w.suppliers.map((x, i) => ({
    idx: i,
    supplier: x.name,
    brand: x.brand,
    rate: base >= 1000 ? Math.round((base * (1 + x.delta)) / 10) * 10 : Math.round(base * (1 + x.delta) * 10) / 10,
    days: x.days,
    onTime: x.onTime,
    best: false,
  }));
  const best = rows.filter((r) => r.onTime >= 90).sort((a, b) => a.rate - b.rate)[0] ?? rows[0]!;
  best.best = true;
  return rows;
}

export function reorderQty(s: DemoState, productIdx: number) {
  const p = s.world.products[productIdx]!;
  return roundQty(p.perDay * 30, p.unit);
}

/** A purchase order from the stock table. Above the buyer's limit it waits
 *  for the owner, the same rule the chat follows. */
export function makePo(s0: DemoState, productIdx: number, supplierIdx: number): Outcome {
  const w = s0.world;
  const p = w.products[productIdx]!;
  const sup = w.suppliers[supplierIdx]!;
  const r = supplierRates(s0, productIdx)[supplierIdx]!.rate;
  const q = reorderQty(s0, productIdx);
  const total = r * q;
  const over = total > w.limits.poLimit;
  return {
    now: (s) => {
      const [no, st0] = nextPoNo(s);
      let st = st0;
      if (over) {
        st = {
          ...st,
          approvals: [
            { id: `ap${no}`, type: "Purchase order", who: `${w.team.purchase} · purchase`, title: `${sup.brand} · ${qty(q, p.unit)} ${shortName(p)}`, detail: `${money(total)} · ${rate(r, p.unit)}`, why: `Above ${w.team.purchase}'s ${money(w.limits.poLimit)} limit`, thread: "stock", after: `${no} posted in Tally and sent to ${sup.name}.`, status: "waiting", ref: no },
            ...st.approvals,
          ],
        };
      }
      st = logWork(st, "stock", over ? `Drafted ${no} for ${qty(q, p.unit)} ${shortName(p)} from ${sup.name} · waiting for your approval` : `Sent ${no} to ${sup.name}: ${qty(q, p.unit)} ${shortName(p)} · ${money(total)}`, 1);
      return push(st, "stock", [
        agent(st.clock, {
          card: { kind: "po", no, supplier: sup.name, product: p.name, qty: q, unit: p.unit, rate: r, status: over ? "waiting" : "posted" },
          text: over ? `${money(total)} is above ${w.team.purchase}'s ${money(w.limits.poLimit)} limit, so it's waiting for your approval.` : `${no} posted in Tally and sent to ${sup.name}.`,
        }),
      ], { unread: true });
    },
    ui: { type: "toast", text: over ? "PO drafted — waiting in Inbox for approval" : "PO sent to supplier and posted in Tally" },
  };
}

export function askRates(s0: DemoState, productIdx: number): Outcome {
  const w = s0.world;
  const p = w.products[productIdx]!;
  return {
    now: (s) => logWork(s, "stock", `Asked ${w.suppliers.slice(0, 3).map((x) => x.name).join(", ")} for today's rate on ${shortName(p)}`, 3),
    later: [say("stock", 700, post("stock", `Sent rate requests for ${qty(reorderQty(s0, productIdx), p.unit)} ${shortName(p)} to ${w.suppliers.slice(0, 3).map((x) => x.name).join(", ")}. Each gets a link to type their rate.`, { actions: [act("view-supplier", "See the supplier's page", { product: p.name }, true)] }))],
    ui: { type: "toast", text: "Rate requests sent to 3 suppliers" },
  };
}

/* --- cash ------------------------------------------------------------------ */

/** Customers who pay on time and could pay this week: the agent's pick for
 *  closing a short week. */
export function earlyPayers(s: DemoState) {
  return s.world.customers.filter((c) => (c.grade === "A" || c.grade === "B") && c.outstanding > 0).slice(0, 4);
}

/** Asks the good payers to pay early. One agrees a few seconds later and the
 *  money lands in the short week. */
export function cashAskEarly(s0: DemoState): Outcome {
  const list = earlyPayers(s0);
  const first = list.find((c) => c.grade === "A") ?? list[0];
  if (!first) return {};
  const gap = s0.world.cash[2]!.outflow - s0.world.cash[2]!.inflow;
  return {
    now: (s) => logWork(s, "cash", `Asked ${names(s, list.map((c) => c.id))} to pay this week`, list.length),
    later: [
      say("cash", 700, post("cash", `Asked ${names(s0, list.map((c) => c.id))} to pay this week instead of next. I'll update the cash view as they reply.`)),
      say("cash", 4300, (s) => {
        const st = logWork({ ...s, collectedToday: s.collectedToday + first.outstanding, desk: { ...s.desk, cashFix: { ...s.desk.cashFix, early: s.desk.cashFix.early + first.outstanding } } }, "cash", `${first.name} agreed to pay ${money(first.outstanding)} on Thursday`, 1, first.id);
        return push(st, "cash", [agent(st.clock, { card: { kind: "alert", tone: "good", title: `${first.name} will pay ${money(first.outstanding)} on Thursday`, body: `Week 3 gap is now ${money(Math.max(0, gap - st.desk.cashFix.early - (st.desk.cashFix.delayed ? s0.world.cash[2]!.outflow * 0.22 : 0)))}.` } })], { unread: true });
      }),
    ],
    ui: { type: "toast", text: `Early-payment requests sent to ${list.length} customers` },
  };
}

/** What moving the biggest supplier payment by 5 days shifts out of week 3. */
export const delayAmount = (s: DemoState) => Math.round((s.world.cash[2]!.outflow * 0.22) / 1e5) * 1e5;

export function cashDelay(s0: DemoState): Outcome {
  const w = s0.world;
  const sup = w.suppliers[0]!;
  return {
    now: (s) => logWork(s, "cash", `Asked ${sup.name} to move ${money(delayAmount(s))} by 5 days`, 1),
    later: [
      say("cash", 700, post("cash", `Asked ${sup.name} to move the ${money(delayAmount(s0))} payment by 5 days. They've agreed before when asked a week ahead.`)),
      say("cash", 3800, (s) => {
        const st = logWork({ ...s, desk: { ...s.desk, cashFix: { ...s.desk.cashFix, delayed: true } } }, "cash", `${sup.name} agreed to move the payment to ${dayDate(addDays(w.today, 20))}`, 1);
        return push(st, "cash", [agent(st.clock, { card: { kind: "alert", tone: "good", title: `${sup.name} agreed`, body: `${money(delayAmount(s0))} moves to ${dayDate(addDays(w.today, 20))}, out of week 3.` } })], { unread: true });
      }),
    ],
    ui: { type: "toast", text: `Request sent to ${sup.name}` },
  };
}

/* --- anything a chat card offers --------------------------------------------- */

/** Taps the newest untaken button with this id in a chat, as if the visitor
 *  pressed it there. Lets a desk button reuse exactly what the chat does. */
export function tapLatest(s: DemoState, thread: ThreadId, actionId: string): Outcome {
  const msgs = s.threads[thread].messages;
  for (let i = msgs.length - 1; i >= 0; i--) {
    const m = msgs[i]!;
    const a = !m.chosen ? m.actions?.find((x) => x.id === actionId) : undefined;
    if (a) return tap(s, thread, m.id, a);
  }
  return {};
}

export function approveMany(s: DemoState, ids: string[]): Outcome {
  return combine(...ids.map((id) => approve(s, id)), { now: (st) => ({ ...st, desk: { ...st.desk, tour: { ...st.desk.tour, inbox: true } } }) });
}

export function setRules(s: DemoState, patch: Partial<Rules>): DemoState {
  return { ...s, desk: { ...s.desk, rules: { ...s.desk.rules, ...patch } } };
}

/** Value of quotes still open (not won, not lost) — the desk's "money waiting". */
export function openQuoteValue(pipeline: PipeQuote[]): number {
  return pipeline.filter((q) => q.stage !== "won" && q.stage !== "lost").reduce((a, q) => a + q.value, 0);
}
