import { useEffect, useMemo, useState } from "react";

import { api } from "../api/client";
import Conversation from "../demo/components/Conversation";
import type { Action, Go, Thread as DemoThread, ThreadId } from "../demo/engine/types";
import { IClose } from "../demo/desk/icons";
import { Avatar } from "../demo/desk/ui";
import type { Page } from "./ctx";
import { useData, useVersion, type ChatMsg, type Thread } from "./data";

/** Questions the chat suggests, from the screen you're on. */
export function suggestions(page: Page | null, thread: string): string[] {
  if (thread !== "ask") {
    return {
      collect: ["Who owes me the most?", "Promises due this week", "How much is overdue?"],
      sales: ["Which quotes are still open?", "Who stopped buying?", "Top customers"],
      stock: ["What will run out this week?", "Show idle stock", "What do I pay suppliers this week?"],
      cash: ["Cash position", "What do I pay suppliers this week?", "Promises due this week"],
      score: ["How many customers are grade D?", "Who stopped buying?", "Who owes me the most?"],
      brief: ["What needs me today?", "Sales last month", "Cash position"],
    }[thread] ?? [];
  }
  switch (page) {
    case "collect":
      return ["Who owes me the most?", "Promises due this week", "How many customers are grade D?"];
    case "sales":
      return ["Which quotes are still open?", "Sales this month", "Who stopped buying?"];
    case "stock":
      return ["What will run out this week?", "Show idle stock", "What do I pay suppliers this week?"];
    case "cash":
      return ["Cash position", "What do I pay suppliers this week?", "Promises due this week"];
    case "customers":
      return ["Top customers", "Who stopped buying?", "How many customers are grade D?"];
    default:
      return ["What needs me today?", "Sales last month", "Who owes me the most?"];
  }
}

/** Minutes past midnight in IST, which is what chat messages are stamped with. */
function minutes(iso?: string | null): number {
  const [h, m] = new Date(iso ?? Date.now()).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Kolkata" }).split(":").map(Number);
  return (h ?? 0) * 60 + (m ?? 0);
}

export const ORDER = ["ask", "brief", "sales", "collect", "stock", "cash", "score"];

type Props = {
  thread: string;
  setThread: (t: string) => void;
  page: Page | null;
  onClose: () => void;
  /** A button that moves the app ("Open Approvals", "Open customer"). */
  onNavigate: (action: Action) => void;
  onGo: (go: Go) => void;
  toast: (t: string) => void;
  /** Phone layout: no agent tabs, a back arrow instead. */
  compact?: boolean;
  pendingQuestion?: string | null;
  clearPending?: () => void;
  /** The business's clock (held still on a sample desk). */
  clockNow?: string | null;
};

export default function ChatPanel({ thread, setThread, page, onClose, onNavigate, onGo, toast, compact, pendingQuestion, clearPending, clockNow }: Props) {
  const { bump } = useVersion();
  const threads = useData<Thread[]>("/app/chat", 15000);
  const msgs = useData<{ messages: ChatMsg[] }>(`/app/chat/${thread}`, 12000);
  const [typing, setTyping] = useState(false);
  const [local, setLocal] = useState<ChatMsg[]>([]);

  useEffect(() => setLocal([]), [thread, msgs.data]);

  const info = threads.data?.find((t) => t.id === thread);
  const view: DemoThread | null = useMemo(() => {
    if (!info) return null;
    return {
      id: thread as ThreadId, name: info.name, sub: info.sub, letter: info.letter, bg: info.bg, fg: info.fg,
      messages: [...(msgs.data?.messages ?? []), ...local], unread: 0, typing,
      suggestions: suggestions(page, thread),
    } as DemoThread;
  }, [info, msgs.data, local, typing, page, thread]);

  const send = async (text: string) => {
    const now = new Date();
    setLocal((l) => [...l, { id: `local-${Date.now()}`, from: "me", at: minutes(clockNow), text, ts: now.toISOString(), ref: null } as ChatMsg]);
    setTyping(true);
    try {
      await api.post(`/app/chat/${thread}`, { text });
      msgs.reload();
      bump();
    } catch (e) {
      toast((e as Error).message);
    } finally {
      setTyping(false);
    }
  };

  // A question handed over from elsewhere (search bar, a screen's "Ask" link).
  useEffect(() => {
    if (pendingQuestion && info) {
      void send(pendingQuestion);
      clearPending?.();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingQuestion, info]);

  const onAction = async (m: { id: string }, a: Action) => {
    if (a.id.startsWith("go-") || a.id.startsWith("view-")) {
      onNavigate(a);
      return;
    }
    try {
      const r = await api.post<{ resumed?: boolean; status?: string }>(`/app/chat/messages/${m.id}/action`, { action_id: a.id });
      if (a.id === "approve") toast(r.resumed ? "Approved. The agent has gone ahead." : "Approved.");
      if (a.id === "reject") toast("Okay, held back.");
      msgs.reload();
      bump();
    } catch (e) {
      toast((e as Error).message);
    }
  };

  return (
    <>
      {!compact && (
        <div className="dk-chat-h">
          <div className="dk-chat-agents" role="tablist" aria-label="Agents">
            {ORDER.map((id) => {
              const t = threads.data?.find((x) => x.id === id);
              if (!t) return null;
              return (
                <button key={id} type="button" role="tab" aria-selected={thread === id} title={t.name} onClick={() => setThread(id)}>
                  <Avatar t={t} size={30} />
                  {t.unread > 0 && thread !== id && <i className="dot" aria-label="unread" />}
                </button>
              );
            })}
          </div>
          <button type="button" className="dk-x" aria-label="Close chat" onClick={onClose}>
            <IClose />
          </button>
        </div>
      )}
      <div className="dk-chat-b">
        {view ? (
          <Conversation key={thread} thread={view} now={minutes(clockNow)} onBack={onClose}
            onAction={onAction} onSend={(t) => void send(t)} onGo={onGo} />
        ) : (
          <div className="dk-empty"><b>Loading the chat…</b></div>
        )}
      </div>
    </>
  );
}
