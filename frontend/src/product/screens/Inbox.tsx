import { useEffect, useMemo, useState } from "react";

import { api } from "../../api/client";
import { IChat } from "../../demo/desk/icons";
import { Check, Empty, PageHead, Tabs } from "../../demo/desk/ui";
import { AgentAvatar, approvalLine } from "../bits";
import { useDesk } from "../ctx";
import { AGENT_NAMES, day, money, rate, stamp, useData, type Approval, type Task } from "../data";
import { PromiseForm } from "../panels";

type Item = { key: string; kind: "approval"; a: Approval } | { key: string; kind: "task"; t: Task };

export default function Inbox() {
  const ctx = useDesk();
  const { data } = useData<{ tasks: Task[]; approvals: Approval[] }>(`/app/inbox?role=${ctx.role}`, 20000);
  const [tab, setTab] = useState<"all" | "approvals" | "tasks">((ctx.params.tab as "approvals") ?? "all");
  const [sel, setSel] = useState<string | null>(null);
  const [ticked, setTicked] = useState<Set<number>>(new Set());
  const [note, setNote] = useState("");

  const items: Item[] = useMemo(() => {
    const ap = (data?.approvals ?? []).map((a) => ({ key: `a${a.id}`, kind: "approval" as const, a }));
    const ts = (data?.tasks ?? []).map((t) => ({ key: `t${t.id}`, kind: "task" as const, t }));
    return tab === "approvals" ? ap : tab === "tasks" ? ts : [...ap, ...ts];
  }, [data, tab]);
  const current = items.find((i) => i.key === sel) ?? items[0];
  useEffect(() => setNote(""), [current?.key]);

  const nextAfter = (key: string) => {
    const i = items.findIndex((x) => x.key === key);
    const nxt = items[i + 1] ?? items[i - 1];
    setSel(nxt ? nxt.key : null);
  };
  const decide = async (a: Approval, approve: boolean) => {
    nextAfter(`a${a.id}`);
    await ctx.act(() => api.post(`/app/approvals/${a.id}`, { approve, note: note || undefined }),
      approve ? `Approved: ${a.title}. The agent has gone ahead.` : "Held back. The agent knows.");
  };
  const many = async (ids: number[]) => {
    for (const id of ids) await api.post(`/app/approvals/${id}`, { approve: true }).catch(() => null);
    setTicked(new Set());
    await ctx.act(async () => null, `${ids.length} approved. The agents are sending them out.`);
  };
  const setTask = (t: Task, status: string) => {
    nextAfter(`t${t.id}`);
    void ctx.act(() => api.post(`/app/tasks/${t.id}`, { status }), status === "done" ? "Marked done." : "Dismissed.");
  };

  const approvals = data?.approvals ?? [];
  const canApprove = ctx.me.user.can_approve;

  return (
    <>
      <PageHead title="Inbox" sub={<>Everything waiting for {ctx.role === "owner" ? "you" : `the ${ctx.role} desk`}, from every agent. Anything inside your rules already went out.</>}>
        {canApprove && approvals.length > 0 && (
          <>
            <button type="button" className="btn btn-line btn-sm" disabled={!ticked.size} onClick={() => void many([...ticked])}>
              Approve selected{ticked.size ? ` (${ticked.size})` : ""}
            </button>
          </>
        )}
      </PageHead>

      <Tabs value={tab} onChange={setTab} items={[
        { id: "all", label: "All", count: approvals.length + (data?.tasks.length ?? 0) },
        { id: "approvals", label: "Approvals", count: approvals.length },
        { id: "tasks", label: "Tasks", count: data?.tasks.length ?? 0 },
      ]} />

      {!data ? <Empty title="Loading…" /> : !items.length ? (
        <div className="dk-panel"><Empty title="Inbox zero." sub="The agents will put anything that needs you here." /></div>
      ) : (
        <div className="dk-split">
          <div className="dk-split-l" role="listbox" aria-label="Waiting for you">
            {(["approval", "task"] as const).map((kind) => {
              const list = items.filter((i) => i.kind === kind);
              if (!list.length) return null;
              return (
                <div key={kind} className="dk-ig">
                  <div className="dk-ig-h">
                    {kind === "approval" && canApprove && <Check on={list.every((x) => x.kind === "approval" && ticked.has(x.a.id))} onChange={(v) => setTicked(new Set(v ? list.map((x) => (x as { a: Approval }).a.id) : []))} label="Select all approvals" />}
                    <span>{kind === "approval" ? "Approvals" : "Tasks"}</span>
                    <span className="n">{list.length}</span>
                  </div>
                  {list.map((it) => (
                    <div key={it.key} role="option" aria-selected={current?.key === it.key} className={`dk-ii ${current?.key === it.key ? "on" : ""}`} onClick={() => { setSel(it.key); document.querySelector(".op-phone .pane-screen")?.scrollTo({ top: 0, behavior: "smooth" }); }}>
                      {it.kind === "approval" && canApprove ? (
                        <Check on={ticked.has(it.a.id)} onChange={(v) => setTicked((old) => { const n = new Set(old); if (v) n.add(it.a.id); else n.delete(it.a.id); return n; })} label={`Select ${it.a.title}`} />
                      ) : (
                        <AgentAvatar agent={it.kind === "approval" ? it.a.agent : it.t.agent} size={26} />
                      )}
                      <span className="tx">
                        <b>{it.kind === "approval" ? it.a.title : it.t.title}</b>
                        <small>{it.kind === "approval" ? <span className="dk-why">{it.a.reason}</span> : it.t.detail}</small>
                      </span>
                      <time>{it.kind === "approval" ? (it.a.amount ? money(it.a.amount) : "") : it.t.amount ? money(it.t.amount) : ""}</time>
                    </div>
                  ))}
                </div>
              );
            })}
          </div>

          <div className="dk-split-r">
            {current?.kind === "approval" && (
              <div className="dk-preview">
                <div className="dk-preview-h">
                  <AgentAvatar agent={current.a.agent} size={34} />
                  <div>
                    <span className="k">{current.a.agent_label} · {stamp(current.a.requested_at)}{current.a.requested_by ? ` · priced by ${current.a.requested_by}` : ""}</span>
                    <h2>{current.a.title}</h2>
                  </div>
                </div>
                <div className="dk-facts">
                  <div><span>What happens</span><b>{approvalLine(current.a)}</b></div>
                  <div className="warn"><span>Why it needs you</span><b>{current.a.reason}</b></div>
                  <div><span>When you approve</span><b>{AFTER[current.a.action] ?? "The agent goes ahead exactly as shown."}</b></div>
                </div>
                <ApprovalDetail a={current.a} />
                <label className="op-field">
                  <span>Note to the agent (optional)</span>
                  <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. hold till Monday" />
                </label>
                <div className="dk-preview-acts">
                  <button type="button" className="btn btn-go" disabled={!canApprove} onClick={() => void decide(current.a, true)}>Approve</button>
                  <button type="button" className="btn btn-line" disabled={!canApprove} onClick={() => void decide(current.a, false)}>Reject</button>
                  <button type="button" className="btn btn-ghost-d" onClick={() => ctx.chat(current.a.agent)}><IChat size={16} /> Open chat</button>
                </div>
                {!canApprove && <p className="dk-fine">Only the owner can approve. It's waiting in their Inbox.</p>}
                <p className="dk-fine">Everything inside your rules goes out without you. Change the limits in Agents & rules.</p>
              </div>
            )}
            {current?.kind === "task" && <TaskPreview t={current.t} onDone={(s) => setTask(current.t, s)} />}
          </div>
        </div>
      )}
    </>
  );
}

const AFTER: Record<string, string> = {
  send_quote: "The quote goes to the customer as a link, and the Sales agent follows it up.",
  place_po: "The PO goes to the supplier, is queued for Tally, and the item comes off the reorder list.",
  change_credit_limit: "The new limit applies to the next quote and is queued for Tally.",
  send_offer: "Each past buyer gets the offer with a link to reserve.",
  ask_early_payment: "The customers get a polite request with a link to pick a date; the supplier is asked to take payment a week later.",
};

function ApprovalDetail({ a }: { a: Approval }) {
  const d = a.details ?? {};
  if (d.lines && d.cols) {
    return (
      <table className="dk-table compact">
        <thead><tr>{(d.cols as string[]).map((c, i) => <th key={c + i} className={i ? "r" : ""}>{c}</th>)}</tr></thead>
        <tbody>
          {(d.lines as string[][]).map((row, i) => (
            <tr key={i} className={row.includes("Best") ? "best" : ""}>{row.map((c, j) => <td key={j} className={j ? "r num" : ""}>{c}</td>)}</tr>
          ))}
        </tbody>
      </table>
    );
  }
  if (a.action === "change_credit_limit") {
    return <ul className="dk-reasons">{(d.reasons as string[] ?? []).map((r) => <li key={r} className="down">{r}</li>)}</ul>;
  }
  if (a.action === "send_offer") {
    return (
      <div className="dk-facts">
        <div><span>Offer price</span><b>{rate(d.price)} (list {rate(d.list)}, cost {rate(d.cost)})</b></div>
        <div><span>Stock</span><b>{d.qty} · {money(d.value)}</b></div>
        <div><span>Goes to</span><b>{(d.buyers as string[]).join(", ")}</b></div>
      </div>
    );
  }
  return null;
}

function TaskPreview({ t, onDone }: { t: Task; onDone: (status: string) => void }) {
  const ctx = useDesk();
  const [promise, setPromise] = useState(false);
  const open = () => {
    if (t.entity_type === "party" && t.entity_id) ctx.drawer({ type: "customer", id: t.entity_id });
    else if (t.entity_type === "quote" && t.entity_id) ctx.drawer({ type: "quote", id: t.entity_id });
    else if (t.entity_type === "item" && t.entity_id) ctx.drawer({ type: "item", id: t.entity_id });
    else if (t.entity_type === "cash_forecast") ctx.go("cash");
    else if (t.entity_type === "enquiry") ctx.go("sales", { tab: "enquiries" });
  };
  const partyId = t.entity_type === "party" ? t.entity_id : null;
  return (
    <div className="dk-preview">
      <div className="dk-preview-h">
        <AgentAvatar agent={t.agent} size={34} />
        <div>
          <span className="k">{AGENT_NAMES[t.agent]} · for {t.role} · {day(t.created_at)}</span>
          <h2>{t.title}</h2>
        </div>
      </div>
      {t.detail && <p className="dk-preview-t">{t.detail}</p>}
      {t.why.length > 0 && <ul className="dk-reasons">{t.why.map((w) => <li key={w}>{w}</li>)}</ul>}
      {promise && partyId && <PromiseForm partyId={partyId} onDone={() => { setPromise(false); onDone("done"); }} />}
      <div className="dk-preview-acts">
        {(t.kind === "call_customer" || t.kind === "missed_promise") && partyId && !promise && (
          <button type="button" className="btn btn-go" onClick={() => setPromise(true)}>Log a promise</button>
        )}
        {t.entity_id && <button type="button" className="btn btn-line" onClick={open}>Open</button>}
        <button type="button" className="btn btn-line" onClick={() => onDone("done")}>Done</button>
        <button type="button" className="btn btn-ghost-d" onClick={() => onDone("dismissed")}>Dismiss</button>
      </div>
    </div>
  );
}
