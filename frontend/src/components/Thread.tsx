/* ---------------------------------------------------------------------------
   The conversation with a customer.

   Read like a mail thread, because that is what it is: they asked, we quoted,
   they replied, we chased. Direction is carried by alignment and colour so
   the shape of a conversation is readable before any word of it — a column
   of inbound messages with no reply is visibly a problem.

   Every message also says what it *caused* ("Quotation sent", "Customer
   accepted"), so the state shown at the top is traceable to the message that
   produced it rather than being an assertion the trader has to trust.
   --------------------------------------------------------------------------- */

import { useState } from "react";

import { ago, when } from "./ui";

export interface ThreadMessage {
  id: string;
  direction: "INBOUND" | "OUTBOUND";
  kind: "ENQUIRY" | "QUOTATION" | "REPLY" | "FOLLOW_UP";
  at: string | null;
  sender_name: string | null;
  sender_email: string | null;
  subject: string | null;
  body: string | null;
  sent: boolean;
  outcome: string | null;
  email_id: number | null;
  has_attachments: boolean;
}

export interface Thread {
  quotation_id: number;
  quotation_number: string;
  state: string;
  status: string;
  customer_name: string | null;
  customer_email: string | null;
  messages: ThreadMessage[];
}

/** What each stage means, in the words the Inbox tabs use. Kept identical so
 *  a trader never has to learn two vocabularies for one pipeline. */
const STATE_LABEL: Record<string, { label: string; hint: string; tone: string }> = {
  ENQUIRY: {
    label: "Enquiry",
    hint: "No quotation has gone out yet.",
    tone: "bg-brand-wash text-brand",
  },
  FOLLOW_UP: {
    label: "Follow up",
    hint: "Quoted, waiting on the customer.",
    tone: "bg-attention-wash text-attention-ink",
  },
  NEEDS_REPLY: {
    label: "Needs reply",
    hint: "They asked something and nobody has answered.",
    tone: "bg-attention-wash text-attention-ink",
  },
  DELIVERY: {
    label: "Delivery",
    hint: "Order confirmed, waiting for despatch.",
    tone: "bg-good-wash text-good-ink",
  },
  COMPLAINT: {
    label: "Complaint",
    hint: "Something went wrong and nobody has answered.",
    tone: "bg-danger-wash text-danger-ink",
  },
  DONE: {
    label: "Nothing outstanding",
    hint: "Nobody is waiting on anybody.",
    tone: "bg-sunk text-ink-soft",
  },
};

const KIND_LABEL: Record<ThreadMessage["kind"], string> = {
  ENQUIRY: "Enquiry",
  QUOTATION: "Quotation sent",
  REPLY: "Customer replied",
  FOLLOW_UP: "Follow-up",
};

/** Long quoted bodies collapse: the newest exchange is what matters, and a
 *  wall of quoted history buries it. */
const LONG = 900;

function Message({ message }: { message: ThreadMessage }) {
  const inbound = message.direction === "INBOUND";
  const body = message.body ?? "";
  const [expanded, setExpanded] = useState(body.length <= LONG);
  const shown = expanded ? body : `${body.slice(0, LONG)}…`;

  return (
    <li className={`flex ${inbound ? "justify-start" : "justify-end"}`}>
      <div className={`w-full max-w-2xl ${inbound ? "" : "flex flex-col items-end"}`}>
        <div className="mb-1 flex flex-wrap items-baseline gap-x-2 gap-y-0.5 px-0.5">
          <span className="text-[13px] font-medium text-ink">
            {inbound ? (message.sender_name ?? message.sender_email ?? "Customer") : "You"}
          </span>
          <span className="text-[11px] text-ink-faint">{KIND_LABEL[message.kind]}</span>
          <span className="text-[11px] text-ink-faint" title={when(message.at)}>
            {ago(message.at)}
          </span>
        </div>

        <div
          className={`w-full rounded-xl border px-3.5 py-3 ${
            inbound
              ? "border-rule bg-surface"
              : message.sent
                ? "border-brand-soft/40 bg-brand-wash"
                : // Drafted but never sent - must not read as delivered.
                  "border-dashed border-rule bg-sunk"
          }`}
        >
          {message.subject && (
            <p className="mb-1.5 text-[13px] font-semibold text-ink">{message.subject}</p>
          )}
          <p className="whitespace-pre-wrap break-words text-[13px] leading-relaxed text-ink-soft">
            {shown || <span className="italic text-ink-faint">No message body.</span>}
          </p>

          {body.length > LONG && (
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="mt-1.5 text-xs font-medium text-brand hover:underline"
            >
              {expanded ? "Show less" : "Show the whole message"}
            </button>
          )}

          {(message.outcome || message.has_attachments || !message.sent) && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5 border-t border-rule pt-2">
              {!message.sent && (
                <span className="rounded-full bg-attention-wash px-2 py-0.5 text-[11px] font-medium text-attention-ink">
                  not sent
                </span>
              )}
              {message.outcome && (
                <span className="text-[11px] text-ink-faint">{message.outcome}</span>
              )}
              {message.has_attachments && (
                <span className="text-[11px] text-ink-faint">· has attachments</span>
              )}
            </div>
          )}
        </div>
      </div>
    </li>
  );
}

export default function ThreadView({ thread }: { thread: Thread }) {
  const state = STATE_LABEL[thread.state] ?? STATE_LABEL.DONE;

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-2 border-b border-rule pb-3">
        <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${state.tone}`}>
          {state.label}
        </span>
        <span className="text-xs text-ink-faint">{state.hint}</span>
        <span className="ml-auto text-xs text-ink-faint">
          {thread.messages.length}{" "}
          {thread.messages.length === 1 ? "message" : "messages"}
        </span>
      </div>

      {thread.messages.length === 0 ? (
        <p className="py-6 text-center text-sm text-ink-soft">
          Nothing has been exchanged yet.
        </p>
      ) : (
        <ul className="flex flex-col gap-4">
          {thread.messages.map((message) => (
            <Message key={message.id} message={message} />
          ))}
        </ul>
      )}
    </div>
  );
}
