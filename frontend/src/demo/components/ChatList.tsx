import { useState } from "react";
import type { DemoState, Msg, ThreadId } from "../engine/types";
import { clock } from "../lib/format";

/** What the list shows as a chat's last line. */
function preview(m: Msg | undefined): string {
  if (!m) return "";
  if (m.from === "me") return `You: ${m.text ?? ""}`;
  if (m.text) return m.text.replace(/\*\*/g, "");
  const c = m.card;
  if (!c) return "";
  switch (c.kind) {
    case "quote": return `Quote ${c.no} · ${c.customer}`;
    case "due": return `${c.name} · ${c.daysLate} day${c.daysLate === 1 ? "" : "s"} late`;
    case "queue": return `${c.count} customers to follow up`;
    case "reorder": return `${c.product} · ${c.daysLeft} days left`;
    case "rates": return `Rates in for ${c.product}`;
    case "idle": return `Idle stock · ${c.product}`;
    case "alert": return c.title;
    case "won": return `Order won · ${c.customer}`;
    case "score": return `${c.name} moved to grade ${c.grade}`;
    case "po": return `${c.no} · ${c.supplier}`;
    case "brief": return "Your business in one minute";
    case "enquiry": return `New enquiry · ${c.customer}`;
    case "kpis": return c.title ?? "Your numbers";
    case "table": return c.title ?? "Your answer";
    case "bars": return c.title;
    case "cashweeks": return "Cash, next 4 weeks";
    default: return "New message";
  }
}

type Props = {
  state: DemoState;
  active: ThreadId | null;
  onOpen: (id: ThreadId) => void;
};

export default function ChatList({ state, active, onOpen }: Props) {
  const [filter, setFilter] = useState<"all" | "unread">("all");
  const [q, setQ] = useState("");
  const w = state.world;
  const ids = state.order.filter((id) => {
    const t = state.threads[id];
    if (filter === "unread" && t.unread === 0) return false;
    if (q && !t.name.toLowerCase().includes(q.toLowerCase())) return false;
    return true;
  });
  // Chats with something unread, as on the Chats tab badge (not a message count).
  const unreadTotal = state.order.filter((id) => state.threads[id].unread > 0).length;

  return (
    <>
      <div className="list-head">
        <div className="top">
          <div className="mark">Oprisa<i>.</i></div>
          <span className="sync">Tally {clock(state.clock - 2)}</span>
        </div>
        <label className="sr" htmlFor="search">Search chats</label>
        <input id="search" className="search" placeholder="Search chats" value={q} onChange={(e) => setQ(e.target.value)} />
        <div className="filters" role="group" aria-label="Filter">
          <button type="button" aria-pressed={filter === "all"} onClick={() => setFilter("all")}>All</button>
          <button type="button" aria-pressed={filter === "unread"} onClick={() => setFilter("unread")}>Unread {unreadTotal || ""}</button>
        </div>
      </div>
      <div className="rows">
        {ids.map((id) => {
          const t = state.threads[id];
          const last = t.messages[t.messages.length - 1];
          return (
            <button key={id} type="button" className="chat-row" aria-current={active === id} onClick={() => onOpen(id)}>
              <div className="av" style={{ background: t.bg, color: t.fg }} aria-hidden="true">{t.letter}</div>
              <div className="mid">
                <div className="t1">
                  <span className="nm">{t.name}</span>
                  <span className={`tm ${t.unread ? "new" : ""}`}>{last ? clock(last.at) : ""}</span>
                </div>
                <div className={`pv ${t.typing ? "is-typing" : ""}`}>{t.typing ? "typing…" : preview(last)}</div>
              </div>
              {t.unread > 0 && <span className="cnt" aria-label={`${t.unread} unread`}>{t.unread}</span>}
            </button>
          );
        })}
        {ids.length === 0 && <div className="list-tip">No chats match.</div>}
        <div className="list-tip">
          This is {w.biz.company} with sample data. Tap any chat, press the buttons, or type a question. Agents reply from the mock Tally data.
        </div>
      </div>
    </>
  );
}
