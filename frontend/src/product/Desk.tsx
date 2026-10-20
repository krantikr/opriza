import { useCallback, useEffect, useMemo, useRef, useState, type ReactElement } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api } from "../api/client";
import type { Action, Go } from "../demo/engine/types";
import "../demo/desk/desk.css";
import { IAgents, IBox, IChat, IClose, IGear, IHome, IInbox, IReport, IRupee, ISales, ISearch, IUsers, IWallet } from "../demo/desk/icons";
import { Avatar, Initials } from "../demo/desk/ui";
import { useAuth } from "../lib/auth";
import ChatPanel, { ORDER } from "./Chat";
import { DeskContext, ROLES, type Ctx, type DrawerView, type Page } from "./ctx";
import { day, time, useData, useVersion, type Approval, type Me, type Role, type Task, type Thread } from "./data";
import { CustomerPanel, ItemPanel, QuotePanel } from "./panels";
import Agents from "./screens/Agents";
import Cash from "./screens/Cash";
import Collections from "./screens/Collections";
import Customers from "./screens/Customers";
import Home from "./screens/Home";
import Inbox from "./screens/Inbox";
import Reports from "./screens/Reports";
import Sales from "./screens/Sales";
import Settings from "./screens/Settings";
import Stock from "./screens/Stock";

const NAV: { id: Page; label: string; icon: () => ReactElement }[] = [
  { id: "home", label: "Home", icon: () => <IHome /> },
  { id: "inbox", label: "Inbox", icon: () => <IInbox /> },
  { id: "sales", label: "Sales", icon: () => <ISales /> },
  { id: "collect", label: "Collections", icon: () => <IRupee /> },
  { id: "stock", label: "Stock & Purchase", icon: () => <IBox /> },
  { id: "cash", label: "Cash", icon: () => <IWallet /> },
  { id: "customers", label: "Customers", icon: () => <IUsers /> },
  { id: "reports", label: "Reports", icon: () => <IReport /> },
];
const NAV_LOW: { id: Page; label: string; icon: () => ReactElement }[] = [
  { id: "agents", label: "Agents & rules", icon: () => <IAgents /> },
  { id: "settings", label: "Settings", icon: () => <IGear /> },
];
const PAGES = new Set<string>([...NAV, ...NAV_LOW].map((n) => n.id));
const PAGE_NAME = Object.fromEntries([...NAV, ...NAV_LOW].map((n) => [n.id, n.label])) as Record<Page, string>;

export default function Desk({ me }: { me: Me }) {
  const { page: raw } = useParams();
  const page: Page = raw && PAGES.has(raw) ? (raw as Page) : "home";
  const navigate = useNavigate();
  const { signOut } = useAuth();
  const { bump } = useVersion();
  const [params, setParams] = useState<Record<string, string>>({});
  const [role, setRole] = useState<Role>(me.user.desk_role);
  const [drawer, setDrawer] = useState<DrawerView | null>(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [thread, setThread] = useState("ask");
  const [pending, setPending] = useState<string | null>(null);
  const [cmdk, setCmdk] = useState(false);
  const [toastText, setToast] = useState<string | null>(null);
  const [menu, setMenu] = useState(false);
  const mainRef = useRef<HTMLElement>(null);

  const toast = useCallback((t: string) => setToast(t), []);
  useEffect(() => {
    if (!toastText) return;
    const t = window.setTimeout(() => setToast(null), 4200);
    return () => window.clearTimeout(t);
  }, [toastText]);

  const go = useCallback((p: Page, prm: Record<string, string> = {}) => {
    setParams(prm);
    setDrawer(null);
    navigate(`/app/${p === "home" ? "" : p}`);
    mainRef.current?.scrollTo({ top: 0 });
  }, [navigate]);

  const chat = useCallback((t: string, question?: string) => {
    setThread(t);
    setChatOpen(true);
    if (question) setPending(question);
  }, []);

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

  const ctx: Ctx = { me, role, go, params, drawer: setDrawer, chat, toast, act };

  // Keyboard: Ctrl/⌘ K search, Ctrl/⌘ J chat, Esc closes the top layer.
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      const mod = e.metaKey || e.ctrlKey;
      if (mod && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setCmdk((v) => !v);
      } else if (mod && e.key.toLowerCase() === "j") {
        e.preventDefault();
        setChatOpen((v) => !v);
      } else if (e.key === "Escape") {
        if (cmdk) setCmdk(false);
        else if (drawer) setDrawer(null);
        else if (menu) setMenu(false);
      }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [cmdk, drawer, menu]);

  const inbox = useData<{ tasks: Task[]; approvals: Approval[] }>(`/app/inbox?role=${role}`, 20000);
  const threads = useData<Thread[]>("/app/chat", 15000);
  const inboxCount = (inbox.data?.tasks.length ?? 0) + (role === "owner" ? inbox.data?.approvals.length ?? 0 : 0);
  const unread = (threads.data ?? []).filter((t) => t.unread > 0);

  // When an agent posts somewhere you're not looking, a small note appears
  // above the chat button, once per message.
  const seen = useRef<Set<string> | null>(null);
  const [note, setNote] = useState<{ thread: Thread; text: string } | null>(null);
  useEffect(() => {
    const list = threads.data;
    if (!list) return;
    const ids = new Set(list.map((t) => t.last?.id ?? "").filter(Boolean));
    if (seen.current) {
      const fresh = list.find((t) => t.last && !seen.current!.has(t.last.id) && t.last.from === "agent" && !(chatOpen && t.id === thread));
      if (fresh?.last) setNote({ thread: fresh, text: (fresh.last.text ?? (fresh.last.card as { title?: string } | undefined)?.title ?? "New update").replace(/\*\*/g, "") });
    }
    seen.current = ids;
  }, [threads.data, chatOpen, thread]);
  useEffect(() => {
    if (!note) return;
    const t = window.setTimeout(() => setNote(null), 7000);
    return () => window.clearTimeout(t);
  }, [note]);

  const onNavigate = (a: Action) => {
    const d = (a.data ?? {}) as Record<string, number>;
    if (a.id === "go-approvals") go("inbox", { tab: "approvals" });
    else if (a.id === "go-collect" || a.id === "go-call") d.party_id ? setDrawer({ type: "customer", id: d.party_id }) : go("collect");
    else if (a.id === "go-customer" && d.party_id) setDrawer({ type: "customer", id: d.party_id });
    else if (a.id === "view-quote" && d.quote_id) setDrawer({ type: "quote", id: d.quote_id });
    else if (a.id === "go-stock") go("stock");
    else if (a.id === "go-cash") go("cash");
  };
  const onGo = (g: Go) => {
    if (g.to === "thread") chat(g.id);
    else go(g.tab === "approvals" ? "inbox" : g.tab === "settings" ? "settings" : "home", g.tab === "approvals" ? { tab: "approvals" } : {});
  };

  let screen: ReactElement;
  switch (page) {
    case "inbox": screen = <Inbox />; break;
    case "sales": screen = <Sales />; break;
    case "collect": screen = <Collections />; break;
    case "customers": screen = <Customers />; break;
    case "stock": screen = <Stock />; break;
    case "cash": screen = <Cash />; break;
    case "reports": screen = <Reports />; break;
    case "agents": screen = <Agents />; break;
    case "settings": screen = <Settings />; break;
    default: screen = <Home />;
  }

  const biz = me.business!;
  return (
    <DeskContext.Provider value={ctx}>
      <div className={`desk ${chatOpen ? "chat-open" : ""}`}>
        <nav className="dk-side" aria-label="Main menu">
          <div className="dk-brand">Oprisa<i>.</i></div>
          <div className="dk-nav">
            {NAV.map((n) => (
              <button key={n.id} type="button" aria-current={page === n.id ? "page" : undefined} onClick={() => go(n.id)}>
                {n.icon()}
                <span>{n.label}</span>
                {n.id === "inbox" && inboxCount > 0 && <span className="dk-badge">{inboxCount}</span>}
              </button>
            ))}
          </div>
          <div className="dk-nav low">
            {NAV_LOW.map((n) => (
              <button key={n.id} type="button" aria-current={page === n.id ? "page" : undefined} onClick={() => go(n.id)}>
                {n.icon()}
                <span>{n.label}</span>
              </button>
            ))}
          </div>
          <div className="op-org">
            <b>{me.organisation?.name}</b>
            <span>{biz.mock ? "Sample data" : biz.tally_version} · {biz.city}</span>
          </div>
        </nav>

        <header className="dk-top">
          <div className="dk-crumb">{PAGE_NAME[page]}</div>
          <button type="button" className="dk-search" onClick={() => setCmdk(true)}>
            <ISearch />
            <span>Search customers, items, quotes — or type a question</span>
            <kbd>Ctrl K</kbd>
          </button>
          <div className="dk-top-r">
            <span className={`dk-sync ${biz.last_sync_status === "failed" ? "bad" : ""}`}
              title={biz.mock ? "This desk runs on the sample books; the clock is held at the data's today." : biz.last_sync_error ?? "Tally sync runs every 15 minutes"}>
              <i aria-hidden="true" />
              {biz.mock ? `Sample books · ${day(biz.now)} ${time(biz.now)}` : biz.last_sync_status === "failed" ? "Tally not reachable" : `Tally synced ${time(biz.last_sync_at)}`}
            </span>
            <span className={`op-brain ${me.brain}`} title={me.brain === "llm" ? "Agents think with a language model (falls back to rules)" : "Agents run on rules (AGENT_BRAIN=rules)"}>
              {me.brain === "llm" ? "AI" : "Rules"}
            </span>
            <label className="dk-role">
              <span>Viewing as</span>
              <select value={role} onChange={(e) => setRole(e.target.value as Role)} aria-label="Viewing as">
                {ROLES.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
              </select>
            </label>
            <div className="op-menu-wrap">
              <button type="button" className="dk-me" title={me.user.name} onClick={() => setMenu((v) => !v)} aria-haspopup="menu" aria-expanded={menu}>
                <Initials name={me.user.name} size={32} />
              </button>
              {menu && (
                <div className="op-menu" role="menu">
                  <div className="who"><b>{me.user.name}</b><span>{me.user.email}</span></div>
                  <button type="button" role="menuitem" onClick={() => { setMenu(false); go("settings"); }}>Settings</button>
                  <button type="button" role="menuitem" onClick={() => { setMenu(false); signOut(); navigate("/sign-in"); }}>Sign out</button>
                </div>
              )}
            </div>
          </div>
        </header>

        <main className="dk-main" ref={mainRef}>
          <div className="dk-page" key={page}>{screen}</div>
        </main>

        {chatOpen && (
          <aside className="dk-chat" aria-label="Chat with agents">
            <ChatPanel thread={thread} setThread={setThread} page={page} onClose={() => setChatOpen(false)}
              onNavigate={onNavigate} onGo={onGo} toast={toast} pendingQuestion={pending} clearPending={() => setPending(null)} clockNow={me.business?.now} />
          </aside>
        )}

        {!chatOpen && (
          <div className="dk-fab-wrap">
            {note && (
              <button type="button" className="dk-note" onClick={() => { chat(note.thread.id); setNote(null); }}>
                <Avatar t={note.thread} size={26} />
                <span>
                  <b>{note.thread.name}</b>
                  {note.text.length > 110 ? `${note.text.slice(0, 108)}…` : note.text}
                </span>
              </button>
            )}
            <button type="button" className="dk-fab" aria-label="Chat with agents (Ctrl J)"
              onClick={() => chat(unread.length ? unread.sort((a, b) => ORDER.indexOf(a.id) - ORDER.indexOf(b.id))[0]!.id : thread)}>
              <IChat />
              <span>Ask Oprisa</span>
              {unread.length > 0 && <span className="dk-badge">{unread.length}</span>}
            </button>
          </div>
        )}

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

        {cmdk && <CommandBar onClose={() => setCmdk(false)} go={go} open={setDrawer} chat={chat} />}
        {toastText && <div className="toast" role="status">{toastText}</div>}
      </div>
    </DeskContext.Provider>
  );

}

function CommandBar({ onClose, go, open, chat }: { onClose: () => void; go: Ctx["go"]; open: (d: DrawerView) => void; chat: Ctx["chat"] }) {
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const [hits, setHits] = useState<{ parties: { id: number; name: string; kind: string }[]; items: { id: number; name: string }[]; quotes: { id: number; number: string }[] } | null>(null);
  useEffect(() => {
    const t = q.trim();
    if (!t) {
      setHits(null);
      return;
    }
    const h = window.setTimeout(() => {
      api.get<typeof hits>(`/app/search?q=${encodeURIComponent(t)}`).then(setHits).catch(() => setHits(null));
    }, 160);
    return () => window.clearTimeout(h);
  }, [q]);
  const t = q.trim().toLowerCase();
  type Hit = { key: string; group: string; label: string; sub?: string; run: () => void };
  const list: Hit[] = useMemo(() => {
    const out: Hit[] = [];
    for (const n of [...NAV, ...NAV_LOW]) if (!t || n.label.toLowerCase().includes(t)) out.push({ key: `p-${n.id}`, group: "Go to", label: n.label, run: () => go(n.id) });
    if (t) {
      for (const p of hits?.parties ?? []) out.push({ key: `c-${p.id}`, group: p.kind === "customer" ? "Customers" : "Suppliers", label: p.name, run: () => open({ type: "customer", id: p.id }) });
      for (const i of hits?.items ?? []) out.push({ key: `i-${i.id}`, group: "Items", label: i.name, run: () => open({ type: "item", id: i.id }) });
      for (const x of hits?.quotes ?? []) out.push({ key: `q-${x.id}`, group: "Quotes", label: x.number, run: () => open({ type: "quote", id: x.id }) });
      if (/\d+\s*(mt|bag|bags|pc|pcs|box|boxes|ton)/i.test(t)) out.unshift({ key: "enq", group: "Do", label: `New enquiry: “${q.trim()}”`, sub: "Sales agent reads and prices it", run: () => go("sales", { paste: q.trim() }) });
      out.push({ key: "ask", group: "Ask", label: `Ask Oprisa: “${q.trim()}”`, sub: "Answers from your books", run: () => chat("ask", q.trim()) });
    }
    return out.slice(0, 14);
  }, [t, hits, q]);
  const pick = (h: Hit | undefined) => {
    if (!h) return;
    onClose();
    h.run();
  };
  return (
    <div className="dk-cmdk-wrap" onClick={onClose}>
      <div className="dk-cmdk" role="dialog" aria-modal="true" aria-label="Search" onClick={(e) => e.stopPropagation()}>
        <div className="dk-cmdk-in">
          <ISearch />
          <input autoFocus value={q} placeholder="Search, or ask “who owes me the most?”" aria-label="Search"
            onChange={(e) => { setQ(e.target.value); setSel(0); }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") { e.preventDefault(); setSel((v) => Math.min(list.length - 1, v + 1)); }
              else if (e.key === "ArrowUp") { e.preventDefault(); setSel((v) => Math.max(0, v - 1)); }
              else if (e.key === "Enter") pick(list[sel]);
            }} />
          <kbd>Esc</kbd>
        </div>
        <ul className="dk-cmdk-list" role="listbox">
          {list.map((h, i) => (
            <li key={h.key} role="option" aria-selected={i === sel}>
              {(i === 0 || list[i - 1]!.group !== h.group) && <div className="g">{h.group}</div>}
              <button type="button" className={i === sel ? "on" : ""} onMouseEnter={() => setSel(i)} onClick={() => pick(h)}>
                <b>{h.label}</b>
                {h.sub && <span>{h.sub}</span>}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
