import { useMemo, useState } from "react";

import { api } from "../../api/client";
import { IPhone, ISend } from "../../demo/desk/icons";
import { Check, Empty, GradeTag, PageHead, Panel, Tabs } from "../../demo/desk/ui";
import type { Grade } from "../../demo/engine/types";
import { Status } from "../bits";
import { useDesk } from "../ctx";
import { day, money, useData, type Collections as Data } from "../data";

type View = "dues" | "calls" | "promises";

export default function Collections() {
  const ctx = useDesk();
  const { data } = useData<Data>("/app/collections", 30000);
  const [view, setView] = useState<View>((ctx.params.tab as View) ?? "dues");
  const [bucket, setBucket] = useState<string | null>(null);
  const [ticked, setTicked] = useState<Set<number>>(new Set());
  const [q, setQ] = useState("");

  const rows = useMemo(() => {
    let r = data?.dues ?? [];
    if (bucket) r = r.filter((d) => d.bucket === bucket);
    if (q.trim()) r = r.filter((d) => d.name.toLowerCase().includes(q.trim().toLowerCase()));
    return r;
  }, [data, bucket, q]);
  if (!data) return <Empty title="Loading…" />;

  const late = data.buckets.filter((b) => b.key !== "current");
  const totalLate = late.reduce((a, b) => a + b.amount, 0);
  const pick = rows.filter((d) => ticked.has(d.party_id));
  const send = () =>
    ctx.act(() => api.post("/app/collections/remind", { party_ids: pick.map((d) => d.party_id) }),
      `Reminders sent to ${pick.length} customers, each with a link to pick a payment date.`).then(() => setTicked(new Set()));

  return (
    <>
      <PageHead title="Collections" sub={<>The Collections agent reminds before due dates, sends statements, and keeps today's calls. <b>{money(totalLate)}</b> is overdue.</>} />
      <Panel title="Overdue by age" sub="Tap a bar to see who's in it">
        <div className="dk-ageing">
          {late.map((b, i) => (
            <button key={b.key} type="button" className={`seg s${i + 1} ${bucket === b.key ? "on" : ""}`}
              style={{ flexGrow: Math.max(0.12, b.amount / Math.max(1, totalLate)) }}
              onClick={() => { setBucket(bucket === b.key ? null : b.key); setView("dues"); }}>
              <b>{money(b.amount)}</b>
              <span>{b.label} · {b.count} bills</span>
            </button>
          ))}
        </div>
      </Panel>

      <Tabs value={view} onChange={setView} items={[
        { id: "dues", label: "Who owes", count: data.dues.filter((d) => d.overdue > 1).length },
        { id: "calls", label: "Today's calls", count: data.calls.length },
        { id: "promises", label: "Promises", count: data.promises.filter((p) => p.status === "open").length },
      ]} />

      {view === "dues" && (
        <Panel pad={false}>
          <div className="dk-filters op-pad">
            <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a customer" aria-label="Find a customer" />
            {bucket && <button type="button" className="dk-link" onClick={() => setBucket(null)}>Show all ages</button>}
          </div>
          {pick.length > 0 && (
            <div className="dk-bulk">
              <b>{pick.length} selected · {money(pick.reduce((a, c) => a + c.amount, 0))}</b>
              <button type="button" className="btn btn-go btn-sm" onClick={() => void send()}><ISend /> Send reminders ({pick.length})</button>
              <button type="button" className="dk-link" onClick={() => setTicked(new Set())}>Clear</button>
            </div>
          )}
          <table className="dk-table">
            <thead>
              <tr>
                <th className="ck"><Check on={rows.length > 0 && rows.slice(0, 50).every((d) => ticked.has(d.party_id))} onChange={(v) => setTicked(new Set(v ? rows.slice(0, 50).map((d) => d.party_id) : []))} label="Select all" /></th>
                <th>Customer</th><th>Grade</th><th className="r">Owes</th><th className="r">Overdue</th><th className="r">Oldest</th><th>Usually pays</th><th>Last message</th>
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 200).map((d) => (
                <tr key={d.party_id} className={ticked.has(d.party_id) ? "sel" : ""} onClick={() => ctx.drawer({ type: "customer", id: d.party_id })}>
                  <td className="ck"><Check on={ticked.has(d.party_id)} onChange={(v) => setTicked((old) => { const n = new Set(old); if (v) n.add(d.party_id); else n.delete(d.party_id); return n; })} label={`Select ${d.name}`} /></td>
                  <td><b>{d.name}</b><small>{d.area} · {d.bills} bills</small></td>
                  <td>{d.grade && <GradeTag g={d.grade as Grade} />}</td>
                  <td className="r num">{money(d.amount)}</td>
                  <td className={`r num ${d.overdue > 1 ? "bad" : "muted"}`}>{d.overdue > 1 ? money(d.overdue) : "—"}</td>
                  <td className={`r num ${d.oldest > 30 ? "bad" : d.oldest > 0 ? "warn" : "muted"}`}>{d.oldest ? `${d.oldest} d` : "—"}</td>
                  <td className="muted">{d.pay_day ? `${d.pay_day} days after bill` : "—"}</td>
                  <td className="muted">{day(d.last_message_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}

      {view === "calls" && (
        <Panel title="Today's calls" sub="Biggest and latest first, with what to say" pad={false}>
          <ul className="dk-list">
            {data.calls.map((t) => (
              <li key={t.id}>
                <button type="button" className="dk-list-main" onClick={() => t.entity_type === "party" && t.entity_id && ctx.drawer({ type: "customer", id: t.entity_id })}>
                  <span className={`dk-pill ${t.priority === 1 ? "bad" : "warn"}`}>{t.kind === "missed_promise" ? "Missed" : "Call"}</span>
                  <span><b>{t.title}</b><small>{t.detail}{t.why[0] ? ` · ${t.why[0]}` : ""}</small></span>
                </button>
                <span className="op-row-acts">
                  {t.entity_type === "party" && <button type="button" className="btn btn-line btn-xs" onClick={() => t.entity_id && ctx.drawer({ type: "customer", id: t.entity_id })}><IPhone /> Call</button>}
                  <button type="button" className="btn btn-ghost-d btn-xs" onClick={() => void ctx.act(() => api.post(`/app/tasks/${t.id}`, { status: "done" }), "Done.")}>Done</button>
                </span>
              </li>
            ))}
            {!data.calls.length && <li className="dk-list-empty">No calls today.</li>}
          </ul>
        </Panel>
      )}

      {view === "promises" && (
        <Panel title="Payment promises" sub="From calls and from the dates customers pick on their statement link" pad={false}>
          <table className="dk-table">
            <thead><tr><th>Customer</th><th className="r">Amount</th><th>Made</th><th>Due</th><th>From</th><th>Status</th></tr></thead>
            <tbody>
              {data.promises.map((p) => (
                <tr key={p.id} onClick={() => ctx.drawer({ type: "customer", id: p.party_id })}>
                  <td><b>{p.party}</b></td><td className="r num">{money(p.amount)}</td><td>{day(p.made_on)}</td><td>{day(p.due_date)}</td>
                  <td className="muted">{p.source}</td><td><Status s={p.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}
    </>
  );
}
