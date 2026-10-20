import { useCallback, useEffect, useState, type ReactElement } from "react";
import { useNavigate } from "react-router-dom";

import { IconChats, IconCheck, IconGear, IconToday } from "../demo/components/Icons";
import type { Action, Go } from "../demo/engine/types";
import "../demo/desk/desk.css";
import { IClose } from "../demo/desk/icons";
import { useAuth } from "../lib/auth";
import ChatPanel, { ORDER } from "./Chat";
import { DeskContext, type Ctx, type DrawerView, type Page } from "./ctx";
import { day, time, useData, useVersion, type ChatMsg, type Me, type Thread } from "./data";
import { CustomerPanel, ItemPanel, QuotePanel } from "./panels";
import Home from "./screens/Home";
import Inbox from "./screens/Inbox";
import Settings from "./screens/Settings";

/* ---------------------------------------------------------------------------
   Oprisa on a phone: chat first, like the demo. Approvals and Today reuse the
   desk's Inbox and Home screens; tapping something opens the same drawers.
   --------------------------------------------------------------------------- */

type Tab = "chats" | "approvals" | "today" | "settings";

function preview(m: ChatMsg | null): string {
  if (!m) return "";
  if (m.from === "me") return `You: ${m.text ?? ""}`;
  if (m.text) return m.text.replace(/\*\*/g, "");
  const c = m.card as { kind?: string; title?: string; customer?: string; name?: string } | undefined;
  if (!c) return "";
  return c.title ?? (c.customer ? `${c.kind} · ${c.customer}` : c.name ?? "New message");
}

export default function Phone({ me }: { me: Me }) {
  const navigate = useNavigate();
  const { signOut } = useAuth();
  const { bump } = useVersion();
  const [tab, setTab] = useState<Tab>("chats");
  const [open, setOpen] = useState<string | null>(null);
  const [drawer, setDrawer] = useState<DrawerView | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [params, setParams] = useState<Record<string, string>>({});
  const [toastText, setToast] = useState<string | null>(null);
  const [q, setQ] = useState("");

  useEffect(() => {
    if (!toastText) return;
    const t = window.setTimeout(() => setToast(null), 4200);
    return () => window.clearTimeout(t);
  }, [toastText]);

  const threads = useData<Thread[]>("/app/chat", 15000);
  const inbox = useData<{ tasks: unknown[]; approvals: unknown[] }>(`/app/inbox?role=${me.user.desk_role}`, 20000);

  const go = useCallback((p: Page, prm: Record<string, string> = {}) => {
    setParams(prm);
    setDrawer(null);
    setOpen(null);
    setTab(p === "inbox" ? "approvals" : p === "settings" ? "settings" : "today");
  }, []);
  const chat = useCallback((t: string, question?: string) => {
    setTab("chats");
    setOpen(t);
    if (question) setPending(question);
  }, []);
  const toast = useCallback((t: string) => setToast(t), []);
  const act = useCallback(async <T,>(fn: () => Promise<T>, done?: string | ((r: T) => string)) => {
    try {
      const r = await fn();
      if (done) toast(typeof done === "string" ? done : done(r));
      bump();
      return r;
    } catch (e) {
      toast((e as Error).message);
      return null;
    }
  }, [bump, toast]);

  const ctx: Ctx = { me, role: me.user.desk_role, go, params, drawer: setDrawer, chat, toast, act };

  const onNavigate = (a: Action) => {
    const d = (a.data ?? {}) as Record<string, number>;
    if (a.id === "go-approvals") go("inbox", { tab: "approvals" });
    else if ((a.id === "go-collect" || a.id === "go-call" || a.id === "go-customer") && d.party_id) setDrawer({ type: "customer", id: d.party_id });
    else if (a.id === "view-quote" && d.quote_id) setDrawer({ type: "quote", id: d.quote_id });
    else go("home");
  };
  const onGo = (g: Go) => (g.to === "thread" ? chat(g.id) : go(g.tab === "approvals" ? "inbox" : g.tab === "settings" ? "settings" : "home"));

  const biz = me.business!;
  const list = (threads.data ?? [])
    .slice()
    .sort((a, b) => ORDER.indexOf(a.id) - ORDER.indexOf(b.id))
    .filter((t) => !q || t.name.toLowerCase().includes(q.toLowerCase()));
  const waiting = me.user.can_approve ? inbox.data?.approvals.length ?? 0 : 0;
  const unreadChats = (threads.data ?? []).filter((t) => t.unread > 0).length;
  const screenMode = tab !== "chats";

  const tabs: { id: Tab; label: string; icon: (c: string) => ReactElement; badge?: number }[] = [
    { id: "chats", label: "Chats", icon: (c) => <IconChats color={c} />, badge: unreadChats },
    { id: "approvals", label: "Inbox", icon: (c) => <IconCheck color={c} />, badge: waiting },
    { id: "today", label: "Today", icon: (c) => <IconToday color={c} /> },
    { id: "settings", label: "Settings", icon: (c) => <IconGear color={c} /> },
  ];

  return (
    <DeskContext.Provider value={ctx}>
      <div className="app op-phone">
        <div className={`shell ${open && tab === "chats" ? "has-thread" : ""} ${screenMode ? "screen-mode" : ""}`}>
          <nav className="rail" aria-label="Main">
            <div className="logo mark" aria-hidden="true">O<i>.</i></div>
            {tabs.map((t) => (
              <button key={t.id} type="button" aria-current={tab === t.id ? "page" : undefined} onClick={() => setTab(t.id)} aria-label={t.label}>
                {t.icon(tab === t.id ? "#e8a33d" : "#b3a79a")}
                <span>{t.label}</span>
                {!!t.badge && t.id === "approvals" && <span className="badge">{t.badge}</span>}
              </button>
            ))}
            <div className="spacer" />
            <button type="button" className="me" title={`Sign out ${me.user.name}`} onClick={() => { signOut(); navigate("/sign-in"); }}>
              {me.user.name.split(/\s+/).map((x) => x[0]).join("").slice(0, 2).toUpperCase()}
            </button>
          </nav>

          {screenMode ? (
            <main className="pane-screen">
              <div className="dk-page op-phone-page">
                {tab === "approvals" && <Inbox />}
                {tab === "today" && <Home />}
                {tab === "settings" && (
                  <>
                    <Settings />
                    <button type="button" className="btn btn-line btn-sm op-signout" onClick={() => { signOut(); navigate("/sign-in"); }}>Sign out</button>
                  </>
                )}
              </div>
            </main>
          ) : (
            <>
              <section className="pane-list" aria-label="Chats">
                <div className="list-head">
                  <div className="top">
                    <div className="mark">Oprisa<i>.</i></div>
                    <span className="sync">{biz.mock ? `Sample · ${day(biz.now)} ${time(biz.now)}` : `Tally ${time(biz.last_sync_at)}`}</span>
                  </div>
                  <label className="sr" htmlFor="op-search">Search chats</label>
                  <input id="op-search" className="search" placeholder="Search chats" value={q} onChange={(e) => setQ(e.target.value)} />
                </div>
                <div className="rows">
                  {list.map((t) => (
                    <button key={t.id} type="button" className="chat-row" aria-current={open === t.id} onClick={() => setOpen(t.id)}>
                      <div className="av" style={{ background: t.bg, color: t.fg }} aria-hidden="true">{t.letter}</div>
                      <div className="mid">
                        <div className="t1">
                          <span className="nm">{t.name}</span>
                          <span className={`tm ${t.unread ? "new" : ""}`}>{t.last ? time(t.last.ts) : ""}</span>
                        </div>
                        <div className="pv">{preview(t.last)}</div>
                      </div>
                      {t.unread > 0 && <span className="cnt" aria-label={`${t.unread} unread`}>{t.unread}</span>}
                    </button>
                  ))}
                  {!threads.data && <div className="list-tip">Loading…</div>}
                  <div className="list-tip">{me.organisation?.name}{biz.mock ? " · sample books. Messages to customers stay in the outbox." : ""}</div>
                </div>
              </section>
              <main className="pane-conv">
                {open && (
                  <ChatPanel compact thread={open} setThread={setOpen} page={null} onClose={() => setOpen(null)}
                    onNavigate={onNavigate} onGo={onGo} toast={toast} pendingQuestion={pending} clearPending={() => setPending(null)} clockNow={me.business?.now} />
                )}
              </main>
            </>
          )}
        </div>

        <nav className="mtabs" aria-label="Tabs">
          {tabs.map((t) => (
            <button key={t.id} type="button" aria-current={tab === t.id ? "page" : undefined} onClick={() => { setTab(t.id); if (t.id === "chats") setOpen(null); }}>
              {t.icon("currentColor")}
              {t.label}
              {!!t.badge && <span className="badge">{t.badge}</span>}
            </button>
          ))}
        </nav>

        {drawer && (
          <div className="dk-drawer-wrap" onClick={() => setDrawer(null)}>
            <aside className="dk-drawer" role="dialog" aria-modal="true" aria-label="Details" onClick={(e) => e.stopPropagation()}>
              <button type="button" className="dk-x dk-drawer-x" aria-label="Close" onClick={() => setDrawer(null)}>
                <IClose />
              </button>
              {drawer.type === "customer" && <CustomerPanel id={drawer.id} />}
              {drawer.type === "quote" && <QuotePanel id={drawer.id} />}
              {drawer.type === "item" && <ItemPanel id={drawer.id} />}
            </aside>
          </div>
        )}
        {toastText && <div className="toast" role="status">{toastText}</div>}
      </div>
    </DeskContext.Provider>
  );
}
