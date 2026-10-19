import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";
import type { Action, Go, Msg, Thread } from "../engine/types";
import { clock } from "../lib/format";
import CardView from "./CardView";
import { IconBack, IconSend } from "./Icons";

/** **bold** in agent text, nothing else. */
function rich(text: string): ReactNode {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((p, i) => (p.startsWith("**") && p.endsWith("**") ? <b key={i}>{p.slice(2, -2)}</b> : <Fragment key={i}>{p}</Fragment>));
}

type MsgProps = {
  m: Msg;
  onAction: (m: Msg, a: Action) => void;
  onGo: (go: Go) => void;
};

function MessageView({ m, onAction, onGo }: MsgProps) {
  if (m.from === "system") return <div className="day">{m.text}</div>;
  const mine = m.from === "me";
  const wide = !!m.card;
  const taken = !!m.chosen;
  return (
    <div className={`msg ${mine ? "out" : "in"} ${wide ? "wide" : ""}`}>
      <div className="bubble">
        {m.text && <div className="btxt">{rich(m.text)}</div>}
        {m.card && <CardView card={m.card} onGo={onGo} />}
        {m.status && <div className="status">{m.status}</div>}
        <div className="meta">
          <span>{clock(m.at)}</span>
          {mine && <span className="ticks" aria-label="Read">✓✓</span>}
        </div>
        {m.actions && m.actions.length > 0 && (
          <div className="acts">
            {m.actions.map((a) => {
              const nav = a.id.startsWith("go-") || a.id.startsWith("view-");
              const chosen = m.chosen === a.label;
              return (
                <button
                  key={a.id + a.label}
                  type="button"
                  className={`${a.primary ? "p" : ""} ${chosen ? "chosen" : ""}`}
                  disabled={taken && !nav}
                  onClick={() => onAction(m, a)}
                >
                  {chosen ? `✓ ${a.label}` : a.label}
                </button>
              );
            })}
          </div>
        )}
      </div>
      {m.chips && m.chips.length > 0 && (
        <div className="chips">
          {m.chips.map((a) => (
            <button
              key={a.label}
              type="button"
              className={`chip ${m.chosen === a.label ? "chosen" : ""}`}
              disabled={taken}
              onClick={() => onAction(m, a)}
            >
              {a.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

type Props = {
  thread: Thread;
  now: number;
  onBack: () => void;
  onAction: (m: Msg, a: Action) => void;
  onSend: (text: string) => void;
  onGo: (go: Go) => void;
};

export default function Conversation({ thread, now, onBack, onAction, onSend, onGo }: Props) {
  const [draft, setDraft] = useState("");
  const feed = useRef<HTMLDivElement>(null);
  const count = thread.messages.length;
  const last = thread.messages[count - 1];
  // Whether the reader is at the bottom of the chat. Only then do new
  // messages scroll the chat; someone reading or tapping further up is
  // left where they are and gets a "new messages" pill, as in WhatsApp.
  const atBottom = useRef(true);
  const shownThread = useRef<string | null>(null);
  const [unseen, setUnseen] = useState(false);

  const toBottom = (smooth: boolean) => {
    const el = feed.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" });
    atBottom.current = true;
    setUnseen(false);
  };

  useEffect(() => {
    if (shownThread.current !== thread.id) {
      shownThread.current = thread.id;
      toBottom(false);
      return;
    }
    if (atBottom.current || last?.from === "me") toBottom(true);
    else setUnseen(true);
  }, [count, thread.typing, thread.id]);

  // Tapping a button means "show me what happens", so the reply is followed.
  const act = (m: Msg, a: Action) => {
    atBottom.current = true;
    onAction(m, a);
  };

  const onScroll = () => {
    const el = feed.current;
    if (!el) return;
    atBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    if (atBottom.current && unseen) setUnseen(false);
  };

  useEffect(() => setDraft(""), [thread.id]);

  const submit = (text: string) => {
    const t = text.trim();
    if (!t) return;
    onSend(t);
    setDraft("");
  };

  return (
    <>
      <header className="conv-head">
        <button type="button" className="back" onClick={onBack} aria-label="Back to chats">
          <IconBack />
        </button>
        <div className="av sm" style={{ background: thread.bg, color: thread.fg }} aria-hidden="true">
          {thread.letter}
        </div>
        <div className="who">
          <div className="nm">{thread.name}</div>
          <div className="sub">{thread.typing ? "typing…" : `${thread.sub} · ${clock(now)}`}</div>
        </div>
      </header>
      <div className="feed" ref={feed} aria-live="polite" onScroll={onScroll}>
        <div className="day">Today</div>
        {thread.messages.map((m) => (
          <MessageView key={m.id} m={m} onAction={act} onGo={onGo} />
        ))}
        {thread.typing && (
          <div className="typing-dots" aria-label={`${thread.name} is typing`}>
            <i />
            <i />
            <i />
          </div>
        )}
      </div>
      {unseen && (
        <div className="unseen-wrap">
          <button type="button" className="unseen" onClick={() => toBottom(true)}>
            New messages ↓
          </button>
        </div>
      )}
      <div className="suggest" aria-label="Suggested questions">
        {thread.suggestions.map((q) => (
          <button key={q} type="button" onClick={() => submit(q)}>
            {q}
          </button>
        ))}
      </div>
      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          submit(draft);
        }}
      >
        <label className="sr" htmlFor="composer">
          Message {thread.name}
        </label>
        <input
          id="composer"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={thread.id === "sales" ? "Type an enquiry, e.g. quote 20 MT for a customer…" : "Ask anything about your business…"}
          autoComplete="off"
        />
        <button type="submit" className="send" aria-label="Send" disabled={!draft.trim()}>
          <IconSend color="#3a1a05" />
        </button>
      </form>
    </>
  );
}
