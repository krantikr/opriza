import { useEffect, useMemo, useState } from "react";
import CardView from "../components/CardView";
import { approveMany } from "../engine/desk";
import { approve, changeApproval, tap } from "../engine/respond";
import type { Action, Go } from "../engine/types";
import { clock } from "../lib/format";
import type { Ctx, PageParams } from "./ctx";
import { IChat } from "./icons";
import { inboxItems, inboxTitle, type InboxItem } from "./select";
import { Avatar, Check, Empty, PageHead } from "./ui";

const GROUPS: InboxItem["group"][] = ["Approvals", "Waiting for your tap", "Replies"];

export default function Inbox({ ctx, params }: { ctx: Ctx; params: PageParams }) {
  const s = ctx.s;
  const items = useMemo(() => inboxItems(s), [s]);
  const [sel, setSel] = useState<string | null>(params.tab ?? null);
  const [ticked, setTicked] = useState<Set<string>>(new Set());
  const current = items.find((i) => i.key === sel) ?? items[0];

  const markTour = () => ctx.set((st) => ({ ...st, desk: { ...st.desk, tour: { ...st.desk.tour, inbox: true } } }));
  const nextAfter = (key: string) => {
    const i = items.findIndex((x) => x.key === key);
    const nxt = items[i + 1] ?? items[i - 1];
    setSel(nxt ? nxt.key : null);
  };

  const approvals = items.filter((i): i is Extract<InboxItem, { kind: "approval" }> => i.kind === "approval");
  const tickedIds = approvals.filter((a) => ticked.has(a.key)).map((a) => a.approval.id);

  const approveSelected = (ids: string[]) => {
    if (!ids.length) return;
    ctx.run(approveMany(ctx.s, ids));
    setTicked(new Set());
    ctx.toast(`${ids.length} approved — the agents are sending them out`);
  };

  const act = (it: InboxItem, a: Action) => {
    if (it.kind !== "msg") return;
    const nav = a.id.startsWith("go-") || a.id.startsWith("view-");
    if (!nav) nextAfter(it.key);
    ctx.run(tap(ctx.s, it.thread, it.msg.id, a));
    if (!nav) markTour();
  };

  // Keyboard: J / K to move, A to approve or take the main action.
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || e.metaKey || e.ctrlKey) return;
      if (!items.length) return;
      const i = Math.max(0, items.findIndex((x) => x.key === current?.key));
      if (e.key === "j") setSel(items[Math.min(items.length - 1, i + 1)]!.key);
      else if (e.key === "k") setSel(items[Math.max(0, i - 1)]!.key);
      else if (e.key === "a" && current) {
        if (current.kind === "approval") {
          nextAfter(current.key);
          ctx.run(approve(ctx.s, current.approval.id));
          markTour();
        } else {
          const a = current.actions.find((x) => x.primary) ?? current.actions[0];
          if (a) act(current, a);
        }
      }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  });

  return (
    <>
      <PageHead title="Inbox" sub={<>Everything waiting for you, from every agent. <kbd>J</kbd>/<kbd>K</kbd> to move, <kbd>A</kbd> to do what the agent suggests.</>}>
        {approvals.length > 0 && (
          <>
            <button type="button" className="btn btn-line btn-sm" disabled={!tickedIds.length} onClick={() => approveSelected(tickedIds)}>
              Approve selected{tickedIds.length ? ` (${tickedIds.length})` : ""}
            </button>
            <button type="button" className="btn btn-go btn-sm" onClick={() => approveSelected(approvals.map((a) => a.approval.id))}>
              Approve all {approvals.length}
            </button>
          </>
        )}
      </PageHead>

      {!items.length ? (
        <div className="dk-panel"><Empty title="Inbox zero." sub="The agents will put anything that needs you here." /></div>
      ) : (
        <div className="dk-split">
          <div className="dk-split-l" role="listbox" aria-label="Waiting for you">
            {GROUPS.map((g) => {
              const list = items.filter((i) => i.group === g);
              if (!list.length) return null;
              return (
                <div key={g} className="dk-ig">
                  <div className="dk-ig-h">
                    {g === "Approvals" && <Check on={list.every((x) => ticked.has(x.key))} onChange={(v) => setTicked(new Set(v ? list.map((x) => x.key) : []))} label="Select all approvals" />}
                    <span>{g}</span>
                    <span className="n">{list.length}</span>
                  </div>
                  {list.map((it) => {
                    const { title, sub } = inboxTitle(s, it);
                    const t = s.threads[it.kind === "approval" ? it.approval.thread : it.thread];
                    return (
                      <div key={it.key} role="option" aria-selected={current?.key === it.key} className={`dk-ii ${current?.key === it.key ? "on" : ""}`} onClick={() => setSel(it.key)}>
                        {it.kind === "approval" ? <Check on={ticked.has(it.key)} onChange={(v) => setTicked((old) => { const n = new Set(old); if (v) n.add(it.key); else n.delete(it.key); return n; })} label={`Select ${title}`} /> : <Avatar t={t} size={26} />}
                        <span className="tx">
                          <b>{title}</b>
                          <small>{it.kind === "approval" ? <span className="dk-why">{it.approval.why}</span> : sub}</small>
                        </span>
                        <time>{it.kind === "msg" ? clock(it.msg.at) : it.approval.type}</time>
                      </div>
                    );
                  })}
                </div>
              );
            })}
          </div>

          <div className="dk-split-r">
            {current && current.kind === "approval" && (
              <div className="dk-preview">
                <div className="dk-preview-h">
                  <Avatar t={s.threads[current.approval.thread]} size={34} />
                  <div>
                    <span className="k">{current.approval.type} · asked by {current.approval.who}</span>
                    <h2>{current.approval.title}</h2>
                  </div>
                </div>
                <div className="dk-facts">
                  <div><span>Amount and terms</span><b>{current.approval.detail}</b></div>
                  <div className="warn"><span>Why it needs you</span><b>{current.approval.why}</b></div>
                  <div><span>When you approve</span><b>{current.approval.after}</b></div>
                </div>
                <div className="dk-preview-acts">
                  <button type="button" className="btn btn-go" onClick={() => { nextAfter(current.key); ctx.run(approve(ctx.s, current.approval.id)); markTour(); }}>Approve</button>
                  <button type="button" className="btn btn-line" onClick={() => { nextAfter(current.key); ctx.run(changeApproval(ctx.s, current.approval.id)); markTour(); }}>Send back</button>
                  <button type="button" className="btn btn-ghost-d" onClick={() => ctx.chat(current.approval.thread)}><IChat size={16} /> Discuss in chat</button>
                </div>
                <p className="dk-fine">Everything inside your rules goes out without you. Only items like this one wait here. Limits are in Agents &amp; rules.</p>
              </div>
            )}
            {current && current.kind === "msg" && (
              <div className="dk-preview">
                <div className="dk-preview-h">
                  <Avatar t={s.threads[current.thread]} size={34} />
                  <div>
                    <span className="k">{s.threads[current.thread].name} · {clock(current.msg.at)}</span>
                    <h2>{inboxTitle(s, current).title}</h2>
                  </div>
                </div>
                {current.msg.text && <p className="dk-preview-t">{current.msg.text.replace(/\*\*/g, "")}</p>}
                {current.msg.card && (
                  <div className="dk-card-host">
                    <CardView card={current.msg.card} onGo={(g: Go) => (g.to === "thread" ? ctx.chat(g.id) : ctx.go("inbox"))} />
                  </div>
                )}
                <div className="dk-preview-acts">
                  {(current.msg.actions ?? []).map((a) => (
                    <button key={a.id + a.label} type="button" className={`btn ${a.primary ? "btn-go" : "btn-line"}`} onClick={() => act(current, a)}>{a.label}</button>
                  ))}
                  <button type="button" className="btn btn-ghost-d" onClick={() => ctx.chat(current.thread)}><IChat size={16} /> Open chat</button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );
}
