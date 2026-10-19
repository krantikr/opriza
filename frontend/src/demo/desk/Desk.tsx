import { useCallback, useEffect, useMemo, useRef, useState, type ReactElement } from "react";
import Conversation from "../components/Conversation";
import type { LinkView } from "../components/LinkOverlay";
import { ask } from "../engine/ask";
import { shortName } from "../engine/core";
import { tap } from "../engine/respond";
import type { Action, Business, DemoState, Go, Msg, Outcome, Tab, ThreadId, UiEffect } from "../engine/types";
import { clock, money } from "../lib/format";
import "./desk.css";
import Agents, { SettingsPage } from "./Agents";
import Cash from "./Cash";
import Collections from "./Collections";
import { ROLES, type Ctx, type DrawerView, type Page, type PageParams, type Role } from "./ctx";
import Customers, { CustomerPanel } from "./Customers";
import Home from "./Home";
import { IAgents, IBox, IChat, ICheck, IClose, IGear, IHome, IInbox, IReport, IRupee, ISales, ISearch, IUsers, IWallet } from "./icons";
import Inbox from "./Inbox";
import Reports from "./Reports";
import Sales, { QuotePanel } from "./Sales";
import { allQuotes, inboxItems, moneyWaiting } from "./select";
import Stock, { ProductPanel } from "./Stock";
import { Avatar, Initials } from "./ui";

type Props = {
  biz: Business;
  state: DemoState;
  run: (o: Outcome) => void;
  set: (fn: (s: DemoState) => DemoState) => void;
  link: (v: LinkView) => void;
  toast: (t: string) => void;
  /** The shell registers how it handles "open chat" and "open tab" effects. */
  bindUi: (fn: ((ui: UiEffect) => boolean) | null) => void;
};

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
const PAGE_NAME: Record<Page, string> = Object.fromEntries([...NAV, ...NAV_LOW].map((n) => [n.id, n.label])) as Record<Page, string>;

const TAB_PAGE: Record<Tab, Page> = { chats: "home", approvals: "inbox", today: "home", settings: "settings" };

const CHAT_ORDER: ThreadId[] = ["ask", "brief", "sales", "collect", "stock", "cash", "score"];

/** Questions the chat suggests, from the screen you're on. */
function contextQuestions(s: DemoState, page: Page): string[] {
  const w = s.world;
  switch (page) {
    case "collect":
      return ["Who owes me the most?", "Promises due this week", "Which customers are grade D?"];
    case "sales":
      return ["Which quotes are still open?", "What's my win rate this month?", "Who stopped buying?"];
    case "stock":
      return ["What should I reorder this week?", "Show idle stock", `Stock of ${shortName(w.products[1]!)}`];
    case "cash":
      return ["Cash position today", "Payments due this week", "Who can pay early?"];
    case "customers":
      return ["Top 5 customers", "Who stopped buying?", "Which customers are grade D?"];
    default:
      return ["What needs me today?", "Margin by month", "Sales this week"];
  }
}

export default function Desk({ biz, state, run, set, link, toast, bindUi }: Props) {
  const [page, setPage] = useState<Page>("home");
  const [params, setParams] = useState<PageParams>({});
  const [role, setRole] = useState<Role>("owner");
  const [drawer, setDrawer] = useState<DrawerView | null>(null);
  const [chatOpen, setChatOpen] = useState(false);
  const [chatThread, setChatThread] = useState<ThreadId>("ask");
  const [cmdk, setCmdk] = useState(false);
  const [note, setNote] = useState<{ thread: ThreadId; text: string } | null>(null);
  const [resultSeen, setResultSeen] = useState(false);
  const [tourHidden, setTourHidden] = useState(false);
  const stateRef = useRef(state);
  stateRef.current = state;
  const mainRef = useRef<HTMLElement>(null);

  const go = useCallback((p: Page, prm: PageParams = {}) => {
    setPage(p);
    setParams(prm);
    setDrawer(null);
    mainRef.current?.scrollTo({ top: 0 });
  }, []);

  const chat = useCallback(
    (thread: ThreadId, question?: string) => {
      setChatThread(thread);
      setChatOpen(true);
      setNote(null);
      if (question) run(ask(stateRef.current, thread, question));
    },
    [run],
  );

  // Chat buttons that navigate ("Open approvals") move the desk instead.
  useEffect(() => {
    bindUi((ui) => {
      if (ui.type === "openThread") {
        chat(ui.id);
        return true;
      }
      if (ui.type === "tab") {
        go(TAB_PAGE[ui.tab]);
        return true;
      }
      return false;
    });
    return () => bindUi(null);
  }, [bindUi, chat, go]);

  // Reading a chat clears its unread count.
  const visible = chatOpen ? chatThread : null;
  const visibleUnread = visible ? state.threads[visible].unread : 0;
  useEffect(() => {
    if (visible && visibleUnread > 0) set((s) => ({ ...s, threads: { ...s.threads, [visible]: { ...s.threads[visible], unread: 0 } } }));
  }, [visible, visibleUnread, set]);

  // When an agent posts somewhere you're not looking, a small note appears
  // above the chat button. One at a time, gone after a few seconds.
  const lastCounts = useRef<Record<string, number> | null>(null);
  useEffect(() => {
    const counts = Object.fromEntries(CHAT_ORDER.map((id) => [id, state.threads[id].messages.length]));
    const prev = lastCounts.current;
    lastCounts.current = counts;
    if (!prev) return;
    for (const id of CHAT_ORDER) {
      if (counts[id]! <= prev[id]!) continue;
      if (visible === id) continue;
      const m = state.threads[id].messages.at(-1);
      if (!m || m.from !== "agent") continue;
      const text = (m.text ?? (m.card?.kind === "alert" ? m.card.title : m.card?.kind === "quote" ? `Quote ${m.card.no} ready for ${m.card.customer}` : "New update")).replace(/\*\*/g, "");
      setNote({ thread: id, text });
    }
  }, [state.threads, visible]);
  useEffect(() => {
    if (!note) return;
    const t = window.setTimeout(() => setNote(null), 6000);
    return () => window.clearTimeout(t);
  }, [note]);

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
      }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [cmdk, drawer]);

  const ctx: Ctx = { s: state, role, run, set, go, drawer: setDrawer, chat, toast, link };

  const inboxCount = useMemo(() => inboxItems(state).length, [state]);
  const enquiriesWaiting = state.desk.enquiries.filter((e) => !e.quoted).length;
  const badges: Partial<Record<Page, number>> = { inbox: inboxCount, sales: enquiriesWaiting };
  const unreadChats = CHAT_ORDER.filter((id) => state.threads[id].unread > 0).length;

  const thread = state.threads[chatThread];
  const shownThread = chatThread === "ask" ? { ...thread, suggestions: contextQuestions(state, page) } : thread;
  const onAction = (m: Msg, a: Action) => run(tap(stateRef.current, chatThread, m.id, a));
  const onSend = (text: string) => {
    run(ask(stateRef.current, chatThread, text));
    set((s) => ({ ...s, desk: { ...s.desk, tour: { ...s.desk.tour, ask: true } } }));
  };
  const onGo = (g: Go) => (g.to === "thread" ? chat(g.id) : go(TAB_PAGE[g.tab]));

  const tour = state.desk.tour;
  const tourDone = tour.inbox && tour.remind && tour.ask;

  let screen: ReactElement;
  switch (page) {
    case "inbox":
      screen = <Inbox ctx={ctx} params={params} />;
      break;
    case "sales":
      screen = <Sales ctx={ctx} params={params} />;
      break;
    case "collect":
      screen = <Collections ctx={ctx} params={params} />;
      break;
    case "customers":
      screen = <Customers ctx={ctx} params={params} />;
      break;
    case "stock":
      screen = <Stock ctx={ctx} />;
      break;
    case "cash":
      screen = <Cash ctx={ctx} />;
      break;
    case "reports":
      screen = <Reports ctx={ctx} params={params} />;
      break;
    case "agents":
      screen = <Agents ctx={ctx} />;
      break;
    case "settings":
      screen = <SettingsPage ctx={ctx} />;
      break;
    default:
      screen = <Home ctx={ctx} />;
  }

  return (
    <div className={`desk ${chatOpen ? "chat-open" : ""}`}>
      <nav className="dk-side" aria-label="Main menu">
        <div className="dk-brand">
          Oprisa<i>.</i>
        </div>
        <div className="dk-nav">
          {NAV.map((n) => (
            <button key={n.id} type="button" aria-current={page === n.id ? "page" : undefined} onClick={() => go(n.id)}>
              {n.icon()}
              <span>{n.label}</span>
              {!!badges[n.id] && <span className="dk-badge">{badges[n.id]}</span>}
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
        {!tourHidden && !tourDone && (
          <div className="dk-tour" aria-label="Try 3 things">
            <div className="dk-tour-h">
              <b>Try 3 things</b>
              <button type="button" aria-label="Hide" onClick={() => setTourHidden(true)}>
                <IClose size={14} />
              </button>
            </div>
            <TourItem done={tour.inbox} label="Approve items in Inbox" onClick={() => go("inbox")} />
            <TourItem done={tour.remind} label="Send reminders to several customers at once" onClick={() => go("collect", { tab: "dues" })} />
            <TourItem done={tour.ask} label="Ask the chat a question" onClick={() => chat("ask")} />
            <div className="dk-tour-bar"><b style={{ width: `${(Number(tour.inbox) + Number(tour.remind) + Number(tour.ask)) * 33.4}%` }} /></div>
          </div>
        )}
      </nav>

      <header className="dk-top">
        <div className="dk-crumb">{PAGE_NAME[page]}</div>
        <button type="button" className="dk-search" onClick={() => setCmdk(true)}>
          <ISearch />
          <span>Search customers, items, quotes — or type a question</span>
          <kbd>Ctrl K</kbd>
        </button>
        <div className="dk-top-r">
          <span className="dk-sync" title="Tally sync runs every 15 minutes">
            <i aria-hidden="true" /> Tally synced {clock(state.clock - 2)}
          </span>
          <label className="dk-role">
            <span>Viewing as</span>
            <select value={role} onChange={(e) => setRole(e.target.value as Role)} aria-label="Viewing as">
              {ROLES.map((r) => (
                <option key={r.id} value={r.id}>{r.label}</option>
              ))}
            </select>
          </label>
          <button type="button" className="dk-me" title={biz.owner} onClick={() => go("settings")}>
            <Initials name={biz.owner || "You"} size={32} />
          </button>
        </div>
      </header>

      <main className="dk-main" ref={mainRef}>
        <div className="dk-page" key={page}>{screen}</div>
      </main>

      {chatOpen && (
        <aside className="dk-chat" aria-label="Chat with agents">
          <div className="dk-chat-h">
            <div className="dk-chat-agents" role="tablist" aria-label="Agents">
              {CHAT_ORDER.map((id) => {
                const t = state.threads[id];
                return (
                  <button key={id} type="button" role="tab" aria-selected={chatThread === id} title={t.name} onClick={() => setChatThread(id)}>
                    <Avatar t={t} size={30} />
                    {t.unread > 0 && chatThread !== id && <i className="dot" aria-label="unread" />}
                  </button>
                );
              })}
            </div>
            <button type="button" className="dk-x" aria-label="Close chat" onClick={() => setChatOpen(false)}>
              <IClose />
            </button>
          </div>
          <div className="dk-chat-b">
            <Conversation key={chatThread} thread={shownThread} now={state.clock} onBack={() => setChatOpen(false)} onAction={onAction} onSend={onSend} onGo={onGo} />
          </div>
        </aside>
      )}

      {!chatOpen && (
        <div className="dk-fab-wrap">
          {note && (
            <button type="button" className="dk-note" onClick={() => chat(note.thread)}>
              <Avatar t={state.threads[note.thread]} size={26} />
              <span>
                <b>{state.threads[note.thread].name}</b>
                {note.text.length > 110 ? `${note.text.slice(0, 108)}…` : note.text}
              </span>
            </button>
          )}
          <button type="button" className="dk-fab" aria-label="Chat with agents (Ctrl J)" onClick={() => chat(unreadChats ? CHAT_ORDER.find((id) => state.threads[id].unread > 0)! : chatThread)}>
            <IChat />
            <span>Ask Oprisa</span>
            {unreadChats > 0 && <span className="dk-badge">{unreadChats}</span>}
          </button>
        </div>
      )}

      {drawer && (
        <div className="dk-drawer-wrap" onClick={() => setDrawer(null)}>
          <aside className="dk-drawer" role="dialog" aria-modal="true" aria-label="Details" onClick={(e) => e.stopPropagation()}>
            <button type="button" className="dk-x dk-drawer-x" aria-label="Close" onClick={() => setDrawer(null)}>
              <IClose />
            </button>
            {drawer.type === "customer" && <CustomerPanel ctx={ctx} id={drawer.id} />}
            {drawer.type === "quote" && <QuotePanel ctx={ctx} no={drawer.no} />}
            {drawer.type === "product" && <ProductPanel ctx={ctx} idx={drawer.idx} />}
          </aside>
        </div>
      )}

      {cmdk && <CommandBar ctx={ctx} onClose={() => setCmdk(false)} />}

      {tourDone && !resultSeen && <Result state={state} onClose={() => setResultSeen(true)} />}
    </div>
  );
}

function TourItem({ done, label, onClick }: { done: boolean; label: string; onClick: () => void }) {
  return (
    <button type="button" className={`dk-tour-i ${done ? "done" : ""}`} onClick={onClick}>
      <span className="b" aria-hidden="true">{done && <ICheck size={12} />}</span>
      <span>{label}</span>
    </button>
  );
}

/* ---------------------------------------------------------------------------
   Ctrl/⌘ K: find anything, or ask
   --------------------------------------------------------------------------- */

type Hit = { key: string; group: string; label: string; sub?: string; run: () => void };

function CommandBar({ ctx, onClose }: { ctx: Ctx; onClose: () => void }) {
  const [q, setQ] = useState("");
  const [sel, setSel] = useState(0);
  const s = ctx.s;
  const w = s.world;
  const t = q.trim().toLowerCase();

  const hits: Hit[] = [];
  const pages: [Page, string][] = [...NAV, ...NAV_LOW].map((n) => [n.id, n.label]);
  for (const [id, label] of pages) if (!t || label.toLowerCase().includes(t)) hits.push({ key: `p-${id}`, group: "Go to", label, run: () => ctx.go(id) });
  if (t) {
    for (const c of w.customers.filter((c) => c.name.toLowerCase().includes(t) || c.contact.toLowerCase().includes(t)).slice(0, 5))
      hits.push({ key: `c-${c.id}`, group: "Customers", label: c.name, sub: `${c.contact} · grade ${c.grade} · owes ${money(c.outstanding)}`, run: () => ctx.drawer({ type: "customer", id: c.id }) });
    w.products.forEach((p, i) => {
      if (p.name.toLowerCase().includes(t) || p.alias.some((a) => a.toLowerCase().startsWith(t))) hits.push({ key: `i-${i}`, group: "Items", label: p.name, sub: `${Math.round(p.stock / p.perDay)} days of stock`, run: () => ctx.drawer({ type: "product", idx: i }) });
    });
    for (const qq of allQuotes(s).filter((x) => x.no.toLowerCase().includes(t)).slice(0, 4))
      hits.push({ key: `q-${qq.no}`, group: "Quotes", label: qq.no, sub: `${w.customers.find((c) => c.id === qq.customerId)?.name} · ${money(qq.value)}`, run: () => ctx.drawer({ type: "quote", no: qq.no }) });
    if (/^(quote|rate|need|bhav)\b/.test(t) || /\d+\s*(mt|bag|pc|pcs|kg|box|coil|roll)/.test(t)) hits.unshift({ key: "mkq", group: "Do", label: `Make a quote: “${q.trim()}”`, sub: "Sales agent prices it from Tally", run: () => ctx.chat("sales", q.trim()) });
    hits.push({ key: "ask", group: "Ask", label: `Ask Oprisa: “${q.trim()}”`, sub: "Answers from your Tally data", run: () => ctx.chat("ask", q.trim()) });
  }
  const list = hits.slice(0, 12);
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
          <input
            autoFocus
            value={q}
            placeholder="Search, or type “quote 20 MT TMT for Mehta”"
            onChange={(e) => {
              setQ(e.target.value);
              setSel(0);
            }}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setSel((v) => Math.min(list.length - 1, v + 1));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setSel((v) => Math.max(0, v - 1));
              } else if (e.key === "Enter") pick(list[sel]);
            }}
            aria-label="Search"
          />
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

/* ---------------------------------------------------------------------------
   The end of the guided tour: what the visitor got done
   --------------------------------------------------------------------------- */

function Result({ state, onClose }: { state: DemoState; onClose: () => void }) {
  const done = state.desk.log.filter((l) => !l.yday && l.at >= 615).reduce((a, l) => a + l.count, 0);
  const mw = moneyWaiting(state);
  return (
    <div className="dk-modal-wrap" onClick={onClose}>
      <div className="dk-modal" role="dialog" aria-modal="true" aria-label="Your result" onClick={(e) => e.stopPropagation()}>
        <div className="dk-modal-top">
          <span className="k">Your 2-minute result</span>
          <h2>{money(state.collectedToday + state.wonToday)} promised or won</h2>
          <p>That's what {state.world.biz.company} would see on a normal morning, with the agents doing the legwork.</p>
        </div>
        <div className="dk-modal-grid">
          <div><b>{done}</b><span>tasks done by agents for you</span></div>
          <div><b>{money(mw.quotes)}</b><span>in open quotes, being followed up</span></div>
          <div><b>{state.approvals.filter((a) => a.status !== "waiting").length}</b><span>approvals cleared</span></div>
        </div>
        <div className="dk-modal-acts">
          <a className="btn btn-go" href="/contact">Book a pilot for {state.world.biz.company} →</a>
          <button type="button" className="btn btn-line" onClick={onClose}>Keep exploring</button>
        </div>
      </div>
    </div>
  );
}
