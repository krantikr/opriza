import type { ReactNode } from "react";

import { Avatar } from "../demo/desk/ui";
import { AGENT_NAMES, day, money, STATUS_LABEL, type Approval, type Task, type Week } from "./data";

const AGENT_LOOK: Record<string, { letter: string; bg: string; fg: string }> = {
  ask: { letter: "O", bg: "#E8A33D", fg: "#3A1A05" },
  brief: { letter: "B", bg: "#8A2420", fg: "#FFFFFF" },
  sales: { letter: "S", bg: "#1F6B4D", fg: "#FFFFFF" },
  collect: { letter: "C", bg: "#6D1A17", fg: "#FFFFFF" },
  stock: { letter: "P", bg: "#2F4F6F", fg: "#FFFFFF" },
  cash: { letter: "₹", bg: "#5B4A1F", fg: "#FFFFFF" },
  score: { letter: "G", bg: "#4A3F6B", fg: "#FFFFFF" },
};

export function AgentAvatar({ agent, size = 28 }: { agent: string; size?: number }) {
  const look = AGENT_LOOK[agent] ?? AGENT_LOOK.ask!;
  return <Avatar t={{ ...look, name: AGENT_NAMES[agent] ?? agent }} size={size} />;
}

const TONE: Record<string, string> = {
  sent: "st-sent", opened: "st-opened", negotiating: "st-talks", won: "st-won", lost: "st-lost", expired: "st-lost",
  pending_approval: "s-watch", waiting: "s-watch", draft: "", reorder: "s-reorder", watch: "s-watch", idle: "s-watch", ok: "s-ok",
  kept: "s-ok", part_kept: "s-watch", missed: "s-reorder", open: "st-sent", received: "s-ok", quoted: "s-ok",
  new: "st-opened", needs_review: "s-reorder",
};

export function Status({ s }: { s: string }) {
  return <span className={`dk-stage dk-status ${TONE[s] ?? ""}`}>{STATUS_LABEL[s] ?? s.replace(/_/g, " ")}</span>;
}

export function CashBars({ weeks }: { weeks: Week[] }) {
  if (!weeks.length) return <div className="dk-empty"><b>No forecast yet</b><span>It appears after the first Tally sync.</span></div>;
  const max = Math.max(...weeks.flatMap((w) => [w.inflow, w.outflow]), 1);
  return (
    <div className="dk-cash">
      <div className="dk-cash-key">
        <span><i className="in" /> Coming in</span>
        <span><i className="out" /> Going out</span>
        <span className="op-key-close">Bank at week end</span>
      </div>
      <div className="dk-cash-cols">
        {weeks.map((wk, i) => (
          <div key={wk.week_start} className={`wk ${wk.closing < 0 ? "short" : ""}`}>
            <div className="bars">
              <i className="in" style={{ height: `${(wk.inflow / max) * 100}%` }} title={`In ${money(wk.inflow)}`} />
              <i className="out" style={{ height: `${(wk.outflow / max) * 100}%` }} title={`Out ${money(wk.outflow)}`} />
            </div>
            <b className={wk.closing < 0 ? "neg" : "pos"}>{money(wk.closing)}</b>
            <span>Week {i + 1} · {day(wk.week_start)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function Bars({ rows, highlight }: { rows: { label: string; value: number }[]; highlight?: number }) {
  const max = Math.max(...rows.map((r) => r.value), 1);
  return (
    <div className="dk-bars">
      {rows.map((r, i) => (
        <div key={r.label + i} className="col">
          <span className="v">{r.value ? money(r.value) : "—"}</span>
          <i style={{ height: `${Math.max(2, (r.value / max) * 100)}%` }} className={i === highlight ? "hi" : ""} />
          <span className="l">{r.label}</span>
        </div>
      ))}
    </div>
  );
}

/** A small line chart, for series of 30–90 points. */
export function Spark({ points, height = 120, tone = "var(--maroon-bar)", label }: { points: number[]; height?: number; tone?: string; label: string }) {
  if (points.length < 2) return null;
  const max = Math.max(...points, 1);
  const min = Math.min(...points, 0);
  const w = 600;
  const xy = points.map((p, i) => [(i / (points.length - 1)) * w, height - ((p - min) / (max - min || 1)) * (height - 8) - 4]);
  const d = xy.map(([x, y], i) => `${i ? "L" : "M"}${x!.toFixed(1)} ${y!.toFixed(1)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${height}`} className="op-spark" role="img" aria-label={label} preserveAspectRatio="none">
      <path d={`${d} L${w} ${height} L0 ${height} Z`} fill={tone} opacity="0.08" />
      <path d={d} fill="none" stroke={tone} strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export function TaskLine({ t, right, onOpen }: { t: Task; right?: ReactNode; onOpen?: () => void }) {
  return (
    <li>
      <button type="button" className="dk-list-main" onClick={onOpen}>
        <AgentAvatar agent={t.agent} size={30} />
        <span>
          <b>{t.title}</b>
          <small>{t.detail}</small>
        </span>
      </button>
      {right}
    </li>
  );
}

export function approvalLine(a: Approval): string {
  const d = a.details ?? {};
  switch (a.action) {
    case "place_po": return `${d.qty} from ${d.supplier} at ₹${Math.round(d.rate).toLocaleString("en-IN")} · ${money(d.total)}`;
    case "send_quote": return `${d.party} · ${money(d.total)} at ${Number(d.margin).toFixed(1)}% margin`;
    case "change_credit_limit": return `${d.party}: ${money(d.old_limit)} → ${money(d.new_limit)}`;
    case "send_offer": return `${d.item} at ₹${Math.round(d.price).toLocaleString("en-IN")} to ${d.buyers?.length ?? 0} buyers`;
    case "ask_early_payment": return `Week of ${day(d.week_start)} short by ${money(d.shortfall)}`;
    default: return a.reason;
  }
}
