import { useState, type ReactNode } from "react";
import { setRules } from "../engine/desk";
import type { DemoState, ThreadId } from "../engine/types";
import { clock, money, pct } from "../lib/format";
import type { Ctx } from "./ctx";
import { IChat } from "./icons";
import { Avatar, Initials, PageHead, Panel, Toggle } from "./ui";

/* ---------------------------------------------------------------------------
   Agents & rules: what each agent does, what it did this month, and the
   rules it follows — written as sentences with blanks the owner can change.
   --------------------------------------------------------------------------- */

const ORDER: ThreadId[] = ["sales", "collect", "stock", "cash", "brief", "score", "ask"];

const WHAT: Record<ThreadId, string> = {
  sales: "Reads enquiries from email and WhatsApp, prices them from Tally and follows up on quotes.",
  collect: "Ranks who to call, sends statement links and tracks every payment promise.",
  stock: "Watches days of stock, asks suppliers for rates and drafts purchase orders.",
  cash: "Forecasts the next 4 weeks and finds ways to close a short week.",
  brief: "Sends one morning brief: yesterday's numbers and the first things to do.",
  score: "Grades every customer A–D from how they pay, and suggests credit limits.",
  ask: "Answers any question from your Tally data. It never sends anything to anyone.",
};

/** This month's work before today, so the cards don't start at zero. */
function monthWork(s: DemoState, id: ThreadId): { n: number; what: string; extra?: string } {
  const w = s.world;
  const today = s.desk.log.filter((l) => l.agent === id).reduce((a, l) => a + l.count, 0);
  switch (id) {
    case "sales":
      return { n: 142 + today, what: "quotes priced", extra: "average 8 minutes from enquiry to quote" };
    case "collect":
      return { n: Math.round(w.kpi.overdueCount * 9.5) + today, what: "reminders and statement links", extra: `${money(w.kpi.overdue * 0.36 + s.collectedToday)} promised after them` };
    case "stock":
      return { n: 23 + today, what: "rate requests and POs", extra: "2 stock-outs avoided" };
    case "cash":
      return { n: 19 + today, what: "forecasts and fixes", extra: "1 short week closed in time" };
    case "brief":
      return { n: 19, what: "morning briefs", extra: "sent at 8:00 every working day" };
    case "score":
      return { n: 11 + today, what: "grade changes", extra: `${w.customers.filter((c) => c.grade === "D").length} customers on hold for new credit` };
    default:
      return { n: 64, what: "questions answered", extra: "most asked: who owes the most" };
  }
}

function Stepper({ value, onChange, min, max, step = 1, fmt = (v: number) => String(v), label }: { value: number; onChange: (v: number) => void; min: number; max: number; step?: number; fmt?: (v: number) => string; label: string }) {
  return (
    <span className="dk-stepper" role="group" aria-label={label}>
      <button type="button" aria-label={`Lower ${label}`} disabled={value <= min} onClick={() => onChange(Math.max(min, Math.round((value - step) * 10) / 10))}>−</button>
      <b>{fmt(value)}</b>
      <button type="button" aria-label={`Raise ${label}`} disabled={value >= max} onClick={() => onChange(Math.min(max, Math.round((value + step) * 10) / 10))}>+</button>
    </span>
  );
}

function Rule({ children, control }: { children: ReactNode; control?: ReactNode }) {
  return (
    <li className="dk-rule">
      <span className="t">{children}</span>
      {control}
    </li>
  );
}

export default function Agents({ ctx }: { ctx: Ctx }) {
  const s = ctx.s;
  const w = s.world;
  const r = s.desk.rules;
  const set = (patch: Parameters<typeof setRules>[1]) => ctx.set((st) => setRules(st, patch));
  const onCount = ORDER.filter((id) => r.agents[id]).length;

  const rules: Partial<Record<ThreadId, ReactNode>> = {
    sales: (
      <>
        <Rule control={<Toggle on={r.autoSendInBand} onChange={(v) => set({ autoSendInBand: v })} label="Send quotes inside the band without approval" />}>
          Quotes inside the price band go out <b>without me</b>
        </Rule>
        <Rule>
          Nudge a quote nobody opened after <Stepper value={r.nudgeHours} min={6} max={72} step={6} fmt={(v) => `${v} hours`} onChange={(v) => set({ nudgeHours: v })} label="nudge after" />
        </Rule>
      </>
    ),
    collect: (
      <>
        <Rule>
          Remind customers <Stepper value={r.remindDays} min={0} max={7} fmt={(v) => (v === 0 ? "on" : `${v} day${v === 1 ? "" : "s"}`)} onChange={(v) => set({ remindDays: v })} label="days before due" /> before the due date, in <b>{w.biz.language}</b>
        </Rule>
        <Rule>Tell me the morning after a promise is missed</Rule>
      </>
    ),
    stock: (
      <>
        <Rule>
          Flag items with less than <Stepper value={r.reorderDays} min={5} max={30} fmt={(v) => `${v} days`} onChange={(v) => set({ reorderDays: v })} label="days of stock" /> of stock
        </Rule>
        <Rule>Ask 3 suppliers for rates before every PO</Rule>
      </>
    ),
    cash: <Rule>Warn me 3 weeks before a short week, with fixes</Rule>,
    brief: (
      <>
        <Rule>Morning brief at <b>8:00 am</b>, every working day</Rule>
        <Rule control={<Toggle on={r.weeklyReport} onChange={(v) => set({ weeklyReport: v })} label="Weekly report" />}>Weekly report by email every Monday</Rule>
      </>
    ),
    score: <Rule>Re-grade a customer after every payment; ask me before lowering a limit</Rule>,
    ask: <Rule>Only reads data. Anything that sends goes through the other agents' rules</Rule>,
  };

  return (
    <>
      <PageHead title="Agents & rules" sub={`${onCount} of ${ORDER.length} agents working. Change a rule here and every agent follows it from the next task.`} />

      <div className="dk-agents">
        {ORDER.map((id) => {
          const t = s.threads[id];
          const on = r.agents[id];
          const m = monthWork(s, id);
          return (
            <section key={id} className={`dk-agent ${on ? "" : "off"}`}>
              <div className="dk-agent-h">
                <Avatar t={t} size={40} />
                <div>
                  <h2>{t.name}</h2>
                  <p>{WHAT[id]}</p>
                </div>
                <Toggle
                  on={on}
                  onChange={(v) => {
                    set({ agents: { ...r.agents, [id]: v } });
                    ctx.toast(v ? `${t.name} is working again` : `${t.name} paused — it won't act until you turn it back on`);
                  }}
                  label={`${t.name} on or off`}
                />
              </div>
              <div className="dk-agent-m">
                <b>{m.n.toLocaleString("en-IN")}</b>
                <span>{m.what} this month{m.extra ? ` · ${m.extra}` : ""}</span>
              </div>
              <ul className="dk-rules">{rules[id]}</ul>
              <button type="button" className="dk-link" onClick={() => ctx.chat(id)}><IChat size={16} /> Open chat</button>
            </section>
          );
        })}
      </div>

      <Panel title="Who can approve what" sub="Anything above a limit comes to the owner's Inbox" pad={false}>
        <table className="dk-table">
          <thead><tr><th>Person</th><th>Role</th><th>Can approve on their own</th><th>Above that</th></tr></thead>
          <tbody>
            {w.team.sales.map((n) => (
              <tr key={n}><td><b>{n}</b></td><td>Sales</td><td>Quotes inside the price band (margin {pct(w.limits.marginFloor)}+)</td><td className="muted">Comes to you</td></tr>
            ))}
            <tr>
              <td><b>{w.team.purchase}</b></td><td>Purchase</td>
              <td>
                POs up to{" "}
                <Stepper value={w.limits.poLimit / 1e5} min={10} max={500} step={10} fmt={(v) => money(v * 1e5)} onChange={(v) => ctx.set((st) => ({ ...st, world: { ...st.world, limits: { ...st.world.limits, poLimit: v * 1e5 } } }))} label="PO limit" />
              </td>
              <td className="muted">Comes to you</td>
            </tr>
            <tr><td><b>{w.team.accounts}</b></td><td>Accounts</td><td>Reminders, receipts, promise logging</td><td className="muted">Credit limits come to you</td></tr>
          </tbody>
        </table>
      </Panel>
    </>
  );
}

/* ---------------------------------------------------------------------------
   Settings
   --------------------------------------------------------------------------- */

export function SettingsPage({ ctx }: { ctx: Ctx }) {
  const s = ctx.s;
  const w = s.world;
  const l = w.limits;
  const [quiet, setQuiet] = useState(true);
  const auto = Math.max(40, Math.min(97, Math.round(85 - (l.marginFloor - 3) * 8 + (l.maxDiscount - 1.5) * 4)));
  const setLimit = (k: "marginFloor" | "maxDiscount", v: number) => ctx.set((st) => ({ ...st, world: { ...st.world, limits: { ...st.world.limits, [k]: v } } }));
  const people = [
    { name: w.biz.owner || "You", role: "Owner", sees: "Everything", owner: true },
    ...w.team.sales.map((n) => ({ name: n, role: "Sales", sees: "Home, Inbox, Sales, Customers", owner: false })),
    { name: w.team.accounts, role: "Accounts", sees: "Home, Inbox, Collections, Cash, Customers", owner: false },
    { name: w.team.purchase, role: "Purchase", sees: "Home, Inbox, Stock & Purchase", owner: false },
    { name: "CA (view only)", role: "View only", sees: "Reports, audit trail", owner: false },
  ];
  const who = (agent: ThreadId) => s.threads[agent].name;

  return (
    <>
      <PageHead title="Settings" sub="Set once; the agents and your team follow it." />
      <div className="dk-grid2">
        <Panel title="Price band" sub="Quotes inside the band go out without you">
          <div className="dk-set">
            <div><b>Minimum margin</b><small>Below this, the quote waits for you</small></div>
            <Stepper value={l.marginFloor} min={0} max={10} step={0.5} fmt={(v) => pct(v)} onChange={(v) => setLimit("marginFloor", v)} label="minimum margin" />
          </div>
          <div className="dk-set">
            <div><b>Maximum discount</b><small>Against the customer's last rate</small></div>
            <Stepper value={l.maxDiscount} min={0} max={10} step={0.5} fmt={(v) => pct(v)} onChange={(v) => setLimit("maxDiscount", v)} label="maximum discount" />
          </div>
          <p className="dk-fine good">About {auto}% of last month's quotes would have gone out without you.</p>
        </Panel>

        <Panel title="Tally" sub="Tally stays your books">
          <div className="dk-set"><div><b>Sync app · OFFICE-PC</b><small>{w.biz.tally} · every 15 minutes</small></div><span className="dk-status s-ok">Synced {clock(s.clock - 2)}</span></div>
          <div className="dk-set"><div><b>Reads</b><small>Sales, receipts, stock, bills, ledgers</small></div></div>
          <div className="dk-set"><div><b>Writes, only after approval</b><small>Sales orders, POs, receipts, credit limits</small></div></div>
        </Panel>

        <Panel title="Team and roles" sub="Each person sees only their menu" pad={false}>
          <table className="dk-table compact">
            <thead><tr><th>Person</th><th>Role</th><th>Sees</th></tr></thead>
            <tbody>
              {people.map((p) => (
                <tr key={p.name}>
                  <td><span className="dk-person"><Initials name={p.name} size={26} /> <b>{p.name}</b></span></td>
                  <td>{p.role}</td>
                  <td className="muted">{p.sees}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>

        <Panel title="Alerts and security">
          <div className="dk-set"><div><b>Quiet hours, 9 pm – 8 am</b><small>Urgent alerts only, max 5 a day</small></div><Toggle on={quiet} onChange={setQuiet} label="Quiet hours" /></div>
          <div className="dk-set"><div><b>Message language</b><small>Reminders and links to customers</small></div><b>{w.biz.language}</b></div>
          <div className="dk-set"><div><b>Sign-in</b><small>One-time code on phone; 2-step check for the owner</small></div><span className="dk-status s-ok">On</span></div>
          <div className="dk-set"><div><b>Signed-in devices</b><small>This browser, {w.firstName}'s phone, OFFICE-PC</small></div><button type="button" className="dk-link" onClick={() => ctx.toast("Other devices signed out")}>Sign out others</button></div>
        </Panel>
      </div>

      <Panel title="Audit trail" sub="Every action by an agent or a person: who, what, when" pad={false}>
        <table className="dk-table compact">
          <thead><tr><th>When</th><th>Who</th><th>What</th></tr></thead>
          <tbody>
            {s.desk.log.slice(0, 12).map((e) => (
              <tr key={e.id}>
                <td className="muted">{e.yday ? `Yesterday ${clock(e.at)}` : clock(e.at)}</td>
                <td>{who(e.agent)} agent</td>
                <td>{e.text}</td>
              </tr>
            ))}
            {s.approvals.filter((a) => a.status !== "waiting").map((a) => (
              <tr key={a.id}>
                <td className="muted">Today</td>
                <td>{w.biz.owner || "Owner"}</td>
                <td>{a.status === "approved" ? "Approved" : "Sent back"}: {a.type.toLowerCase()} · {a.title}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </>
  );
}
