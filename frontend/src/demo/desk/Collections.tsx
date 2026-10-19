import { useMemo, useState } from "react";
import { callResult, remindMany } from "../engine/desk";
import type { Customer, Grade } from "../engine/types";
import { addDays, clock, dayDate, money } from "../lib/format";
import type { Ctx, PageParams } from "./ctx";
import { IPhone, ISend } from "./icons";
import { ageing, BUCKETS, bucketOf, callScript, callWhy, chaseOrder, customerById, oldestLate, type BucketKey } from "./select";
import { Check, Empty, GradeTag, Meter, PageHead, Panel, Tabs } from "./ui";

type View = "calls" | "dues" | "promises";

export default function Collections({ ctx, params }: { ctx: Ctx; params: PageParams }) {
  const s = ctx.s;
  const w = s.world;
  const [view, setView] = useState<View>((params.tab as View) ?? (params.bucket ? "dues" : "calls"));
  const [bucket, setBucket] = useState<BucketKey | "all">(params.bucket ?? "all");
  const buckets = ageing(s);
  const totalLate = buckets.reduce((a, b) => a + b.amount, 0);
  const open = s.desk.promises.filter((p) => p.status === "due");
  const remindedToday = Object.keys(s.desk.reminded).length;
  const late = chaseOrder(w);
  const notReminded = late.filter((c) => s.desk.reminded[c.id] === undefined && c.grade !== "D");

  return (
    <>
      <PageHead title="Collections" sub="Who should we collect from today, and what do we say?">
        <button type="button" className="btn btn-go btn-sm" disabled={!notReminded.length} onClick={() => { ctx.run(remindMany(ctx.s, notReminded.map((c) => c.id))); ctx.toast(`Statement links sent to ${notReminded.length} customers`); }}>
          <ISend /> Remind all due ({notReminded.length})
        </button>
      </PageHead>

      <div className="dk-stats">
        <div><span>Overdue</span><b className="neg">{money(w.kpi.overdue)}</b><small>{late.length} customers</small></div>
        <div><span>Promised, not yet paid</span><b>{money(open.reduce((a, p) => a + p.amount, 0))}</b><small>{open.length} promises</small></div>
        <div><span>Promised in this demo</span><b className={s.collectedToday ? "pos" : ""}>{money(s.collectedToday)}</b><small>{s.collectedToday ? "from your reminders and calls" : "send reminders to see it move"}</small></div>
        <div><span>Days to collect</span><b>{w.kpi.dso} days</b><small>target {w.kpi.dso - 5} in 90 days</small></div>
        <div><span>Reminders sent today</span><b>{remindedToday}</b><small>{Math.max(6, Math.round(w.kpi.overdueCount * 0.6))} more went last night</small></div>
      </div>

      <Panel title="Overdue by days late" sub="Click a band to see who is in it" right={bucket !== "all" ? <button type="button" className="dk-link" onClick={() => setBucket("all")}>Show all</button> : undefined}>
        <div className="dk-ageing">
          {buckets.map((b, i) => (
            <button
              key={b.key}
              type="button"
              className={`seg s${i} ${bucket === b.key ? "on" : ""}`}
              style={{ flexGrow: Math.max(0.12, b.amount / Math.max(1, totalLate)) }}
              onClick={() => {
                setBucket(b.key);
                setView("dues");
              }}
            >
              <b>{money(b.amount)}</b>
              <span>{b.label} · {b.count}</span>
            </button>
          ))}
        </div>
      </Panel>

      <div className="dk-bar">
        <Tabs<View>
          value={view}
          onChange={setView}
          items={[
            { id: "calls", label: "Today's calls", count: Math.min(8, late.length) },
            { id: "dues", label: "All dues", count: late.length },
            { id: "promises", label: "Promises", count: open.length },
          ]}
        />
      </div>

      {view === "calls" && <Calls ctx={ctx} list={late.slice(0, 8)} />}
      {view === "dues" && <Dues ctx={ctx} bucket={bucket} setBucket={setBucket} />}
      {view === "promises" && <Promises ctx={ctx} />}
    </>
  );
}

function lastTouch(ctx: Ctx, c: Customer): string {
  const at = ctx.s.desk.reminded[c.id];
  if (at !== undefined) return `Reminder sent ${clock(at)}`;
  const p = ctx.s.desk.promises.find((x) => x.customerId === c.id);
  if (p) return p.status === "missed" ? `Missed promise · ${p.date}` : p.status === "due" ? `Promised ${money(p.amount)} · ${p.date}` : "Paid last promise";
  return "No reminder yet today";
}

function Calls({ ctx, list }: { ctx: Ctx; list: Customer[] }) {
  const [active, setActive] = useState<string | null>(null);
  const [done, setDone] = useState<Record<string, string>>({});
  const log = (c: Customer, r: "promise" | "half" | "nr" | "dispute", label: string) => {
    ctx.run(callResult(ctx.s, c.id, r));
    setDone((d) => ({ ...d, [c.id]: label }));
    setActive(null);
  };
  return (
    <div className="dk-calls">
      {list.map((c, i) => {
        const late = oldestLate(c);
        const isOn = active === c.id;
        return (
          <div key={c.id} className={`dk-call ${done[c.id] ? "done" : ""} ${isOn ? "on" : ""}`}>
            <span className="rank">{i + 1}</span>
            <div className="who">
              <button type="button" className="dk-cell-link" onClick={() => ctx.drawer({ type: "customer", id: c.id })}>{c.name}</button>
              <small><GradeTag g={c.grade} /> {c.contact} · {c.phone} · {c.rep}</small>
            </div>
            <div className="amt">
              <b>{money(c.outstanding)}</b>
              <small className={late >= 15 ? "bad" : ""}>{late} day{late === 1 ? "" : "s"} late · {c.bills.length} bills</small>
            </div>
            <div className="say">
              <small className="dk-call-why">{callWhy(c)}</small>
              <span>{callScript(ctx.s, c)}</span>
              <small className="muted">{lastTouch(ctx, c)}</small>
            </div>
            <div className="dk-call-acts">
              {done[c.id] ? (
                <span className="dk-ok">✓ {done[c.id]}</span>
              ) : isOn ? (
                <div className="dk-outcomes" role="group" aria-label="How did the call go?">
                  <button type="button" className="btn btn-go btn-xs" onClick={() => log(c, "promise", "Promised full")}>Promised full</button>
                  <button type="button" className="btn btn-line btn-xs" onClick={() => log(c, "half", "Promised half")}>Half now</button>
                  <button type="button" className="btn btn-line btn-xs" onClick={() => log(c, "nr", "No answer")}>No answer</button>
                  <button type="button" className="btn btn-line btn-xs" onClick={() => log(c, "dispute", "Dispute flagged")}>Disputes a bill</button>
                </div>
              ) : (
                <>
                  <button type="button" className="btn btn-go btn-xs" onClick={() => setActive(c.id)}><IPhone /> Call</button>
                  <button type="button" className="btn btn-line btn-xs" disabled={ctx.s.desk.reminded[c.id] !== undefined} onClick={() => ctx.run(remindMany(ctx.s, [c.id]))}>{ctx.s.desk.reminded[c.id] !== undefined ? "Reminded" : "Remind"}</button>
                </>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Dues({ ctx, bucket, setBucket }: { ctx: Ctx; bucket: BucketKey | "all"; setBucket: (b: BucketKey | "all") => void }) {
  const s = ctx.s;
  const w = s.world;
  const [grade, setGrade] = useState<Grade | "all">("all");
  const [rep, setRep] = useState("all");
  const [q, setQ] = useState("");
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const rows = useMemo(
    () =>
      chaseOrder(w)
        .filter((c) => (bucket === "all" ? true : bucketOf(c) === bucket))
        .filter((c) => (grade === "all" ? true : c.grade === grade))
        .filter((c) => (rep === "all" ? true : c.rep === rep))
        .filter((c) => (q ? `${c.name} ${c.contact} ${c.area}`.toLowerCase().includes(q.toLowerCase()) : true)),
    [w, bucket, grade, rep, q],
  );
  const pick = rows.filter((c) => ticked.has(c.id));
  const maxLate = Math.max(...rows.map((c) => oldestLate(c)), 1);
  const send = () => {
    ctx.run(remindMany(ctx.s, pick.map((c) => c.id)));
    ctx.toast(`Statement links sent to ${pick.length} customer${pick.length === 1 ? "" : "s"}`);
    setTicked(new Set());
  };

  return (
    <Panel pad={false}>
      <div className="dk-filters">
        <input type="search" placeholder="Search customer, contact or area" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search dues" />
        <div className="dk-chips" role="group" aria-label="Grade">
          {(["all", "A", "B", "C", "D"] as const).map((g) => (
            <button key={g} type="button" aria-pressed={grade === g} onClick={() => setGrade(g)}>{g === "all" ? "All grades" : `Grade ${g}`}</button>
          ))}
        </div>
        <div className="dk-chips" role="group" aria-label="Days late">
          <button type="button" aria-pressed={bucket === "all"} onClick={() => setBucket("all")}>Any age</button>
          {BUCKETS.map((b) => (
            <button key={b.key} type="button" aria-pressed={bucket === b.key} onClick={() => setBucket(b.key)}>{b.label}</button>
          ))}
        </div>
        <select value={rep} onChange={(e) => setRep(e.target.value)} aria-label="Salesperson">
          <option value="all">All salespeople</option>
          {w.team.sales.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
      </div>

      {pick.length > 0 && (
        <div className="dk-bulk">
          <b>{pick.length} selected · {money(pick.reduce((a, c) => a + c.outstanding, 0))}</b>
          <button type="button" className="btn btn-go btn-sm" onClick={send}><ISend /> Send reminders ({pick.length})</button>
          <button type="button" className="dk-link" onClick={() => setTicked(new Set())}>Clear</button>
        </div>
      )}

      <table className="dk-table">
        <thead>
          <tr>
            <th className="ck"><Check on={rows.length > 0 && rows.every((c) => ticked.has(c.id))} onChange={(v) => setTicked(new Set(v ? rows.map((c) => c.id) : []))} label="Select all" /></th>
            <th>Customer</th><th>Grade</th><th className="r">Overdue</th><th>Days late</th><th>Last touch</th><th>Salesperson</th><th />
          </tr>
        </thead>
        <tbody>
          {rows.map((c) => {
            const late = oldestLate(c);
            const overdue = c.bills.filter((b) => b.daysLate > 0).reduce((a, b) => a + b.amount, 0);
            return (
              <tr key={c.id} className={ticked.has(c.id) ? "sel" : ""} onClick={() => ctx.drawer({ type: "customer", id: c.id })}>
                <td className="ck"><Check on={ticked.has(c.id)} onChange={(v) => setTicked((o) => { const n = new Set(o); if (v) n.add(c.id); else n.delete(c.id); return n; })} label={`Select ${c.name}`} /></td>
                <td><b>{c.name}</b><small>{c.contact} · {c.area}</small></td>
                <td><GradeTag g={c.grade} /></td>
                <td className="r num">{money(overdue)}</td>
                <td><span className="dk-late"><Meter value={late} max={maxLate} tone={late >= 15 ? "bad" : "warn"} /><span>{late} d</span></span></td>
                <td className="muted">{lastTouch(ctx, c)}</td>
                <td>{c.rep}</td>
                <td className="r" onClick={(e) => e.stopPropagation()}>
                  <button type="button" className="btn btn-line btn-xs" disabled={s.desk.reminded[c.id] !== undefined} onClick={() => ctx.run(remindMany(ctx.s, [c.id]))}>{s.desk.reminded[c.id] !== undefined ? "Sent" : "Remind"}</button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {!rows.length && <Empty title="Nobody matches these filters." />}
    </Panel>
  );
}

function Promises({ ctx }: { ctx: Ctx }) {
  const s = ctx.s;
  const w = s.world;
  const days = Array.from({ length: 7 }, (_, i) => i);
  const due = s.desk.promises.filter((p) => p.status === "due").sort((a, b) => a.inDays - b.inDays);
  const missed = s.desk.promises.filter((p) => p.status === "missed");
  const kept = s.desk.promises.filter((p) => p.status === "kept");
  const perDay = days.map((d) => due.filter((p) => p.inDays === d).reduce((a, p) => a + p.amount, 0));
  const max = Math.max(...perDay, 1);
  return (
    <div className="dk-grid2 wide-l">
      <Panel title="Promised money, next 7 days" sub="Customers picked these dates on their statement link, or told you on a call" pad={false}>
        <div className="dk-week">
          {days.map((d) => (
            <div key={d} className={d === 0 ? "today" : ""}>
              <span className="v">{perDay[d] ? money(perDay[d]!) : ""}</span>
              <i style={{ height: `${(perDay[d]! / max) * 100}%` }} />
              <span className="l">{d === 0 ? "Today" : dayDate(addDays(w.today, d)).slice(0, 3)}</span>
            </div>
          ))}
        </div>
        <table className="dk-table">
          <thead><tr><th>When</th><th>Customer</th><th className="r">Amount</th><th>How</th></tr></thead>
          <tbody>
            {due.map((p) => {
              const c = customerById(w, p.customerId);
              return (
                <tr key={p.id} onClick={() => ctx.drawer({ type: "customer", id: c.id })}>
                  <td className={p.inDays === 0 ? "hl" : ""}>{p.inDays === 0 ? "Today" : p.date}</td>
                  <td><b>{c.name}</b><small>{c.contact} · {c.phone}</small></td>
                  <td className="r num">{money(p.amount)}</td>
                  <td className="muted">{p.by === "customer" ? "Picked on link" : "Told on a call"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Panel>
      <div className="dk-stack">
        <Panel title="Missed" sub="The agent alerts you the morning after" pad={false}>
          <ul className="dk-list">
            {missed.map((p) => {
              const c = customerById(w, p.customerId);
              return (
                <li key={p.id}>
                  <button type="button" className="dk-list-main" onClick={() => ctx.drawer({ type: "customer", id: c.id })}>
                    <GradeTag g={c.grade} />
                    <span><b>{c.name} · {money(p.amount)}</b><small className="bad">Promised {p.date}</small></span>
                  </button>
                  <button type="button" className="btn btn-go btn-xs" onClick={() => { ctx.go("collect", { tab: "calls" }); }}><IPhone /> Call</button>
                </li>
              );
            })}
            {!missed.length && <li className="dk-list-empty">None missed.</li>}
          </ul>
        </Panel>
        <Panel title="Kept this week" pad={false}>
          <ul className="dk-list">
            {kept.map((p) => {
              const c = customerById(w, p.customerId);
              return (
                <li key={p.id}>
                  <span className="dk-list-main static"><span className="dk-ok">✓</span><span><b>{c.name} · {money(p.amount)}</b><small>Paid {p.date} · matched to bills in Tally</small></span></span>
                </li>
              );
            })}
          </ul>
        </Panel>
      </div>
    </div>
  );
}
