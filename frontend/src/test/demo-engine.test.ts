import { beforeEach, describe, expect, it } from "vitest";
import { buildWorld } from "../demo/data/generate";
import { INDUSTRIES } from "../demo/data/industries";
import { answer, detectIntent, findAmount, findProduct, findQty } from "../demo/engine/ask";
import { chaseOrder, quoteTotals } from "../demo/engine/core";
import { approveMany, cashAskEarly, cashDelay, makePo, moveQuote, remindMany } from "../demo/engine/desk";
import { approve, tap } from "../demo/engine/respond";
import { createDemo } from "../demo/engine/seed";
import { saveDemoLead } from "../demo/lib/lead";
import type { Business, DemoState, ThreadId } from "../demo/engine/types";

const BIZ: Business = {
  company: "Shree Balaji Steels",
  owner: "Kranti Karan",
  city: "Pune",
  industry: "steel",
  revenue: "100-250",
  team: "10–25",
  tally: "TallyPrime",
  language: "Hinglish",
  problems: ["collections", "quotes"],
};
const TODAY = new Date(2026, 9, 19);

/** Runs an outcome to the end, the way the UI does, without waiting. */
function play(s: DemoState, o: ReturnType<typeof tap>): DemoState {
  let st = o.now ? o.now(s) : s;
  for (const step of o.later ?? []) st = step.run(st);
  return st;
}

describe("buildWorld", () => {
  it("is the same for the same answers", () => {
    const a = buildWorld(BIZ, TODAY);
    const b = buildWorld(BIZ, TODAY);
    expect(a.customers.map((c) => c.name)).toEqual(b.customers.map((c) => c.name));
    expect(a.kpi).toEqual(b.kpi);
  });

  it("builds a sane business for every trade", () => {
    for (const ind of INDUSTRIES) {
      const w = buildWorld({ ...BIZ, industry: ind.id }, TODAY);
      expect(w.products).toHaveLength(6);
      expect(w.customers.length).toBeGreaterThan(5);
      for (const p of w.products) {
        expect(p.cost).toBeLessThan(p.rate);
        expect(p.stock).toBeGreaterThan(0);
        expect(p.perDay).toBeGreaterThan(0);
      }
      expect(w.kpi.overdue).toBeLessThan(w.kpi.receivable);
      // Week 3 is the planned cash gap in every demo.
      expect(w.cash[2]!.outflow).toBeGreaterThan(w.cash[2]!.inflow);
    }
  });
});

describe("understanding questions", () => {
  const w = buildWorld(BIZ, TODAY);

  it("reads quantities and amounts", () => {
    expect(findQty("quote 120 MT TMT")).toBe(120);
    expect(findQty("need 2,000 bags")).toBe(2000);
    expect(findAmount("who owes more than ₹50 lakh")).toBe(50e5);
    expect(findAmount("above 2 crore")).toBe(2e7);
  });

  it("does not mistake a size for a quantity", () => {
    expect(findQty("price of 12mm tmt")).toBeUndefined();
  });

  it("quotes the product the visitor named, in every trade", () => {
    for (const ind of INDUSTRIES) {
      const wi = buildWorld({ ...BIZ, industry: ind.id }, TODAY);
      for (const p of wi.products) {
        expect(findProduct(wi, `quote 100 ${p.unit} ${p.name} for ${wi.customers[0]!.name}`)?.name, `${ind.id}: ${p.name}`).toBe(p.name);
      }
    }
  });

  it("tells PPC cement from OPC cement", () => {
    const wb = buildWorld({ ...BIZ, industry: "building" }, TODAY);
    expect(findProduct(wb, "quote 300 bags PPC cement for Raj Developers")?.name).toBe("PPC cement");
    expect(findProduct(wb, "rate for cement")?.name).toBe("OPC 53 cement");
    expect(findProduct(wb, "need waterproofing")?.name).toBe("Waterproofing 20L");
  });

  it("finds products by alias", () => {
    expect(findProduct(w, "rate for saria")?.name).toBe("TMT 12mm Fe500D");
    expect(findProduct(w, "hr coil stock")?.name).toBe("HR coil 2mm");
  });

  it.each([
    ["Who owes me the most?", "overdue"],
    ["kitna baaki hai", "overdue"],
    ["Who stopped buying?", "inactive"],
    ["Kaun se customer ne kharidna band kiya?", "inactive"],
    ["Margin by month", "margin"],
    ["Sales this week", "sales"],
    ["Show idle stock", "idle"],
    ["What should I reorder this week?", "reorder"],
    ["Cash position today", "cash"],
    ["quote 40 MT TMT 12mm", "quote"],
    ["hello", "greet"],
    ["asdf qwerty", "unknown"],
  ])("%s → %s", (q, intent) => {
    expect(detectIntent(w, q)).toBe(intent);
  });

  it("answers every intent with a message", () => {
    const s = createDemo(w);
    for (const q of ["Who owes me the most?", "Top 5 customers", "Margin by month", "Sales this week", "Cash this week", "Payments due this week", "Which customers are grade D?", "Promises due this week", "nonsense words"]) {
      const { msgs } = answer(s, q);
      expect(msgs).toHaveLength(1);
      expect(msgs[0]!.text || msgs[0]!.card).toBeTruthy();
    }
  });

  it("turns a typed enquiry into a priced quote for the named customer", () => {
    const s = createDemo(w);
    const c = w.customers[3]!;
    const { msgs } = answer(s, `quote 50 MT HR coil for ${c.name}`);
    const card = msgs[0]!.card;
    expect(card?.kind).toBe("quote");
    if (card?.kind === "quote") {
      expect(card.customer).toBe(c.name);
      expect(card.lines[0]!.qty).toBe(50);
      expect(card.lines[0]!.name).toBe("HR coil 2mm");
      const t = quoteTotals(card);
      expect(t.total).toBeGreaterThan(t.sub);
    }
  });
});

describe("tapping buttons", () => {
  const w = buildWorld(BIZ, TODAY);

  it("opens the chats for the picked problems first", () => {
    const s = createDemo(w);
    expect(s.order.slice(0, 3)).toEqual(["brief", "sales", "collect"]);
    expect(s.threads.collect.unread).toBeGreaterThan(0);
    expect(s.threads.stock.unread).toBe(0);
  });

  it("sharing a quote marks it sent and the agent follows up", () => {
    const s = createDemo(w);
    const quoteMsg = s.threads.sales.messages.find((m) => m.card?.kind === "quote")!;
    const share = quoteMsg.actions!.find((a) => a.id === "quote-share")!;
    const after = play(s, tap(s, "sales", quoteMsg.id, share));
    const updated = after.threads.sales.messages.find((m) => m.id === quoteMsg.id)!;
    expect(updated.card?.kind === "quote" && updated.card.status).toBe("sent");
    expect(after.threads.sales.messages.length).toBeGreaterThan(s.threads.sales.messages.length);
  });

  it("every opening button gets a reply", () => {
    const s = createDemo(w);
    for (const id of Object.keys(s.threads) as ThreadId[]) {
      for (const m of s.threads[id].messages) {
        for (const a of m.actions ?? []) {
          const o = tap(s, id, m.id, a);
          if (a.id.startsWith("go-") || a.id.startsWith("view-")) {
            expect(o.ui).toBeTruthy();
            continue;
          }
          const after = play(s, o);
          expect(after.threads[id].messages.length, `${id}/${a.id}`).toBeGreaterThan(s.threads[id].messages.length);
        }
      }
    }
  });

  it("a drafted PO replaces the waiting one, and approving it posts the card", () => {
    let s = createDemo(w);
    const reorder = s.threads.stock.messages.find((m) => m.card?.kind === "reorder")!;
    s = play(s, tap(s, "stock", reorder.id, reorder.actions!.find((a) => a.id === "order-last")!));
    const pos = s.approvals.filter((a) => a.type === "Purchase order" && a.status === "waiting");
    expect(pos).toHaveLength(1);
    s = play(s, approve(s, pos[0]!.id));
    const poCard = s.threads.stock.messages.map((m) => m.card).find((c) => c?.kind === "po");
    expect(poCard?.kind === "po" && poCard.status).toBe("posted");
  });
});

describe("desktop actions", () => {
  const w = buildWorld({ ...BIZ, industry: "building" }, TODAY);

  it("headline overdue figures match the bills", () => {
    const late = w.customers.filter((c) => c.bills.some((b) => b.daysLate > 0));
    const sum = late.reduce((a, c) => a + c.bills.filter((b) => b.daysLate > 0).reduce((x, b) => x + b.amount, 0), 0);
    expect(w.kpi.overdueCount).toBe(late.length);
    expect(Math.abs(w.kpi.overdue - sum)).toBeLessThan(1e5);
  });

  it("a customer's yearly sales cover what they owe", () => {
    for (const c of w.customers) expect(c.sales12m, c.name).toBeGreaterThan(c.outstanding * 0.9);
  });

  it("reminding several customers logs the work, ticks the tour and brings a promise", () => {
    const s = createDemo(w);
    const ids = chaseOrder(w).slice(0, 3).map((c) => c.id);
    const after = play(s, remindMany(s, ids));
    expect(after.desk.tour.remind).toBe(true);
    expect(Object.keys(after.desk.reminded)).toEqual(expect.arrayContaining(ids));
    expect(after.collectedToday).toBeGreaterThan(0);
    expect(after.threads.collect.messages.length).toBeGreaterThan(s.threads.collect.messages.length);
  });

  it("moving a quote to Won counts it and tells the Sales chat", () => {
    const s = createDemo(w);
    const q = s.desk.pipeline.find((x) => x.stage === "sent")!;
    const after = play(s, moveQuote(s, q.no, "won"));
    expect(after.desk.pipeline.find((x) => x.no === q.no)!.stage).toBe("won");
    expect(after.wonToday).toBe(q.value);
    expect(after.threads.sales.messages.at(-1)!.card?.kind).toBe("won");
  });

  it("a PO above the buyer's limit waits for approval", () => {
    const s = createDemo(w);
    const tight = { ...s, world: { ...s.world, limits: { ...s.world.limits, poLimit: 1e5 } } };
    const after = play(tight, makePo(tight, 0, 0));
    expect(after.approvals.filter((a) => a.type === "Purchase order" && a.status === "waiting").length).toBeGreaterThan(tight.approvals.filter((a) => a.type === "Purchase order" && a.status === "waiting").length);
  });

  it("cash fixes close the short week", () => {
    const s = createDemo(w);
    const after = play(s, cashDelay(s));
    const done = play(after, cashAskEarly(after));
    expect(done.desk.cashFix.delayed).toBe(true);
    expect(done.desk.cashFix.early).toBeGreaterThan(0);
  });

  it("approving many at once clears them and ticks the tour", () => {
    const s = createDemo(w);
    const ids = s.approvals.filter((a) => a.status === "waiting").map((a) => a.id);
    const after = play(s, approveMany(s, ids));
    expect(after.approvals.filter((a) => a.status === "waiting")).toHaveLength(0);
    expect(after.desk.tour.inbox).toBe(true);
  });
});

describe("saving a demo sign-up", () => {
  const biz: Business = { ...BIZ, email: " karan@kktraders.in ", phone: "98765 43210", problems: ["quotes", "collections"] };

  function fakeFetch(ok = true) {
    const calls: { url: string; body: Record<string, unknown> }[] = [];
    const f = (async (url: string, init?: RequestInit) => {
      calls.push({ url, body: JSON.parse(String(init?.body)) });
      return { ok } as Response;
    }) as unknown as typeof fetch;
    return { f, calls };
  }

  beforeEach(() => localStorage.clear());

  it("sends the contact and business details once", async () => {
    const { f, calls } = fakeFetch();
    expect(await saveDemoLead(biz, f)).toBe("sent");
    expect(calls).toHaveLength(1);
    expect(calls[0]!.url).toBe("/api/v1/leads/demo");
    expect(calls[0]!.body).toMatchObject({
      name: "Kranti Karan",
      company: "Shree Balaji Steels",
      email: "karan@kktraders.in",
      phone: "98765 43210",
      city: "Pune",
      industry: "steel",
      revenue: "100-250",
      tally: "TallyPrime",
      problems: ["Slow quotes", "Late payments"],
    });
    expect(String(calls[0]!.body.industry_label)).toMatch(/Steel/);
    expect(calls[0]!.body).not.toHaveProperty("language");
  });

  it("skips the same answers, but sends again when they change", async () => {
    const { f, calls } = fakeFetch();
    await saveDemoLead(biz, f);
    expect(await saveDemoLead(biz, f)).toBe("skipped");
    expect(await saveDemoLead({ ...biz, industry: "pharma" }, f)).toBe("sent");
    expect(calls).toHaveLength(2);
  });

  it("tries again next time when saving failed", async () => {
    const bad = fakeFetch(false);
    expect(await saveDemoLead(biz, bad.f)).toBe("failed");
    const good = fakeFetch();
    expect(await saveDemoLead(biz, good.f)).toBe("sent");
  });

  it("never throws when the network is down", async () => {
    const down = (async () => {
      throw new Error("offline");
    }) as unknown as typeof fetch;
    expect(await saveDemoLead(biz, down)).toBe("failed");
  });
});
