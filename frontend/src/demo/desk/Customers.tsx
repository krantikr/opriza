import { useMemo, useState } from "react";
import { roundQty } from "../data/generate";
import { shortName } from "../engine/core";
import { remindMany } from "../engine/desk";
import type { Grade } from "../engine/types";
import { clock, money, shortDate } from "../lib/format";
import type { Ctx, PageParams } from "./ctx";
import { IArrow, IChat, ISend } from "./icons";
import { customerById, customerQuotes, oldestLate, trendOf } from "./select";
import { age, Empty, GradeTag, PageHead, Panel, StageTag, Tabs } from "./ui";

type Sort = "owes" | "sales" | "late" | "last";

export default function Customers({ ctx, params }: { ctx: Ctx; params: PageParams }) {
  const w = ctx.s.world;
  const [q, setQ] = useState("");
  const [grade, setGrade] = useState<Grade | "all">((params.grade as Grade) ?? "all");
  const [sort, setSort] = useState<Sort>("owes");
  const counts = { A: 0, B: 0, C: 0, D: 0 } as Record<Grade, number>;
  for (const c of w.customers) counts[c.grade]++;

  const rows = useMemo(() => {
    const list = w.customers
      .filter((c) => (grade === "all" ? true : c.grade === grade))
      .filter((c) => (q ? `${c.name} ${c.contact} ${c.area} ${c.rep}`.toLowerCase().includes(q.toLowerCase()) : true));
    const key = { owes: (c: (typeof list)[number]) => -c.outstanding, sales: (c: (typeof list)[number]) => -c.sales12m, late: (c: (typeof list)[number]) => -oldestLate(c), last: (c: (typeof list)[number]) => -c.lastBuyDays }[sort];
    return [...list].sort((a, b) => key(a) - key(b));
  }, [w, grade, q, sort]);

  return (
    <>
      <PageHead title="Customers" sub={`${w.customers.length} active customers, graded by how they pay. Grades update after every payment.`} />
      <Panel pad={false}>
        <div className="dk-filters">
          <input type="search" placeholder="Search name, contact, area or salesperson" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search customers" />
          <div className="dk-chips" role="group" aria-label="Grade">
            <button type="button" aria-pressed={grade === "all"} onClick={() => setGrade("all")}>All {w.customers.length}</button>
            {(["A", "B", "C", "D"] as Grade[]).map((g) => (
              <button key={g} type="button" aria-pressed={grade === g} onClick={() => setGrade(g)}>
                <GradeTag g={g} /> {counts[g]}
              </button>
            ))}
          </div>
          <label className="dk-filter">
            Sort by
            <select value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
              <option value="owes">Owes most</option>
              <option value="sales">Biggest buyers</option>
              <option value="late">Most days late</option>
              <option value="last">Longest since last order</option>
            </select>
          </label>
        </div>
        <table className="dk-table">
          <thead>
            <tr><th>Customer</th><th>Grade</th><th className="r">12-month sales</th><th className="r">Owes now</th><th className="r">Avg delay</th><th className="r">Last order</th><th>Trend</th><th>Salesperson</th></tr>
          </thead>
          <tbody>
            {rows.map((c) => {
              const t = trendOf(c);
              const late = oldestLate(c);
              return (
                <tr key={c.id} onClick={() => ctx.drawer({ type: "customer", id: c.id })}>
                  <td><b>{c.name}</b><small>{c.contact} · {c.area}</small></td>
                  <td><GradeTag g={c.grade} /></td>
                  <td className="r num">{money(c.sales12m)}</td>
                  <td className="r num">{money(c.outstanding)}{late > 0 && <small className={late >= 15 ? "bad" : "warn"}>{late} d late</small>}</td>
                  <td className="r">{c.avgDelay} d</td>
                  <td className={`r ${c.lastBuyDays > 30 ? "bad" : ""}`}>{c.lastBuyDays} d ago</td>
                  <td><span className={`dk-trend ${t}`}>{t === "up" ? "▲ Growing" : t === "down" ? "▼ Slipping" : "— Steady"}</span></td>
                  <td>{c.rep}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!rows.length && <Empty title="No customers match." />}
      </Panel>
    </>
  );
}

/* ---------------------------------------------------------------------------
   One customer, in the side drawer
   --------------------------------------------------------------------------- */

type CTab = "overview" | "bills" | "quotes" | "activity";

export function CustomerPanel({ ctx, id }: { ctx: Ctx; id: string }) {
  const s = ctx.s;
  const w = s.world;
  const c = customerById(w, id);
  const [tab, setTab] = useState<CTab>("overview");
  const late = oldestLate(c);
  const quotes = customerQuotes(s, c.id);
  const promises = s.desk.promises.filter((p) => p.customerId === c.id);
  const log = s.desk.log.filter((l) => l.customerId === c.id);
  const limit = Math.round((c.outstanding * (c.grade === "A" ? 2.8 : c.grade === "B" ? 2.2 : 1.6)) / 1e5) * 1e5;
  const p = w.products[Number(c.id.slice(1)) % 3]!;
  const reminded = s.desk.reminded[c.id] !== undefined;

  return (
    <div className="dk-dp">
      <span className="k">Customer since {c.since} · {c.area} · {c.rep}</span>
      <h2>{c.name}</h2>
      <div className="dk-dp-tags">
        <GradeTag g={c.grade} />
        <span className="muted">{c.contact} · {c.phone}</span>
      </div>

      <div className="dk-kgrid">
        <div><span>Owes now</span><b className={late > 0 ? "neg" : ""}>{money(c.outstanding)}</b><small>{late > 0 ? `${late} days late` : "Nothing overdue"}</small></div>
        <div><span>12-month sales</span><b>{money(c.sales12m)}</b><small>Last order {c.lastBuyDays} days ago</small></div>
        <div><span>Pays on average</span><b>{c.avgDelay} days late</b><small>Usually day {c.payDay}</small></div>
        <div><span>Promises kept</span><b>{c.promisesKept} of {c.promisesMade}</b><small>Credit limit {money(limit)}</small></div>
      </div>

      <div className="dk-dp-acts">
        {late > 0 && (
          <button type="button" className="btn btn-go btn-sm" disabled={reminded} onClick={() => { ctx.run(remindMany(ctx.s, [c.id])); ctx.toast(`Statement link sent to ${c.contact}`); }}>
            <ISend /> {reminded ? "Reminder sent" : "Send reminder"}
          </button>
        )}
        <button type="button" className="btn btn-line btn-sm" onClick={() => { ctx.drawer(null); ctx.chat("sales", `quote ${roundQty(p.qty[0], p.unit)} ${p.unit} ${shortName(p)} for ${c.name}`); }}>Make a quote</button>
        <button type="button" className="btn btn-line btn-sm" onClick={() => ctx.link({ type: "customerStatement", customerId: c.id })}>Their statement link</button>
        <button type="button" className="btn btn-ghost-d btn-sm" onClick={() => { ctx.drawer(null); ctx.chat("ask", `How is ${c.name} doing?`); }}><IChat size={16} /> Ask about {c.name.split(" ")[0]}</button>
      </div>

      <Tabs<CTab> value={tab} onChange={setTab} items={[{ id: "overview", label: "Overview" }, { id: "bills", label: "Bills", count: c.bills.length }, { id: "quotes", label: "Quotes", count: quotes.length }, { id: "activity", label: "Activity", count: log.length + promises.length }]} />

      {tab === "overview" && (
        <div className="dk-dp-sec">
          <h3>Why grade {c.grade}</h3>
          <ul className="dk-reasons">
            {c.grade === "A" && <li className="up">Pays within {c.avgDelay} days of the due date</li>}
            {c.grade !== "A" && <li className={c.grade === "B" ? "" : "down"}>Pays {c.avgDelay} days late on average</li>}
            <li className={c.promisesKept === c.promisesMade ? "up" : "down"}>Kept {c.promisesKept} of {c.promisesMade} payment promises</li>
            <li className={c.lastBuyDays > 30 ? "down" : "up"}>{c.lastBuyDays > 30 ? `No order for ${c.lastBuyDays} days` : `Buys regularly — last order ${c.lastBuyDays} days ago`}</li>
          </ul>
          <h3>Agent's suggestion</h3>
          <p className="dk-sugg">
            {c.grade === "A" && `Good payer. Offer them 1% early-payment discount on the next big order.`}
            {c.grade === "B" && `Keep the ${money(limit)} limit. Remind ${s.desk.rules.remindDays} days before the due date.`}
            {c.grade === "C" && `Call before sending new stock. Ask 25% advance on orders above ${money(c.outstanding * 0.5)}.`}
            {c.grade === "D" && `Hold new credit. Collect at least half of ${money(c.outstanding)} before the next dispatch.`}
          </p>
        </div>
      )}

      {tab === "bills" && (
        <table className="dk-table compact">
          <thead><tr><th>Bill</th><th>Date</th><th className="r">Amount</th><th>Status</th></tr></thead>
          <tbody>
            {c.bills.map((b) => (
              <tr key={b.no}>
                <td>{b.no}</td>
                <td>{shortDate(b.date)}</td>
                <td className="r num">{money(b.amount)}</td>
                <td className={b.daysLate > 0 ? (b.daysLate >= 15 ? "bad" : "warn") : "muted"}>{b.daysLate > 0 ? `${b.daysLate} days late` : b.daysLate === 0 ? "Due today" : `Due in ${-b.daysLate} days`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {tab === "quotes" && (
        <ul className="dk-list">
          {quotes.map((q) => (
            <li key={q.no}>
              <button type="button" className="dk-list-main" onClick={() => ctx.drawer({ type: "quote", no: q.no })}>
                <StageTag stage={q.stage} />
                <span><b>{q.no} · {money(q.value)}</b><small>{q.product} · {age(q.ageH)} ago</small></span>
              </button>
            </li>
          ))}
          {!quotes.length && <li className="dk-list-empty">No quotes in the last 30 days.</li>}
        </ul>
      )}

      {tab === "activity" && (
        <ul className="dk-feed">
          {promises.map((pr) => (
            <li key={pr.id}>
              <span className="dk-dot due" aria-hidden="true" />
              <span>Promised {money(pr.amount)} on {pr.date} · <b className={pr.status === "missed" ? "bad" : pr.status === "kept" ? "good" : ""}>{pr.status}</b></span>
              <time>{pr.by === "customer" ? "link" : "call"}</time>
            </li>
          ))}
          {log.map((l) => (
            <li key={l.id}>
              <span className="dk-dot ok" aria-hidden="true" />
              <span>{l.text}</span>
              <time>{l.yday ? "Yest" : clock(l.at)}</time>
            </li>
          ))}
          {!promises.length && !log.length && <li className="dk-list-empty">Nothing yet today.</li>}
        </ul>
      )}

      <div className="dk-dp-links">
        <button type="button" className="dk-link" onClick={() => ctx.go("collect", { tab: "dues" })}>All dues <IArrow /></button>
      </div>
    </div>
  );
}
