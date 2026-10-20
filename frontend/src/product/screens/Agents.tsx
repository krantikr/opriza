import { useState } from "react";

import { api } from "../../api/client";
import { Empty, PageHead, Panel, Tabs, Toggle } from "../../demo/desk/ui";
import { AgentAvatar, Status } from "../bits";
import { useDesk } from "../ctx";
import { AGENT_NAMES, money, stamp, time, useData, type Agents as Data, type MessageRow, type Rule } from "../data";

const WHAT: Record<string, string> = {
  sales: "Reads every enquiry, prices it from the customer's last rate and today's market, sends the quote as a link, nudges, and flags regulars who stop ordering.",
  collect: "Reminds before due dates, sends statements with a pay-date link, builds today's call list, and tracks every promise.",
  stock: "Watches days of stock, asks suppliers for rates, drafts the PO with the best one, and offers idle stock to past buyers.",
  cash: "Keeps a four-week forecast from today's bank balance and warns you before a week goes short, with ways to cover it.",
  brief: "Sends the 8 am brief: cash first, then money to collect, then everything else.",
  score: "Grades every customer from how they actually pay, tells the others when a grade changes, and suggests credit limits.",
  ask: "Answers your questions from the books. Hands anything you ask it to do to the agent that owns it.",
};

type T = "agents" | "rules" | "runs" | "outbox" | "tally";

export default function Agents() {
  const ctx = useDesk();
  const { data, reload } = useData<Data>("/app/agents", 30000);
  const { data: outbox } = useData<MessageRow[]>("/app/outbox", 30000);
  const [tab, setTab] = useState<T>("agents");
  if (!data) return <Empty title="Loading…" />;
  const run = (agent: string) =>
    ctx.act(() => api.post<{ runs: number; approvals: number }>(`/app/agents/${agent}/run`), (r) => `${AGENT_NAMES[agent]} ran ${r.runs} time${r.runs === 1 ? "" : "s"}${r.approvals ? `, ${r.approvals} waiting for you` : ""}.`).then(reload);
  return (
    <>
      <PageHead title="Agents & rules" sub={<>Seven agents share one knowledge base built from Tally. They think with <b>{data.brain === "llm" ? "a language model (with rules as a safety net)" : "rules"}</b>; messages go out <b>{data.channel === "live" ? "for real" : "to the outbox only"}</b>.</>} />
      <Tabs value={tab} onChange={setTab} items={[
        { id: "agents", label: "Agents" }, { id: "rules", label: "Your rules" }, { id: "runs", label: "Run log", count: data.runs.length },
        { id: "outbox", label: "Messages sent", count: outbox?.length }, { id: "tally", label: "Back to Tally", count: data.postings.filter((p) => p.status === "pending").length },
      ]} />
      {tab === "agents" && (
        <div className="dk-agents">
          {data.agents.map((a) => (
            <section key={a.agent} className="dk-agent">
              <div className="dk-agent-h">
                <AgentAvatar agent={a.agent} size={38} />
                <div>
                  <h2>{a.label}</h2>
                  <p>{WHAT[a.agent]}</p>
                </div>
              </div>
              <div className="dk-agent-m op-agent-m">
                <div><b>{a.runs_today}</b><span>runs today</span></div>
                <div><b>{a.messages_today}</b><span>messages sent</span></div>
                <div><b>{a.open_tasks}</b><span>open tasks</span></div>
                <div><b>{a.waiting}</b><span>waiting for you</span></div>
              </div>
              <div className="op-agent-foot">
                <span className="muted">{a.last_run_at ? `Last ran ${stamp(a.last_run_at)}` : "Not run yet"}{a.last_status === "failed" ? " · last run failed" : ""}</span>
                {a.agent !== "ask" && <button type="button" className="btn btn-line btn-xs" onClick={() => void run(a.agent)}>Run now</button>}
                <button type="button" className="btn btn-ghost-d btn-xs" onClick={() => ctx.chat(a.agent)}>Chat</button>
              </div>
            </section>
          ))}
        </div>
      )}
      {tab === "rules" && <RulesEditor rules={data.rules} canEdit={ctx.me.user.can_approve} onSaved={reload} />}
      {tab === "runs" && (
        <Panel pad={false}>
          <table className="dk-table compact">
            <thead><tr><th>When</th><th>Agent</th><th>Trigger</th><th>Status</th><th>Brain</th><th className="r">LLM calls</th><th className="r">Tokens</th><th>Outcome</th></tr></thead>
            <tbody>
              {data.runs.map((r) => (
                <tr key={r.id}>
                  <td>{stamp(r.started_at)}</td><td>{AGENT_NAMES[r.agent]}</td><td className="muted">{r.trigger} · {r.ref}</td>
                  <td>{r.status === "failed" ? <span className="bad" title={r.error ?? ""}>Failed</span> : r.status === "waiting_approval" ? "Waiting" : "OK"}</td>
                  <td>{r.brain}</td><td className="r num">{r.llm_calls}</td><td className="r num">{r.tokens.toLocaleString("en-IN")}</td>
                  <td className="muted">{summary(r.outcome)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}
      {tab === "outbox" && (
        <Panel title="Messages to customers and suppliers" sub={data.channel === "live" ? "Sent by email or SMS." : "Outbox mode: stored and written to data/sent/agents, nothing leaves. Set AGENT_CHANNEL=live to send."} pad={false}>
          <table className="dk-table compact">
            <thead><tr><th>When</th><th>To</th><th>Why</th><th>By</th><th>Message</th><th>Status</th></tr></thead>
            <tbody>
              {(outbox ?? []).map((m) => (
                <tr key={m.id}><td>{stamp(m.created_at)}</td><td>{m.party}<small>{m.to}</small></td><td>{m.purpose}</td><td className="muted">{m.channel}</td><td className="op-msg">{m.body}</td><td>{m.status}</td></tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}
      {tab === "tally" && (
        <Panel title="Waiting to go back into Tally" sub="Only approved sales orders, purchase orders and credit limits are written back. The Tally connector picks these up." pad={false}>
          <table className="dk-table compact">
            <thead><tr><th>When</th><th>What</th><th>Details</th><th>Status</th></tr></thead>
            <tbody>
              {data.postings.map((p) => (
                <tr key={p.id}><td>{stamp(p.created_at)}</td><td>{p.kind.replace("_", " ")}</td><td className="muted">{Object.entries(p.payload).map(([k, v]) => `${k}: ${typeof v === "number" && v > 1000 ? money(v) : v}`).join(" · ")}</td><td><Status s={p.status === "pending" ? "open" : p.status} /></td></tr>
              ))}
              {!data.postings.length && <tr><td colSpan={4} className="muted">Nothing yet.</td></tr>}
            </tbody>
          </table>
        </Panel>
      )}
    </>
  );
}

function summary(o: any): string {
  if (!o) return "";
  const res = (o.results ?? []).concat(o.after_approval ? [o.after_approval] : []).filter((x: object) => Object.keys(x).length);
  const parts = res.slice(0, 3).map((x: Record<string, unknown>) => Object.entries(x).map(([k, v]) => `${k} ${typeof v === "object" ? "…" : v}`).join(", "));
  if (o.approvals?.length) parts.push(`${o.approvals.length} sent for approval`);
  return parts.join(" · ");
}

function RulesEditor({ rules, canEdit, onSaved }: { rules: Rule[]; canEdit: boolean; onSaved: () => void }) {
  const ctx = useDesk();
  const [draft, setDraft] = useState<Record<string, string>>({});
  const groups = [...new Set(rules.map((r) => r.agent))];
  const save = (r: Rule, value: unknown) =>
    ctx.act(() => api.put(`/app/rules/${r.agent}/${r.key}`, { value }), `Saved: ${r.label}`).then(() => {
      setDraft((d) => { const n = { ...d }; delete n[`${r.agent}.${r.key}`]; return n; });
      onSaved();
    });
  return (
    <div className="dk-stack">
      {!canEdit && <p className="dk-fine">Only the owner can change the rules.</p>}
      {groups.map((g) => (
        <Panel key={g} title={AGENT_NAMES[g]} pad={false}>
          <div className="dk-rules">
            {rules.filter((r) => r.agent === g).map((r) => {
              const key = `${r.agent}.${r.key}`;
              const v = draft[key] ?? String(r.value);
              return (
                <div key={key} className="dk-set">
                  <div><b>{r.label}</b><small>{r.help}{r.updated_at ? ` · changed ${stamp(r.updated_at)}` : ""}</small></div>
                  {r.kind === "bool" ? (
                    <Toggle on={Boolean(r.value)} label={r.label} onChange={(nv) => canEdit && void save(r, nv)} />
                  ) : r.kind === "choice" ? (
                    <select value={String(r.value)} disabled={!canEdit} onChange={(e) => void save(r, e.target.value)}>
                      {r.choices.map((c) => <option key={c}>{c}</option>)}
                    </select>
                  ) : (
                    <form className="op-rule-in" onSubmit={(e) => { e.preventDefault(); void save(r, r.kind === "text" || r.kind === "time" ? v : Number(v)); }}>
                      {r.kind === "money" && <span className="muted">₹</span>}
                      <input value={v} disabled={!canEdit} onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value }))} aria-label={r.label}
                        inputMode={r.kind === "text" || r.kind === "time" ? "text" : "decimal"} />
                      {r.kind === "percent" && <span className="muted">%</span>}
                      {draft[key] !== undefined && draft[key] !== String(r.value) && <button type="submit" className="btn btn-go btn-xs">Save</button>}
                    </form>
                  )}
                </div>
              );
            })}
          </div>
        </Panel>
      ))}
      <p className="dk-fine">Times are in the business's time zone ({time(new Date().toISOString())} now).</p>
    </div>
  );
}
