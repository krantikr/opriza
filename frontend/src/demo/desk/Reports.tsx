import { useMemo, useState } from "react";
import CardView from "../components/CardView";
import { answer } from "../engine/ask";
import type { Card, DemoState } from "../engine/types";
import { money } from "../lib/format";
import type { Ctx, PageParams } from "./ctx";
import { IChat, IDownload } from "./icons";
import { PageHead, Panel, Toggle } from "./ui";

/* ---------------------------------------------------------------------------
   Ready reports: the questions owners ask most, answered from the same data
   the chat uses, so a report and a chat answer never disagree.
   --------------------------------------------------------------------------- */

type Report = { id: string; group: string; title: string; q?: string; build?: (s: DemoState) => Card };

/** Customers who owe a lot and have stopped ordering: the riskiest dues. */
function owesNoOrder(s: DemoState): Card {
  const w = s.world;
  const sorted = [...w.customers].sort((a, b) => b.outstanding - a.outstanding);
  const bar = sorted[Math.floor(sorted.length / 4)]!.outstanding;
  const rows = w.customers.filter((c) => c.outstanding >= bar && c.lastBuyDays > 30);
  const list = rows.length ? rows : sorted.filter((c) => c.lastBuyDays > 20).slice(0, 5);
  return {
    kind: "table",
    title: `Owe over ${money(bar)} and no order in 30 days`,
    cols: ["Customer", "Owes", "Last order", "Grade"],
    align: ["l", "r", "r", "r"],
    rows: list.map((c) => [c.name, money(c.outstanding), `${c.lastBuyDays} days ago`, c.grade]),
    footnote: "Call before the next dispatch; the agent can send a statement link to each.",
  };
}

const REPORTS: Report[] = [
  { id: "owe", group: "Money owed", title: "Who owes the most", q: "Who owes me the most?" },
  { id: "risky", group: "Money owed", title: "Owes a lot, stopped ordering", build: owesNoOrder },
  { id: "promises", group: "Money owed", title: "Promises due this week", q: "Promises due this week" },
  { id: "gradeD", group: "Money owed", title: "Grade D customers", q: "Which customers are grade D?" },
  { id: "sales", group: "Sales", title: "Sales this week", q: "Sales this week" },
  { id: "margin", group: "Sales", title: "Margin by month", q: "Margin by month" },
  { id: "top", group: "Sales", title: "Top 5 customers", q: "Top 5 customers" },
  { id: "inactive", group: "Sales", title: "Customers who stopped buying", q: "Who stopped buying?" },
  { id: "open", group: "Sales", title: "Quotes still open", q: "Which quotes are still open?" },
  { id: "win", group: "Sales", title: "Win rate this month", q: "What's my win rate this month?" },
  { id: "idle", group: "Stock", title: "Stock idle 60+ days", q: "Show idle stock" },
  { id: "reorder", group: "Stock", title: "What to reorder this week", q: "What should I reorder this week?" },
  { id: "cash", group: "Cash", title: "Cash for the next 4 weeks", q: "Cash position today" },
  { id: "payables", group: "Cash", title: "Supplier payments due", q: "Payments due this week" },
];

function cardOf(s: DemoState, r: Report): { card?: Card; text?: string } {
  if (r.build) return { card: r.build(s) };
  const m = answer(s, r.q!).msgs[0];
  return { card: m?.card, text: m?.text };
}

/** The report as rows, for Excel. */
function toRows(card: Card | undefined, text?: string): string[][] {
  if (!card) return [[(text ?? "").replace(/\*\*/g, "")]];
  switch (card.kind) {
    case "table":
      return [card.cols, ...card.rows];
    case "bars":
      return [["Period", card.unit ?? "Value"], ...card.bars.map((b) => [b.label, b.display])];
    case "queue":
      return [["Customer", "Amount", "Status"], ...card.rows.map((r) => [r.name, money(r.amount), r.tag])];
    case "cashweeks":
      return [["Week", "Coming in", "Going out", "Net"], ...card.weeks.map((w) => [w.label, money(w.inflow), money(w.outflow), money(w.inflow - w.outflow)])];
    case "kpis":
      return [["Measure", "Value"], ...card.kpis.map((k) => [k.label, k.value])];
    case "idle":
      return [["Item", "Quantity", "Value", "Days idle"], [card.product, `${card.qty} ${card.unit}`, money(card.value), String(card.days)]];
    case "reorder":
      return [["Item", "In stock", "Days left", "Suggested order"], [card.product, `${card.stock} ${card.unit}`, String(card.daysLeft), `${card.suggest} ${card.unit}`]];
    default:
      return [[(text ?? "").replace(/\*\*/g, "")]];
  }
}

function download(name: string, rows: string[][]) {
  const csv = rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(",")).join("\r\n");
  const url = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `${name}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function Reports({ ctx, params }: { ctx: Ctx; params: PageParams }) {
  const s = ctx.s;
  const w = s.world;
  const [id, setId] = useState(REPORTS.find((r) => r.id === params.report)?.id ?? "owe");
  const [weekly, setWeekly] = useState<Set<string>>(new Set());
  const r = REPORTS.find((x) => x.id === id)!;
  const out = useMemo(() => cardOf(s, r), [s, r]);
  const groups = [...new Set(REPORTS.map((x) => x.group))];

  return (
    <>
      <PageHead title="Reports" sub="Answers to the questions owners ask most, kept current from Tally. Any chat answer works the same way." />
      <div className="dk-split">
        <nav className="dk-split-l" aria-label="Reports">
          {groups.map((g) => (
            <div key={g} className="dk-rgroup">
              <span className="k">{g}</span>
              {REPORTS.filter((x) => x.group === g).map((x) => (
                <button key={x.id} type="button" aria-current={x.id === id ? "true" : undefined} onClick={() => setId(x.id)}>
                  {x.title}
                  {weekly.has(x.id) && <i className="dk-pill">weekly</i>}
                </button>
              ))}
            </div>
          ))}
        </nav>
        <div className="dk-split-r">
          <Panel
            title={r.title}
            sub={`${w.biz.company} · from Tally, synced a few minutes ago`}
            right={
              <div className="dk-head-acts">
                <button type="button" className="btn btn-line btn-sm" onClick={() => { download(`${w.biz.company} - ${r.title}`, toRows(out.card, out.text)); ctx.toast("Downloaded — opens in Excel"); }}>
                  <IDownload /> Excel
                </button>
                <button type="button" className="btn btn-ghost-d btn-sm" onClick={() => ctx.chat(r.id === "cash" || r.id === "payables" ? "cash" : "ask", r.q ?? r.title)}>
                  <IChat size={16} /> Ask a follow-up
                </button>
              </div>
            }
          >
            <div className="dk-card-host wide">
              {out.text && <p className="dk-report-text">{out.text.replace(/\*\*/g, "")}</p>}
              {out.card && <CardView card={out.card} onGo={(g) => (g.to === "thread" ? ctx.chat(g.id) : ctx.go("inbox"))} />}
            </div>
            <div className="dk-whatif">
              <Toggle
                on={weekly.has(r.id)}
                onChange={(v) => {
                  setWeekly((o) => {
                    const n = new Set(o);
                    if (v) n.add(r.id);
                    else n.delete(r.id);
                    return n;
                  });
                  if (v) ctx.toast(`"${r.title}" will be emailed every Monday at 8 am`);
                }}
                label="Email this every Monday"
              />
              <span>
                <b>Email this every Monday</b>
                <small>To {w.biz.owner || "you"} and anyone you add, as an Excel file</small>
              </span>
            </div>
          </Panel>
        </div>
      </div>
    </>
  );
}
