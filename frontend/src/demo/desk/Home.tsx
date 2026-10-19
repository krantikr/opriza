import { approve, tap } from "../engine/respond";
import type { DemoState } from "../engine/types";
import { clock, money, qty } from "../lib/format";
import type { Ctx } from "./ctx";
import { IArrow, IPhone } from "./icons";
import { callWhy, chaseOrder, inboxItems, inboxTitle, moneyWaiting, oldestLate, stockRows, type InboxItem } from "./select";
import { Avatar, GradeTag, Meter, PageHead, Panel } from "./ui";

export function handledCount(s: DemoState) {
  return s.desk.log.reduce((a, l) => a + l.count, 0);
}

/** A chat button's words, short enough for a list row: "Share quote link
 *  with customer" → "Share quote link". */
export function shortLabel(label: string): string {
  if (label.length <= 20) return label;
  const words = label.split(" ");
  let out = "";
  for (const w of words) {
    if ((out + " " + w).trim().length > 18) break;
    out = (out + " " + w).trim();
  }
  return out.replace(/\s+(to|for|with|from|the|a|and|of|in|on)$/i, "");
}

/** The one button that does what the agent recommends for an inbox item. */
export function primaryOf(ctx: Ctx, it: InboxItem) {
  if (it.kind === "approval")
    return {
      label: "Approve",
      run: () => {
        ctx.run(approve(ctx.s, it.approval.id));
        ctx.set((s) => ({ ...s, desk: { ...s.desk, tour: { ...s.desk.tour, inbox: true } } }));
      },
    };
  const a = it.actions.find((x) => x.primary) ?? it.actions[0]!;
  return {
    label: shortLabel(a.label),
    run: () => {
      ctx.run(tap(ctx.s, it.thread, it.msg.id, a));
      ctx.set((s) => ({ ...s, desk: { ...s.desk, tour: { ...s.desk.tour, inbox: true } } }));
    },
  };
}

export default function Home({ ctx }: { ctx: Ctx }) {
  const s = ctx.s;
  const w = s.world;
  const items = inboxItems(s);
  const mw = moneyWaiting(s);
  const rows = stockRows(s);
  const atRisk = rows.filter((r) => r.status === "reorder");
  const low = w.cash[2]!.inflow - w.cash[2]!.outflow;
  const recovered = s.collectedToday + s.wonToday;
  const hour = Math.floor(s.clock / 60);
  const greet = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  const collectedWeek = Math.round(w.kpi.inThisWeek * 0.58) + s.collectedToday;

  const needs = (
    <Panel title="Needs you" sub="Each one has the agent's draft ready" right={<button type="button" className="dk-link" onClick={() => ctx.go("inbox")}>Open Inbox ({items.length}) <IArrow /></button>} pad={false}>
      <ul className="dk-list">
        {items.slice(0, 5).map((it) => {
          const { title, sub } = inboxTitle(s, it);
          const p = primaryOf(ctx, it);
          const t = s.threads[it.kind === "approval" ? it.approval.thread : it.thread];
          return (
            <li key={it.key}>
              <button type="button" className="dk-list-main" onClick={() => ctx.go("inbox", { tab: it.key })}>
                <Avatar t={t} size={30} />
                <span>
                  <b>{title}</b>
                  <small>{it.kind === "approval" ? <><span className="dk-why">{it.approval.why}</span> · {sub}</> : sub}</small>
                </span>
              </button>
              <button type="button" className="btn btn-go btn-xs" onClick={p.run}>{p.label}</button>
            </li>
          );
        })}
        {!items.length && <li className="dk-list-empty">All clear. The agents will post here when something needs you.</li>}
      </ul>
    </Panel>
  );

  const calls = (
    <Panel title="Today's call list" sub="Ranked by amount, days late and how each customer pays" right={<button type="button" className="dk-link" onClick={() => ctx.go("collect")}>Open Collections <IArrow /></button>} pad={false}>
      <ul className="dk-list">
        {chaseOrder(w).slice(0, 5).map((c) => (
          <li key={c.id}>
            <button type="button" className="dk-list-main" onClick={() => ctx.drawer({ type: "customer", id: c.id })}>
              <GradeTag g={c.grade} />
              <span>
                <b>{c.name} · {money(c.outstanding)}</b>
                <small>{oldestLate(c)} days late · {callWhy(c)}</small>
              </span>
            </button>
            <button type="button" className="btn btn-line btn-xs" onClick={() => ctx.go("collect")}><IPhone /> Call</button>
          </li>
        ))}
      </ul>
    </Panel>
  );

  const enquiries = (
    <Panel title="Enquiries waiting for a quote" right={<button type="button" className="dk-link" onClick={() => ctx.go("sales", { tab: "enquiries" })}>Open Sales <IArrow /></button>} pad={false}>
      <ul className="dk-list">
        {s.desk.enquiries.filter((e) => !e.quoted).map((e) => {
          const c = w.customers.find((x) => x.id === e.customerId)!;
          return (
            <li key={e.id}>
              <button type="button" className="dk-list-main" onClick={() => ctx.go("sales", { tab: "enquiries" })}>
                <span className={`dk-age ${e.ageMin > 30 ? "late" : ""}`}>{e.ageMin < 60 ? `${e.ageMin}m` : `${Math.round(e.ageMin / 60)}h`}</span>
                <span>
                  <b>{c.name}</b>
                  <small>{e.channel} · “{e.text}”</small>
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </Panel>
  );

  const stock = (
    <Panel title="Stock at risk" right={<button type="button" className="dk-link" onClick={() => ctx.go("stock")}>Open Stock <IArrow /></button>} pad={false}>
      <ul className="dk-list">
        {rows.filter((r) => r.status !== "ok").map((r) => (
          <li key={r.i}>
            <button type="button" className="dk-list-main" onClick={() => ctx.drawer({ type: "product", idx: r.i })}>
              <span className={`dk-dot ${r.status}`} aria-hidden="true" />
              <span>
                <b>{r.short}</b>
                <small>{r.status === "idle" ? `Idle 100 days · ${money(w.kpi.idleValue)} stuck` : `${r.days} days left · sells ${qty(r.p.perDay, r.p.unit)}/day`}</small>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </Panel>
  );

  const first = ctx.role === "accounts" ? calls : ctx.role === "sales" ? enquiries : ctx.role === "purchase" ? stock : needs;
  const pendingFor = ctx.role === "owner" ? items.length : ctx.role === "accounts" ? chaseOrder(w).length : ctx.role === "sales" ? s.desk.enquiries.filter((e) => !e.quoted).length : atRisk.length;
  const what = ctx.role === "owner" ? "things need you" : ctx.role === "accounts" ? "customers to follow up" : ctx.role === "sales" ? "enquiries to quote" : "items to reorder";

  return (
    <>
      <PageHead
        title={`${greet}, ${w.firstName}`}
        sub={
          <>
            <b>{pendingFor} {what}</b> · agents handled <b>{handledCount(s)} tasks</b> since yesterday · data from Tally at {clock(s.clock - 2)}
          </>
        }
      />

      <div className="dk-money">
        <button type="button" onClick={() => ctx.go("sales")}>
          <span className="k">In open quotes</span>
          <b>{money(mw.quotes)}</b>
          <small>{s.desk.pipeline.filter((q) => q.stage !== "won" && q.stage !== "lost").length + 1} quotes being followed up</small>
        </button>
        <button type="button" onClick={() => ctx.go("collect")}>
          <span className="k">Overdue you can collect</span>
          <b>{money(mw.collectable)}</b>
          <small>From customers who usually pay after a reminder or call</small>
        </button>
        <button type="button" onClick={() => ctx.go("stock")}>
          <span className="k">Stuck in idle stock</span>
          <b>{money(mw.idle)}</b>
          <small>Unsold 60+ days — offers ready</small>
        </button>
        <div className={`won ${recovered ? "on" : ""}`}>
          <span className="k">Promised or won in this demo</span>
          <b>{money(recovered)}</b>
          <small>{recovered ? "Updates as you work" : "Approve, remind or quote to see it move"}</small>
        </div>
      </div>

      <div className="dk-kpis">
        <button type="button" onClick={() => ctx.go("reports", { report: "sales" })}>
          <span>Sales this month</span>
          <b>{money(w.kpi.salesMtd + s.wonToday)}</b>
          <small className="good">▲ {w.kpi.mtdChange}% vs last month</small>
        </button>
        <button type="button" onClick={() => ctx.go("collect")}>
          <span>Collected this week</span>
          <b>{money(collectedWeek)}</b>
          <Meter value={collectedWeek} max={w.kpi.inThisWeek} tone="good" />
          <small>Target {money(w.kpi.inThisWeek)}</small>
        </button>
        <button type="button" onClick={() => ctx.go("collect", { tab: "dues" })}>
          <span>Overdue</span>
          <b>{money(w.kpi.overdue)}</b>
          <small className="bad">{w.kpi.overdueCount} customers · {w.kpi.dso} days to collect</small>
        </button>
        <button type="button" onClick={() => ctx.go("stock")}>
          <span>Stock at risk</span>
          <b>{atRisk.length} item{atRisk.length === 1 ? "" : "s"}</b>
          <small className={atRisk.length ? "bad" : ""}>Under {s.desk.rules.reorderDays} days of stock</small>
        </button>
        <button type="button" onClick={() => ctx.go("cash")}>
          <span>Cash low point</span>
          <b className={low < 0 ? "neg" : ""}>{money(low)}</b>
          <small className={low < 0 ? "bad" : ""}>Week 3 · fixes ready</small>
        </button>
      </div>

      <div className="dk-grid2">
        {first}
        <Panel title="Agents' work" sub="What they did, newest first" pad={false}>
          <ul className="dk-feed">
            {s.desk.log.slice(0, 8).map((l) => (
              <li key={l.id}>
                <Avatar t={s.threads[l.agent]} size={26} />
                <span>
                  <b>{s.threads[l.agent].name}</b> {l.text}
                </span>
                <time>{l.yday ? `Yest ${clock(l.at)}` : clock(l.at)}</time>
              </li>
            ))}
          </ul>
        </Panel>
      </div>

      <div className="dk-grid2">
        <Panel title="Cash, next 4 weeks" sub="From bills, payment habits and supplier dues in Tally" right={<button type="button" className="dk-link" onClick={() => ctx.go("cash")}>Open Cash <IArrow /></button>}>
          <CashBars s={s} />
        </Panel>
        <Panel title="Sales, last 7 days" sub={`${money(w.kpi.salesYesterday)} yesterday · ▲ ${w.kpi.vsAverage}% vs average`}>
          <div className="dk-bars">
            {w.sales7.map((d, i) => {
              const max = Math.max(...w.sales7.map((x) => x.value));
              return (
                <div key={i} className="col">
                  <span className="v">{d.value ? money(d.value) : "—"}</span>
                  <i style={{ height: `${(d.value / max) * 100}%` }} className={i === w.sales7.length - 2 ? "hi" : ""} />
                  <span className="l">{d.label}</span>
                </div>
              );
            })}
          </div>
        </Panel>
      </div>
    </>
  );
}

export function CashBars({ s, shift = 0, early = 0, delay = 0 }: { s: DemoState; shift?: number; early?: number; delay?: number }) {
  const weeks = s.world.cash.map((wk, i) => ({
    ...wk,
    // What-ifs: a late payer moves money from week 2 to week 4; early
    // payments add to week 3; a moved supplier payment shifts week 3 to 4.
    inflow: wk.inflow + (i === 1 ? -shift : 0) + (i === 3 ? shift : 0) + (i === 2 ? early : 0),
    outflow: wk.outflow - (i === 2 ? delay : 0) + (i === 3 ? delay : 0),
  }));
  const max = Math.max(...weeks.flatMap((w) => [w.inflow, w.outflow]));
  return (
    <div className="dk-cash">
      <div className="dk-cash-key">
        <span><i className="in" /> Coming in</span>
        <span><i className="out" /> Going out</span>
      </div>
      <div className="dk-cash-cols">
        {weeks.map((wk) => {
          const net = wk.inflow - wk.outflow;
          return (
            <div key={wk.label} className={`wk ${net < 0 ? "short" : ""}`}>
              <div className="bars">
                <i className="in" style={{ height: `${(wk.inflow / max) * 100}%` }} title={`In ${money(wk.inflow)}`} />
                <i className="out" style={{ height: `${(wk.outflow / max) * 100}%` }} title={`Out ${money(wk.outflow)}`} />
              </div>
              <b className={net < 0 ? "neg" : "pos"}>{net < 0 ? "" : "+"}{money(net)}</b>
              <span>{wk.label.replace("Wk", "Week")}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
