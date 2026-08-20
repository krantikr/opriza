import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, query, useApi } from "../api/client";
import type { Email, Page } from "../api/types";
import ThreadView, { type Thread } from "../components/Thread";
import {
  ago,
  Badge,
  Banner,
  Button,
  Empty,
  ErrorNote,
  Input,
  Loading,
  Scroller,
  until,
  when,
} from "../components/ui";

/* ---------------------------------------------------------------------------
   The mailbox.

   A two-pane mail client, because that is the shape everyone already knows:
   a scannable list on the left, the full message on the right. What the
   system worked out about each mail - what it classified it as, why, and what
   it became - is shown alongside the message rather than in a separate screen,
   so "why did it do that?" is answered where the question occurs.
   --------------------------------------------------------------------------- */

/**
 * Folders, in the order a desk works them.
 *
 * A folder holds one or more *categories* rather than a single one, because
 * the taxonomy the classifier uses is finer than the way a trader thinks:
 * PRICE_NEGOTIATION and PAYMENT_QUERY both belong with the commercial
 * conversation, and GENERAL / SPAM / OTHER are all "not work" - keeping them
 * apart just makes three near-empty tabs.
 *
 * `pending` is not a category at all: it is every enquiry that became a
 * quotation still waiting on a person. It sits with the categories because
 * that is where someone looks for it.
 */
/**
 * The mailbox is a queue of work, not a filing cabinet.
 *
 * Every message resolves to exactly one *pending state* on the backend
 * (`services/pipeline_state.py`), and leaves it the moment somebody acts. So a
 * tab's number is a true count of outstanding work, and all tabs empty means
 * the desk is clear - something a category scheme can never tell you.
 *
 * "All mail" is the only non-pending tab: the archive and the search surface,
 * where anything already handled still lives.
 */
const FOLDERS: { key: string; label: string; state?: string; hint: string }[] = [
  { key: "", label: "All mail", hint: "Everything, including what is already handled" },
  {
    key: "enquiries",
    label: "Enquiries",
    state: "ENQUIRY",
    hint: "Asked for a price. No quotation has gone out yet.",
  },
  {
    key: "follow-up",
    label: "Follow up",
    state: "FOLLOW_UP",
    hint: "Quotation sent, no reply yet. A rule says when to chase.",
  },
  {
    key: "needs-reply",
    label: "Needs reply",
    state: "NEEDS_REPLY",
    hint: "They asked something. Nobody has answered.",
  },
  {
    key: "delivery",
    label: "Delivery",
    state: "DELIVERY",
    hint: "Order confirmed. Waiting for the goods to go out.",
  },
  {
    key: "complaints",
    label: "Complaints",
    state: "COMPLAINT",
    hint: "Something went wrong and nobody has answered.",
  },
];



/** The stripe down a message's left edge, so a folder reads at a glance. */
const CATEGORY_TONE: Record<string, string> = {
  QUOTATION_REQUEST: "border-l-brand",
  ORDER: "border-l-settled",
  COMPLAINT: "border-l-danger",
  DELIVERY_QUERY: "border-l-info",
  PRICE_NEGOTIATION: "border-l-info",
  PAYMENT_QUERY: "border-l-info",
  SPAM: "border-l-rule-firm",
  GENERAL: "border-l-rule-firm",
};

/**
 * A sentence a trader can act on, from a stack trace they cannot.
 *
 * The raw text is kept behind a disclosure - it matters when reporting a
 * problem - but leading with it means the actual message ("the enquiry is
 * still here, press try again") is buried in provider JSON.
 */
function summariseError(raw: string): string {
  const text = raw.toLowerCase();
  if (text.includes("429") || text.includes("rate-limit") || text.includes("rate limit")) {
    return "The AI provider was busy and refused the request. Nothing is lost — try again.";
  }
  if (text.includes("not a valid model")) {
    return "The configured AI model does not exist. Check LLM_MODEL_* in your settings.";
  }
  if (text.includes("401") || text.includes("api key") || text.includes("unauthorized")) {
    return "The AI provider rejected the API key. Check OPENROUTER_API_KEY.";
  }
  if (text.includes("timeout") || text.includes("timed out")) {
    return "The AI provider took too long to answer. Try again.";
  }
  if (text.includes("extraction failed")) {
    return "The enquiry could not be read well enough to quote. It needs a person.";
  }
  return "This message could not be processed automatically. It needs a person.";
}

/** Colour-blocked initials, so a sender is recognisable before it is read. */
function Avatar({ name, email }: { name: string | null; email: string | null }) {
  const source = name || email || "?";
  const initials = source
    .replace(/@.*/, "")
    .split(/[\s._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join("");

  // Stable hue per sender: the same person is always the same colour.
  let hash = 0;
  for (const ch of source) hash = (hash * 31 + ch.charCodeAt(0)) % 360;

  return (
    <span
      className="grid size-8 shrink-0 place-items-center rounded-full text-[11px] font-semibold text-white"
      style={{ background: `oklch(0.58 0.11 ${hash})` }}
      aria-hidden="true"
    >
      {initials || "?"}
    </span>
  );
}

function MessageRow({
  email,
  active,
  showStatus = false,
  onSelect,
}: {
  email: Email;
  active: boolean;
  /** In the pending folder, the quotation's state is the reason it is listed. */
  showStatus?: boolean;
  onSelect: () => void;
}) {
  const unprocessed = email.processing_status === "PENDING";

  return (
    <button
      type="button"
      onClick={onSelect}
      className={`flex w-full gap-3 border-b border-l-2 border-rule px-3 py-2.5 text-left transition-colors ${
        email.processing_status === "FAILED"
          ? "border-l-danger"
          : (CATEGORY_TONE[email.category ?? ""] ?? "border-l-transparent")
      } ${active ? "bg-brand-wash" : "hover:bg-sunk"}`}
    >
      <Avatar name={email.sender_name} email={email.sender_email} />

      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <span
            className={`truncate text-[13px] ${unprocessed ? "font-semibold text-ink" : "font-medium text-ink"}`}
          >
            {email.sender_name || email.sender_email || "Unknown sender"}
          </span>
          <span className="shrink-0 text-[11px] text-ink-faint">{ago(email.received_at)}</span>
        </div>

        <p className="truncate text-[13px] text-ink-soft">{email.subject || "(no subject)"}</p>
        <p className="truncate text-xs text-ink-faint">{email.snippet}</p>

        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          {showStatus && email.quotation_status ? (
            <Badge value={email.quotation_status} dot={false} />
          ) : (
            email.category && <Badge value={email.category} dot={false} />
          )}
          {showStatus && email.follow_up_due && (
            <span className="rounded-full bg-attention-wash px-1.5 py-0.5 text-[10px] font-medium text-attention-ink">
              chase now
            </span>
          )}
          {showStatus && !email.follow_up_due && email.follow_up_at && (
            <span className="rounded-full bg-sunk px-1.5 py-0.5 text-[10px] font-medium text-ink-soft">
              chase {until(email.follow_up_at)}
            </span>
          )}
          {showStatus && email.promised_date_raw && (
            <span className="rounded-full bg-info-wash px-1.5 py-0.5 text-[10px] font-medium text-info-ink">
              said {email.promised_date_raw}
            </span>
          )}
          {email.quotation_number && (
            <span className="rounded bg-sunk px-1.5 py-0.5 text-[10px] font-medium text-ink-soft">
              {email.quotation_number}
            </span>
          )}
          {email.has_attachments && (
            <svg viewBox="0 0 24 24" className="size-3 text-ink-faint" fill="none" stroke="currentColor" strokeWidth="1.8">
              <path d="M21 12.5L12.5 21a5 5 0 0 1-7-7l8.5-8.5a3.5 3.5 0 0 1 5 5L10.5 19a2 2 0 0 1-3-3L15 8.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          )}
          {email.processing_status === "FAILED" && (
            <span className="rounded-full bg-danger-wash px-2 py-0.5 text-[11px] font-medium text-danger-ink">
              could not be read
            </span>
          )}
        </div>
      </div>
    </button>
  );
}

function Reading({ id, onProcessed }: { id: number; onProcessed: () => void }) {
  const { data, loading, error, reload } = useApi<Email>(`/emails/${id}`);

  // The conversation this message belongs to. Fetched separately so the
  // message itself still appears promptly if the thread is slow.
  const [thread, setThread] = useState<Thread | null>(null);
  useEffect(() => {
    let current = true;
    setThread(null);
    api
      .get<Thread>(`/emails/${id}/thread`)
      .then((t) => current && setThread(t))
      .catch(() => current && setThread(null));
    return () => {
      current = false;
    };
  }, [id, data?.state]);
  const [busy, setBusy] = useState(false);

  if (loading && !data) return <Loading label="Opening" />;
  if (error) return <div className="p-4"><ErrorNote message={error} /></div>;
  if (!data) return null;

  async function reprocess() {
    setBusy(true);
    try {
      await api.post("/pipeline/process");
      setTimeout(() => {
        reload();
        onProcessed();
      }, 2000);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-rule px-5 py-3.5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-ink">
              {data.subject || "(no subject)"}
            </h2>
            <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-faint">
              <span className="font-medium text-ink-soft">
                {data.sender_name || "Unknown"}
              </span>
              <span>&lt;{data.sender_email}&gt;</span>
              <span>·</span>
              <span>{when(data.received_at)}</span>
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            {data.state === "DELIVERY" && data.quotation_id && (
              <Button
                compact
                variant="primary"
                onClick={async () => {
                  await api.post(`/quotations/${data.quotation_id}/despatched`);
                  reload();
                  onProcessed();
                }}
              >
                Mark despatched
              </Button>
            )}
            {data.awaiting_us && !data.answered_at && (
              <Button
                compact
                onClick={async () => {
                  await api.post(`/emails/${data.id}/answered`);
                  reload();
                  onProcessed();
                }}
              >
                Mark answered
              </Button>
            )}
            {data.quotation_id ? (
              <Link to={`/quotations/${data.quotation_id}`}>
                <Button variant="primary">
                  Open {data.quotation_number}
                </Button>
              </Link>
            ) : (
              data.processing_status === "PENDING" && (
                <Button onClick={reprocess} disabled={busy}>
                  {busy ? "Processing…" : "Process now"}
                </Button>
              )
            )}
          </div>
        </div>

        <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
          {data.state !== "DONE" && <Badge value={data.state} dot={false} />}
          {data.promised_date_raw && (
            <span className="rounded-full bg-info-wash px-2 py-0.5 text-[11px] font-medium text-info-ink">
              customer said: {data.promised_date_raw}
            </span>
          )}
          {data.category && <Badge value={data.category} />}
          <Badge value={data.processing_status} />
          {data.reply_intent && <Badge value={data.reply_intent} />}
          {data.processing_ms != null && (
            <span className="text-[11px] text-ink-faint">
              handled in {(data.processing_ms / 1000).toFixed(1)}s
            </span>
          )}
        </div>
      </header>

      <div className="flex-1 overflow-y-auto">
        {/* What the system concluded, and why - beside the mail, not elsewhere. */}
        {(data.classification_reason || data.error_message) && (
          <div className="border-b border-rule px-5 py-3">
            {data.error_message ? (
              <Banner
                tone="danger"
                action={
                  <Button
                    compact
                    onClick={async () => {
                      await api.post("/pipeline/process");
                      setTimeout(() => {
                        reload();
                        onProcessed();
                      }, 2500);
                    }}
                  >
                    Try again
                  </Button>
                }
              >
                <p className="font-medium">{summariseError(data.error_message)}</p>
                <details className="mt-1">
                  <summary className="cursor-pointer text-xs opacity-80">
                    Technical detail
                  </summary>
                  <pre className="mt-1 whitespace-pre-wrap text-[11px] leading-snug opacity-80">
                    {data.error_message}
                  </pre>
                </details>
              </Banner>
            ) : (
              <div className="rounded-lg border border-rule bg-sunk px-3 py-2">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-faint">
                  Why it was filed here
                </p>
                <p className="mt-0.5 text-sm text-ink-soft">{data.classification_reason}</p>
                {data.classification_confidence != null && (
                  <p className="mt-1 text-[11px] text-ink-faint">
                    Confidence {(data.classification_confidence * 100).toFixed(0)}%
                  </p>
                )}
              </div>
            )}
          </div>
        )}

        {/* The conversation, not the single message.

            A reply shown detached from what it answers is the thing this
            replaces: a trader had to hold the other half in their head, or
            open Gmail to see it. Falls back to the plain body while the
            thread loads, and for a message that genuinely stands alone. */}
        <article className="px-5 py-4">
          {thread && thread.messages.length > 1 ? (
            <ThreadView thread={thread} />
          ) : (
            <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-ink">
              {data.body_text || "(no body)"}
            </pre>
          )}
        </article>

        {data.attachments && data.attachments.length > 0 && (
          <section className="border-t border-rule px-5 py-3">
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-ink-faint">
              {data.attachments.length} attachment{data.attachments.length === 1 ? "" : "s"}
            </p>
            <div className="flex flex-col gap-1.5">
              {data.attachments.map((a) => (
                <div
                  key={a.id}
                  className="flex items-center gap-2 rounded-lg border border-rule px-2.5 py-1.5 text-sm"
                >
                  <svg viewBox="0 0 24 24" className="size-4 shrink-0 text-ink-faint" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <path d="M6 2h8l5 5v15H6z" strokeLinejoin="round" />
                    <path d="M14 2v5h5" strokeLinejoin="round" />
                  </svg>
                  <span className="min-w-0 flex-1 truncate text-ink">{a.filename}</span>
                  {a.extraction_error ? (
                    <span className="shrink-0 text-[11px] text-attention">
                      {a.extraction_error}
                    </span>
                  ) : (
                    <span className="shrink-0 text-[11px] text-ink-faint">
                      {a.has_text ? "text extracted" : "no text"}
                    </span>
                  )}
                </div>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

export default function Inbox() {
  const [folder, setFolder] = useState("");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<number | null>(null);

  const { data, error, loading, reload } = useApi<Page<Email>>(
    `/emails${query({ search, limit: 200 })}`,
    30_000,
  );

  const all = data?.items ?? [];

  /** One state per message, decided by the backend so the tabs agree with it. */
  const inFolder = (email: Email, f: (typeof FOLDERS)[number]) =>
    !f.state || email.state === f.state;

  const active = FOLDERS.find((f) => f.key === folder) ?? FOLDERS[0];
  const rows = all.filter((e) => inFolder(e, active));

  // Open the newest message by default, so the pane is never blank on arrival.
  useEffect(() => {
    if (rows.length === 0) return;
    if (selected === null || !rows.some((e) => e.id === selected)) {
      setSelected(rows[0].id);
    }
  }, [rows, selected]);

  const counts = Object.fromEntries(
    FOLDERS.map((f) => [f.key, all.filter((e) => inFolder(e, f)).length]),
  );

  return (
    <div className="flex h-[calc(100vh-7rem)] flex-col md:h-[calc(100vh-3.25rem)]">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-rule px-5 py-3">
        <div>
          <h1 className="text-lg font-semibold text-ink">Inbox</h1>
          <p className="text-sm text-ink-faint">
            {data
              ? `${rows.length} message${rows.length === 1 ? "" : "s"}${
                  active.key ? ` in ${active.label.toLowerCase()}` : ""
                }`
              : "Loading…"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Input
            value={search}
            onChange={setSearch}
            placeholder="Search sender or subject"
            className="w-56"
          />
          <Button onClick={reload}>Refresh</Button>
        </div>
      </header>

      <nav className="flex gap-1 overflow-x-auto border-b border-rule px-4 py-1.5">
        {FOLDERS.map((f) => (
          <button
            key={f.key}
            type="button"
            title={f.hint}
            onClick={() => {
              setFolder(f.key);
              setSelected(null);
            }}
            className={`flex shrink-0 items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium transition-colors ${
              folder === f.key
                ? "bg-brand-wash text-brand-soft-ink"
                : "text-ink-faint hover:bg-sunk hover:text-ink"
            }`}
          >
            {f.label}
            {f.key && counts[f.key] > 0 && (
              <span
                className={`tabular rounded px-1 text-[10px] ${
                  f.state
                    ? "bg-attention text-white"
                    : folder === f.key
                      ? "bg-brand-wash text-brand-soft-ink"
                      : "bg-sunk text-ink-soft"
                }`}
              >
                {counts[f.key]}
              </span>
            )}
          </button>
        ))}
      </nav>

      {error && <div className="p-4"><ErrorNote message={error} /></div>}

      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[22rem_1fr]">
        <Scroller
          className={`min-h-0 overflow-y-auto border-r border-rule ${
            selected ? "hidden lg:block" : "block"
          }`}
        >
          {loading && !data ? (
            <Loading />
          ) : rows.length ? (
            rows.map((email) => (
              <MessageRow
                key={email.id}
                email={email}
                active={selected === email.id}
                showStatus={active.key === "follow-up" || active.key === "delivery"}
                onSelect={() => setSelected(email.id)}
              />
            ))
          ) : (
            <Empty
              message={
                active.state
                  ? `Nothing pending here. ${active.hint}`
                  : "No mail matches."
              }
            />
          )}
        </Scroller>

        <div
          className={`min-h-0 overflow-hidden bg-surface ${
            selected ? "block" : "hidden lg:block"
          }`}
        >
          {selected ? (
            <Reading id={selected} onProcessed={reload} />
          ) : (
            <Empty message="Select a message to read it." />
          )}
        </div>
      </div>
    </div>
  );
}
