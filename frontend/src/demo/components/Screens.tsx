import { chaseOrder, oldestLate, shortName } from "../engine/core";
import type { DemoState, ThreadId, World } from "../engine/types";
import { clock, money, pct, qty, rate } from "../lib/format";
import CardView from "./CardView";

/* ---------------------------------------------------------------------------
   Approvals
   --------------------------------------------------------------------------- */

type ApprovalsProps = { state: DemoState; onApprove: (id: string) => void; onChange: (id: string) => void };

export function Approvals({ state, onApprove, onChange }: ApprovalsProps) {
  const waiting = state.approvals.filter((a) => a.status === "waiting").length;
  return (
    <div className="screen">
      <header className="screen-head">
        <h1>Approvals</h1>
        <p>{waiting ? `${waiting} waiting for you.` : "All clear."} Everything inside your rules went out on its own.</p>
      </header>
      <div className="screen-body">
        <div className="apgrid">
          {state.approvals.map((a) => (
            <article className="panel ap" key={a.id}>
              <div className="ch">
                <span className="tag neutral">{a.type}</span>
                <span className="csub">{a.who}</span>
              </div>
              <div className="tt">{a.title}</div>
              <div className="dd">{a.detail}</div>
              <div className="wy">{a.why}</div>
              {a.status === "waiting" && (
                <div className="row2">
                  <button type="button" className="btn btn-go btn-sm" onClick={() => onApprove(a.id)}>Approve</button>
                  <button type="button" className="btn btn-line btn-sm" onClick={() => onChange(a.id)}>Send back</button>
                </div>
              )}
              {a.status === "approved" && <div className="done">✓ Approved. {a.after}</div>}
              {a.status === "changed" && <div className="chg">Sent back to {a.who.split(" · ")[0]} to revise.</div>}
            </article>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------------------
   Today
   --------------------------------------------------------------------------- */

type TodayProps = { state: DemoState; onOpen: (id: ThreadId) => void };

export function Today({ state, onOpen }: TodayProps) {
  const w = state.world;
  const k = w.kpi;
  const short = w.cash[2]!.outflow - w.cash[2]!.inflow;
  const top = chaseOrder(w)[0]!;
  const p0 = w.products[0]!;
  return (
    <div className="screen">
      <header className="screen-head">
        <h1>Today</h1>
        <p>{w.biz.company} · from Tally at {clock(state.clock - 2)}</p>
      </header>
      <div className="screen-body">
        <div className="tiles">
          <div className="panel tile"><div className="tl">Sales this month</div><div className="tv">{money(k.salesMtd + state.wonToday)}</div><div className="tn good">▲ {k.mtdChange}% vs last month</div></div>
          <div className="panel tile"><div className="tl">Owed to you</div><div className="tv">{money(k.receivable)}</div><div className="tn bad">{k.dso} days to collect</div></div>
          <div className="panel tile"><div className="tl">Stock value</div><div className="tv">{money(k.stockValue)}</div><div className="tn muted">{money(k.idleValue)} idle 60+ days</div></div>
          <div className="panel tile"><div className="tl">To pay, 30 days</div><div className="tv">{money(k.payables30)}</div><div className="tn muted">{k.payablesCount} suppliers</div></div>
        </div>
        {(state.wonToday > 0 || state.collectedToday > 0) && (
          <div className="tiles">
            {state.wonToday > 0 && <div className="panel tile"><div className="tl">Won in this demo</div><div className="tv" style={{ color: "var(--good)" }}>{money(state.wonToday)}</div></div>}
            {state.collectedToday > 0 && <div className="panel tile"><div className="tl">Promised or collected</div><div className="tv" style={{ color: "var(--good)" }}>{money(state.collectedToday)}</div></div>}
          </div>
        )}
        <div className="two">
          <div className="panel"><CardView card={{ kind: "cashweeks", weeks: w.cash }} onGo={() => {}} /></div>
          <div className="panel" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <h2>Needs attention</h2>
            <button type="button" className="btn btn-line" style={{ justifyContent: "space-between" }} onClick={() => onOpen("cash")}>
              <span>Week 3 is {money(short)} short</span><span aria-hidden="true">›</span>
            </button>
            <button type="button" className="btn btn-line" style={{ justifyContent: "space-between" }} onClick={() => onOpen("collect")}>
              <span>{top.name} · {money(top.outstanding)} · {oldestLate(top)}d late</span><span aria-hidden="true">›</span>
            </button>
            <button type="button" className="btn btn-line" style={{ justifyContent: "space-between" }} onClick={() => onOpen("stock")}>
              <span>{shortName(p0)} · {Math.round(p0.stock / p0.perDay)} days of stock</span><span aria-hidden="true">›</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------------------
   Settings
   --------------------------------------------------------------------------- */

type SettingsProps = { state: DemoState; onLimits: (l: World["limits"]) => void };

export function Settings({ state, onLimits }: SettingsProps) {
  const w = state.world;
  const l = w.limits;
  const auto = Math.max(40, Math.min(97, Math.round(85 - (l.marginFloor - 3) * 8 + (l.maxDiscount - 1.5) * 4)));
  const step = (key: "marginFloor" | "maxDiscount", by: number) => onLimits({ ...l, [key]: Math.max(0, Math.round((l[key] + by) * 10) / 10) });
  return (
    <div className="screen">
      <header className="screen-head">
        <h1>Settings</h1>
        <p>Rules you set once. Oprisa follows them.</p>
      </header>
      <div className="screen-body">
        <div className="two">
          <section className="panel">
            <h2>Price band</h2>
            <div className="csub" style={{ marginTop: 2 }}>Quotes inside the band go out without you.</div>
            <div className="set-row">
              <div>Minimum margin<small>Below this, you approve</small></div>
              <div className="stepper">
                <button type="button" aria-label="Lower minimum margin" onClick={() => step("marginFloor", -0.5)}>−</button>
                <span>{pct(l.marginFloor)}</span>
                <button type="button" aria-label="Raise minimum margin" onClick={() => step("marginFloor", 0.5)}>+</button>
              </div>
            </div>
            <div className="set-row">
              <div>Max discount<small>vs the customer's last rate</small></div>
              <div className="stepper">
                <button type="button" aria-label="Lower max discount" onClick={() => step("maxDiscount", -0.5)}>−</button>
                <span>{pct(l.maxDiscount)}</span>
                <button type="button" aria-label="Raise max discount" onClick={() => step("maxDiscount", 0.5)}>+</button>
              </div>
            </div>
            <div className="status">About {auto}% of last month's quotes would go out without you.</div>
          </section>
          <section className="panel">
            <h2>Team limits</h2>
            <div className="set-row"><span>{w.team.sales.join(", ")} · sales</span><span className="csub">Quotes inside band</span></div>
            <div className="set-row"><span>{w.team.purchase} · purchase</span><span className="csub num">POs up to {money(l.poLimit)}</span></div>
            <div className="set-row"><span>{w.team.accounts} · accounts</span><span className="csub">Reminders, receipts</span></div>
          </section>
          <section className="panel">
            <h2>Alerts</h2>
            <div className="set-row"><span>Morning brief</span><b className="num">8:00 am</b></div>
            <div className="set-row"><span>Urgent alerts</span><b>Max 5 a day</b></div>
            <div className="set-row"><span>Quiet hours 9 pm – 8 am</span><button type="button" className="switch" role="switch" aria-checked="true" aria-label="Quiet hours" /></div>
            <div className="set-row"><span>Language</span><b>{w.biz.language}</b></div>
          </section>
          <section className="panel">
            <h2>Tally</h2>
            <div className="set-row"><div>Sync app · OFFICE-PC<small>{w.biz.tally} · every 15 minutes</small></div><span className="tag good">{clock(state.clock - 2)} ✓</span></div>
            <div className="set-row"><span>Reads</span><span className="csub">Sales, receipts, stock, bills, ledgers</span></div>
            <div className="set-row"><span>Writes, after your approval</span><span className="csub">Sales orders, POs, credit limits</span></div>
          </section>
        </div>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------------------
   Side panel on wide screens: the record behind the open chat
   --------------------------------------------------------------------------- */

export function SidePanel({ state, thread }: { state: DemoState; thread: ThreadId | null }) {
  const w = state.world;
  if (thread === "collect" || thread === "score") {
    const c = thread === "score" ? w.customers[4]! : chaseOrder(w)[state.queueIndex] ?? chaseOrder(w)[0]!;
    return (
      <div className="side">
        <div className="lbl">Customer</div>
        <div className="ch"><h2>{c.name}</h2><span className="tag warn">Grade {c.grade}</span></div>
        <div className="csub">{c.contact} · {c.phone} · since {c.since}</div>
        <div className="kgrid">
          <div className="kp"><div className="kl">Owes you</div><div className="kv">{money(c.outstanding)}</div></div>
          <div className="kp"><div className="kl">Avg delay</div><div className="kv">{c.avgDelay} days</div></div>
          <div className="kp"><div className="kl">12-month sales</div><div className="kv">{money(c.sales12m)}</div></div>
          <div className="kp"><div className="kl">Promises kept</div><div className="kv">{c.promisesKept} of {c.promisesMade}</div></div>
        </div>
        <div className="lbl">Open bills</div>
        <div className="lines">
          {c.bills.map((b) => (
            <div className="ln" key={b.no}><span>{b.no}</span><span>{money(b.amount)} · {b.daysLate > 0 ? `${b.daysLate}d late` : `due in ${-b.daysLate}d`}</span></div>
          ))}
        </div>
      </div>
    );
  }
  if (thread === "stock") {
    return (
      <div className="side">
        <div className="lbl">Days of stock left</div>
        {w.products.map((p) => {
          const d = Math.round(p.stock / p.perDay);
          return (
            <div key={p.key} className="cov">
              <div className="ch"><span style={{ fontSize: 13.5, fontWeight: 600 }}>{shortName(p)}</span><span className="num" style={{ fontSize: 13, fontWeight: 800, color: d < 12 ? "var(--bad)" : undefined }}>{d} d</span></div>
              <div className="bar"><b style={{ width: `${Math.min(100, (d / 45) * 100)}%`, background: d < 12 ? "var(--bad)" : d < 20 ? "var(--saffron)" : "var(--faint)" }} /></div>
              <div className="csub">{qty(p.stock, p.unit)} · sells {qty(p.perDay, p.unit)}/day · {rate(p.rate, p.unit)}</div>
            </div>
          );
        })}
      </div>
    );
  }
  if (thread === "sales") {
    // Follows the newest quote in the chat, including ones the visitor typed.
    const lastQuote = [...state.threads.sales.messages].reverse().map((m) => m.card).find((k) => k?.kind === "quote");
    const named = lastQuote?.kind === "quote" ? w.customers.find((x) => x.name === lastQuote.customer) : undefined;
    const c = named ?? w.customers[2]!;
    return (
      <div className="side">
        <div className="lbl">Customer on the latest quote</div>
        <h2>{c.name}</h2>
        <div className="csub">{c.contact} · {c.phone}</div>
        <div className="kgrid">
          <div className="kp"><div className="kl">Grade</div><div className="kv">{c.grade}</div></div>
          <div className="kp"><div className="kl">12-month sales</div><div className="kv">{money(c.sales12m)}</div></div>
          <div className="kp"><div className="kl">Owes you</div><div className="kv">{money(c.outstanding)}</div></div>
          <div className="kp"><div className="kl">Last order</div><div className="kv">{c.lastBuyDays}d ago</div></div>
        </div>
        <div className="lbl">This month</div>
        <div className="kgrid">
          <div className="kp"><div className="kl">Quotes sent</div><div className="kv">{142 + state.seq.quote - 1187}</div></div>
          <div className="kp"><div className="kl">Avg quote time</div><div className="kv">7 min</div></div>
        </div>
      </div>
    );
  }
  return (
    <div className="side">
      <div className="lbl">At a glance</div>
      <div className="kgrid">
        <div className="kp"><div className="kl">Sold yesterday</div><div className="kv">{money(w.kpi.salesYesterday)}</div></div>
        <div className="kp"><div className="kl">Overdue</div><div className="kv">{money(w.kpi.overdue)}</div></div>
        <div className="kp"><div className="kl">Stock value</div><div className="kv">{money(w.kpi.stockValue)}</div></div>
        <div className="kp"><div className="kl">To pay, 7 days</div><div className="kv">{money(w.kpi.payables7)}</div></div>
      </div>
      <div className="panel" style={{ padding: 12 }}><CardView card={{ kind: "cashweeks", weeks: w.cash }} onGo={() => {}} /></div>
    </div>
  );
}
