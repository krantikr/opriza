import { useState } from "react";

import { Empty, GradeTag, PageHead, Panel } from "../../demo/desk/ui";
import type { Grade } from "../../demo/engine/types";
import { useDesk } from "../ctx";
import { day, money, useData, type CustomerRow } from "../data";

export default function Customers() {
  const ctx = useDesk();
  const [q, setQ] = useState("");
  const [grade, setGrade] = useState("");
  const { data } = useData<CustomerRow[]>(`/app/customers?${new URLSearchParams({ ...(q.trim() ? { q: q.trim() } : {}), ...(grade ? { grade } : {}) })}`);
  return (
    <>
      <PageHead title="Customers" sub="Graded A to D from how they actually pay, with the reasons. Click a customer for everything." />
      <Panel pad={false}>
        <div className="dk-filters op-pad">
          <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a customer" aria-label="Find a customer" />
          <div className="dk-chips" role="group" aria-label="Grade">
            {["", "A", "B", "C", "D"].map((g) => (
              <button key={g || "all"} type="button" aria-pressed={grade === g} onClick={() => setGrade(g)}>{g ? `Grade ${g}` : "All grades"}</button>
            ))}
          </div>
        </div>
        {!data ? <Empty title="Loading…" /> : (
          <table className="dk-table">
            <thead><tr><th>Customer</th><th>Grade</th><th className="r">Sales, 12 months</th><th className="r">Owes</th><th className="r">Overdue</th><th className="r">Days late</th><th>Last order</th><th>Trend</th></tr></thead>
            <tbody>
              {data.map((c) => (
                <tr key={c.party_id} onClick={() => ctx.drawer({ type: "customer", id: c.party_id })}>
                  <td><b>{c.name}</b><small>{c.area} · {c.contact}</small></td>
                  <td><GradeTag g={c.grade as Grade} />{c.previous_grade && c.previous_grade !== c.grade && <small className="muted"> was {c.previous_grade}</small>}</td>
                  <td className="r num">{money(c.sales_12m)}</td>
                  <td className="r num">{money(c.outstanding)}</td>
                  <td className={`r num ${c.overdue > 1 ? "bad" : "muted"}`}>{c.overdue > 1 ? money(c.overdue) : "—"}</td>
                  <td className="r num">{Math.round(c.avg_days_late)}</td>
                  <td>{day(c.last_order_on)}</td>
                  <td><span className={`dk-trend ${c.trend}`}>{c.trend === "up" ? "▲ Up" : c.trend === "down" ? "▼ Down" : "Steady"}</span></td>
                </tr>
              ))}
              {!data.length && <tr><td colSpan={8}><Empty title="No customers match" /></td></tr>}
            </tbody>
          </table>
        )}
      </Panel>
    </>
  );
}
