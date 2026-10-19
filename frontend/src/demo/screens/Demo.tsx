import { useCallback, useEffect, useMemo, useRef, useState, type ReactElement } from "react";
import ChatList from "../components/ChatList";
import Conversation from "../components/Conversation";
import { IconChats, IconCheck, IconGear, IconToday } from "../components/Icons";
import LinkOverlay, { type LinkView } from "../components/LinkOverlay";
import { Approvals, Settings, SidePanel, Today } from "../components/Screens";
import { buildWorld } from "../data/generate";
import { ask } from "../engine/ask";
import { setTyping } from "../engine/core";
import { approve, changeApproval, customerAccepted, customerPromised, supplierQuoted, tap } from "../engine/respond";
import { createDemo } from "../engine/seed";
import Desk from "../desk/Desk";
import type { Action, Business, DemoState, Go, Msg, Outcome, Tab, ThreadId, UiEffect } from "../engine/types";

function useMedia(q: string) {
  const [hit, setHit] = useState(() => typeof window !== "undefined" && window.matchMedia(q).matches);
  useEffect(() => {
    const m = window.matchMedia(q);
    const on = () => setHit(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, [q]);
  return hit;
}

/** Phone and tablet keep the chat app; 1100 px and wider gets the desk. */
const DESK_MEDIA = "(min-width: 1100px)";

type Props = { biz: Business; onEdit: () => void };

export default function Demo({ biz, onEdit }: Props) {
  const world = useMemo(() => buildWorld(biz), [biz]);
  const [state, setState] = useState<DemoState>(() => createDemo(world));
  const [tab, setTab] = useState<Tab>("chats");
  const wide = useMedia("(min-width: 900px)");
  const desk = useMedia(DESK_MEDIA);
  // The desk handles "open this chat" and "go to approvals" its own way.
  const deskUi = useRef<((ui: UiEffect) => boolean) | null>(null);
  const bindUi = useCallback((fn: ((ui: UiEffect) => boolean) | null) => {
    deskUi.current = fn;
  }, []);
  const [open, setOpen] = useState<ThreadId | null>(() => (window.matchMedia("(min-width: 900px)").matches ? "brief" : null));
  const [link, setLink] = useState<LinkView | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const stateRef = useRef(state);
  stateRef.current = state;
  const timers = useRef<number[]>([]);

  useEffect(() => () => timers.current.forEach((t) => window.clearTimeout(t)), []);

  // A fresh world (edited details) starts a fresh demo.
  useEffect(() => {
    timers.current.forEach((t) => window.clearTimeout(t));
    timers.current = [];
    setState(createDemo(world));
  }, [world]);

  // On wide screens a chat is always open, so the conversation pane is never empty.
  useEffect(() => {
    if (wide && !open) setOpen("brief");
  }, [wide, open]);

  const visibleThread = !desk && tab === "chats" ? open : null;

  // Reading a chat clears its unread count, as it does in any chat app.
  const visibleUnread = visibleThread ? state.threads[visibleThread].unread : 0;
  useEffect(() => {
    if (visibleThread && visibleUnread > 0) {
      setState((s) => ({ ...s, threads: { ...s.threads, [visibleThread]: { ...s.threads[visibleThread], unread: 0 } } }));
    }
  }, [visibleThread, visibleUnread]);

  const showToast = useCallback((text: string) => {
    setToast(text);
    window.setTimeout(() => setToast((t) => (t === text ? null : t)), 2600);
  }, []);

  const handleUi = useCallback((ui: UiEffect) => {
    if (deskUi.current?.(ui)) return;
    switch (ui.type) {
      case "openThread":
        setTab("chats");
        setOpen(ui.id);
        break;
      case "tab":
        setTab(ui.tab);
        break;
      case "toast":
        showToast(ui.text);
        break;
      default:
        setLink(ui);
    }
  }, [showToast]);

  /** Plays an agent outcome: immediate changes now, then each reply after
   *  its "typing…" delay. */
  const run = useCallback(
    (o: Outcome) => {
      if (o.now) setState(o.now);
      if (o.ui) handleUi(o.ui);
      for (const step of o.later ?? []) {
        const lead = Math.min(900, step.delay);
        timers.current.push(window.setTimeout(() => setState((s) => setTyping(s, step.thread, true)), step.delay - lead));
        timers.current.push(
          window.setTimeout(() => {
            setState((s) => setTyping(step.run(s), step.thread, false));
          }, step.delay),
        );
      }
    },
    [handleUi],
  );

  const onGo = useCallback((go: Go) => (go.to === "thread" ? handleUi({ type: "openThread", id: go.id }) : handleUi({ type: "tab", tab: go.tab })), [handleUi]);

  const onAction = (m: Msg, a: Action) => {
    if (!open) return;
    run(tap(stateRef.current, open, m.id, a));
  };

  const onSend = (text: string) => {
    if (!open) return;
    run(ask(stateRef.current, open, text));
  };

  const restart = () => {
    timers.current.forEach((t) => window.clearTimeout(t));
    timers.current = [];
    setState(createDemo(world));
    setTab("chats");
    setOpen(wide ? "brief" : null);
  };

  const waiting = state.approvals.filter((a) => a.status === "waiting").length;
  const unreadChats = state.order.filter((id) => state.threads[id].unread > 0).length;
  const thread = open ? state.threads[open] : null;
  const screenMode = tab !== "chats";

  const tabs: { id: Tab; label: string; icon: (c: string) => ReactElement; badge?: number }[] = [
    { id: "chats", label: "Chats", icon: (c) => <IconChats color={c} />, badge: unreadChats },
    { id: "approvals", label: "Approvals", icon: (c) => <IconCheck color={c} />, badge: waiting },
    { id: "today", label: "Today", icon: (c) => <IconToday color={c} /> },
    { id: "settings", label: "Settings", icon: (c) => <IconGear color={c} /> },
  ];

  return (
    <div className={`app ${desk ? "app-desk" : ""}`}>
      <div className="demobar" role="note">
        <span className="dot" aria-hidden="true" />
        <span className="what">
          Live demo for <b>{biz.company}</b> with sample data. Nothing is sent to anyone.
        </span>
        <button type="button" onClick={onEdit}>Change details</button>
        <button type="button" onClick={restart}>Start over</button>
      </div>

      {desk ? (
        <Desk biz={biz} state={state} run={run} set={setState} link={setLink} toast={showToast} bindUi={bindUi} />
      ) : (
      <>
      <div className={`shell ${!wide && open && tab === "chats" ? "has-thread" : ""} ${screenMode ? "screen-mode" : ""}`}>
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
          <div className="me" title={biz.owner}>{biz.owner.split(/\s+/).map((x) => x[0]).join("").slice(0, 2).toUpperCase()}</div>
        </nav>

        {screenMode ? (
          <main className="pane-screen">
            {tab === "approvals" && <Approvals state={state} onApprove={(id) => run(approve(stateRef.current, id))} onChange={(id) => run(changeApproval(stateRef.current, id))} />}
            {tab === "today" && <Today state={state} onOpen={(id) => handleUi({ type: "openThread", id })} />}
            {tab === "settings" && <Settings state={state} onLimits={(l) => setState((s) => ({ ...s, world: { ...s.world, limits: l } }))} />}
          </main>
        ) : (
          <>
            <section className="pane-list" aria-label="Chats">
              <ChatList state={state} active={open} onOpen={(id) => setOpen(id)} />
            </section>
            <main className="pane-conv">
              {thread && <Conversation thread={thread} now={state.clock} onBack={() => setOpen(null)} onAction={onAction} onSend={onSend} onGo={onGo} />}
            </main>
            <aside className="pane-side" aria-label="Details">
              <SidePanel state={state} thread={open} />
            </aside>
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
      </>
      )}

      {link && (
        <LinkOverlay
          key={JSON.stringify(link)}
          view={link}
          state={state}
          onClose={() => setLink(null)}
          onAcceptQuote={(v) => run(customerAccepted(stateRef.current, v.thread, v.msgId))}
          onPromise={(id, amount, date) => run(customerPromised(stateRef.current, id, amount, date))}
          onSupplierRate={(sup, v) => run(supplierQuoted(stateRef.current, sup, v))}
        />
      )}
      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
}
