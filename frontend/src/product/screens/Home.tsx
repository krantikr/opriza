import { api } from "../../api/client";
import CardView from "../../demo/components/CardView";
import type { Card } from "../../demo/engine/types";
import { IArrow } from "../../demo/desk/icons";
import { Empty, PageHead, Panel } from "../../demo/desk/ui";
import { AgentAvatar, approvalLine, Bars, CashBars } from "../bits";
import { useDesk } from "../ctx";
import { day, money, time, useData, type Home as HomeData } from "../data";

const WHAT: Record<string, string> = {
  owner: "things need you", accounts: "follow-ups for accounts", sales: "things for sales", purchase: "purchase tasks",
};

export default function Home() {
  const ctx = useDesk();
  const { data: h } = useData<HomeData>(`/app/home?role=${ctx.role}`, 30000);
  const { data: inbox } = useData<import("../data").Approval[]>(`/app/approvals`, 30000);
  if (!h) return <Empty title="Loading your desk…" />;

  const hour = Number(time(h.now).split(":")[0] ?? 9);
  const greet = hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
  const first = ctx.me.user.name.split(" ")[0];
  const approvals = ctx.role === "owner" ? inbox ?? [] : [];
  const pending = h.inbox.length + approvals.length;
  const done = h.agents.reduce((a, x) => a + x.runs_today, 0);
  const sent = h.agents.reduce((a, x) => a + x.messages_today, 0);
  const short = h.cash.short;
  const week = h.sales_series.slice(-7);

  const decide = (id: number, approve: boolean) =>
    ctx.act(() => api.post(`/app/approvals/${id}`, { approve }), approve ? "Approved. The agent has gone ahead." : "Held back.");

  return (
    <>
      <PageHead
        title={`${greet}, ${first}`}
        sub={<><b>{pending} {WHAT[ctx.role]}</b> · agents ran <b>{done} times</b> today and sent <b>{sent} messages</b> · books as of {day(h.today)}</>}
      />

      <div className="dk-money">
        <button type="button" onClick={() => ctx.go("sales")}>
          <span className="k">In open quotes</span>
          <b>{money(h.money_waiting.open_quotes)}</b>
          <small>{h.money_waiting.open_quote_count} quotes being followed up</small>
        </button>
        <button type="button" onClick={() => ctx.go("collect")}>
          <span className="k">Overdue to collect</span>
          <b>{money(h.money_waiting.overdue)}</b>
          <small>{h.money_waiting.overdue_customers} customers · reminders and calls are on</small>
        </button>
        <button type="button" onClick={() => ctx.go("stock")}>
          <span className="k">Stuck in idle stock</span>
          <b>{money(h.money_waiting.idle_stock)}</b>
          <small>No sale for 60+ days</small>
        </button>
        <div className={`won ${h.money_waiting.promised_this_week ? "on" : ""}`}>
          <span className="k">Promised this week</span>
          <b>{money(h.money_waiting.promised_this_week)}</b>
          <small>Payment dates customers picked on their links or calls</small>
        </div>
      </div>

      <div className="dk-kpis">
        <button type="button" onClick={() => ctx.go("reports")}>
          <span>Sales this month</span>
          <b>{money(h.kpis.sales_mtd)}</b>
          <small className={(h.kpis.sales_7d_change ?? 0) >= 0 ? "good" : "bad"}>
            {h.kpis.sales_7d_change === null ? "—" : `${h.kpis.sales_7d_change >= 0 ? "▲" : "▼"} ${Math.abs(h.kpis.sales_7d_change)}% last 7 days vs week before`}
          </small>
        </button>
        <button type="button" onClick={() => ctx.go("collect")}>
          <span>Owed to you</span>
          <b>{money(h.kpis.receivable)}</b>
          <small className="bad">{h.kpis.dso ?? "—"} days to collect</small>
        </button>
        <button type="button" onClick={() => ctx.go("cash")}>
          <span>Bank today</span>
          <b>{h.kpis.bank === null ? "—" : money(h.kpis.bank)}</b>
          <small className={short ? "bad" : "good"}>{short ? `Short in week of ${day(short.week_start)}` : "Fine for 4 weeks"}</small>
        </button>
        <button type="button" onClick={() => ctx.go("cash")}>
          <span>To pay this week</span>
          <b>{money(h.kpis.payables_7d)}</b>
          <small>Supplier bills due</small>
        </button>
        <button type="button" onClick={() => ctx.go("stock")}>
          <span>Stock value</span>
          <b>{money(h.kpis.stock_value)}</b>
          <small>{money(h.money_waiting.idle_stock)} idle</small>
        </button>
      </div>

      <div className="dk-grid2">
        <Panel title="Needs you" sub="Each one comes with the agent's reason" right={<button type="button" className="dk-link" onClick={() => ctx.go("inbox")}>Open Inbox <IArrow /></button>} pad={false}>
          <ul className="dk-list">
            {approvals.slice(0, 4).map((a) => (
              <li key={`a${a.id}`}>
                <button type="button" className="dk-list-main" onClick={() => ctx.go("inbox", { tab: "approvals" })}>
                  <AgentAvatar agent={a.agent} size={30} />
                  <span>
                    <b>{a.title}</b>
                    <small><span className="dk-why">{a.reason}</span> · {approvalLine(a)}</small>
                  </span>
                </button>
                <button type="button" className="btn btn-go btn-xs" onClick={() => void decide(a.id, true)}>Approve</button>
              </li>
            ))}
            {h.inbox.slice(0, Math.max(0, 6 - approvals.slice(0, 4).length)).map((t) => (
              <li key={`t${t.id}`}>
                <button type="button" className="dk-list-main" onClick={() => (t.entity_type === "party" && t.entity_id ? ctx.drawer({ type: "customer", id: t.entity_id }) : ctx.go("inbox"))}>
                  <AgentAvatar agent={t.agent} size={30} />
                  <span>
                    <b>{t.title}</b>
                    <small>{t.detail}</small>
                  </span>
                </button>
                {t.priority === 1 && <span className="dk-pill bad">Today</span>}
              </li>
            ))}
            {pending === 0 && <li className="dk-list-empty">All clear. The agents will put things here when they need you.</li>}
          </ul>
        </Panel>
        {h.brief?.card ? (
          <Panel title="This morning's brief" sub={`From the Business Manager at ${time(h.brief.ts)}`} right={<button type="button" className="dk-link" onClick={() => ctx.chat("brief")}>Open chat <IArrow /></button>}>
            {h.brief.text && <p className="op-brief-text">{h.brief.text.replace(/\*\*/g, "")}</p>}
            <div className="dk-card-host wide">
              <CardView card={h.brief.card as Card} onGo={(g) => (g.to === "thread" ? ctx.chat(g.id) : ctx.go(g.tab === "approvals" ? "inbox" : "home", g.tab === "approvals" ? { tab: "approvals" } : {}))} />
            </div>
          </Panel>
        ) : (
          <Panel title="This morning's brief"><Empty title="The 8 am brief appears here" /></Panel>
        )}
      </div>

      <div className="dk-grid2">
        <Panel title="Cash, next 4 weeks" sub="From open bills, how each customer pays, and supplier dues" right={<button type="button" className="dk-link" onClick={() => ctx.go("cash")}>Open Cash <IArrow /></button>}>
          <CashBars weeks={h.cash.weeks} />
        </Panel>
        <Panel title="Sales, last 7 days" sub={`${money(week.reduce((a, d) => a + d.value, 0))} before tax`}>
          <Bars rows={week.map((d) => ({ label: day(d.day), value: d.value }))} highlight={week.length - 1} />
        </Panel>
      </div>

      <Panel title="Your agents today" sub="What each one did since this morning" right={<button type="button" className="dk-link" onClick={() => ctx.go("agents")}>Agents & rules <IArrow /></button>} pad={false}>
        <ul className="dk-list op-agents-today">
          {h.agents.map((a) => (
            <li key={a.agent}>
              <button type="button" className="dk-list-main" onClick={() => ctx.chat(a.agent)}>
                <AgentAvatar agent={a.agent} size={30} />
                <span>
                  <b>{a.label}</b>
                  <small>
                    {a.runs_today} run{a.runs_today === 1 ? "" : "s"} · {a.messages_today} message{a.messages_today === 1 ? "" : "s"} sent
                    {a.open_tasks ? ` · ${a.open_tasks} open tasks` : ""}{a.waiting ? ` · ${a.waiting} waiting for you` : ""}
                    {a.last_run_at ? ` · last ${time(a.last_run_at)}` : ""}
                  </small>
                </span>
              </button>
              {a.last_status === "failed" && <span className="dk-pill bad">Failed</span>}
            </li>
          ))}
        </ul>
      </Panel>
    </>
  );
}
