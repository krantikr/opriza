import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, query, useApi } from "../api/client";
import type { Email, Page } from "../api/types";
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

const FOLDERS = [
  { key: "", label: "All mail" },
  { key: "QUOTATION_REQUEST", label: "Enquiries" },
  { key: "GENERAL_INQUIRY", label: "General" },
  { key: "ORDER_CONFIRMATION", label: "Orders" },
  { key: "DELIVERY_QUERY", label: "Delivery" },
  { key: "COMPLAINT", label: "Complaints" },
  { key: "SPAM", label: "Spam" },
];

const CATEGORY_TONE: Record<string, string> = {
  QUOTATION_REQUEST: "border-l-brand",
  ORDER_CONFIRMATION: "border-l-settled",
  COMPLAINT: "border-l-danger",
  DELIVERY_QUERY: "border-l-info",
  SPAM: "border-l-rule-firm",
};

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
  onSelect,
}: {
  email: Email;
  active: boolean;
  onSelect: () => void;
}) {
  const unprocessed = email.processing_status === "PENDING";

  return (
    <button
      type="button"
      onClick={onSelect}
      className={`flex w-full gap-3 border-b border-l-2 border-rule px-3 py-2.5 text-left transition-colors ${
        CATEGORY_TONE[email.category ?? ""] ?? "border-l-transparent"
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
          {email.category && <Badge value={email.category} dot={false} />}
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
          {email.processing_status === "FAILED" && <Badge value="FAILED" />}
        </div>
      </div>
    </button>
  );
}

function Reading({ id, onProcessed }: { id: number; onProcessed: () => void }) {
  const { data, loading, error, reload } = useApi<Email>(`/emails/${id}`);
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
            {data.quotation_id ? (
              <Link to={`/quotations/${data.quotation_id}`}>
                <Button variant="primary" size="sm">
                  Open {data.quotation_number}
                </Button>
              </Link>
            ) : (
              data.processing_status === "PENDING" && (
                <Button size="sm" onClick={reprocess} disabled={busy}>
                  {busy ? "Processing…" : "Process now"}
                </Button>
              )
            )}
          </div>
        </div>

        <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
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
              <Banner tone="danger">{data.error_message}</Banner>
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

        <article className="px-5 py-4">
          <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-ink">
            {data.body_text || "(no body)"}
          </pre>
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
    `/emails${query({ category: folder, search, limit: 100 })}`,
    30_000,
  );

  // Open the newest message by default, so the pane is never blank on arrival.
  useEffect(() => {
    if (selected === null && data?.items.length) setSelected(data.items[0].id);
  }, [data, selected]);

  const counts = (data?.items ?? []).reduce<Record<string, number>>((acc, e) => {
    if (e.category) acc[e.category] = (acc[e.category] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="flex h-[calc(100vh-3rem)] flex-col">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-rule px-5 py-3">
        <div>
          <h1 className="text-lg font-semibold text-ink">Inbox</h1>
          <p className="text-sm text-ink-faint">
            {data ? `${data.total} message${data.total === 1 ? "" : "s"}` : "Loading…"}
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
              <span className="rounded bg-sunk px-1 text-[10px] tabular text-ink-soft">
                {counts[f.key]}
              </span>
            )}
          </button>
        ))}
      </nav>

      {error && <div className="p-4"><ErrorNote message={error} /></div>}

      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[22rem_1fr]">
        <Scroller className="min-h-0 overflow-y-auto border-r border-rule">
          {loading && !data ? (
            <Loading />
          ) : data?.items.length ? (
            data.items.map((email) => (
              <MessageRow
                key={email.id}
                email={email}
                active={selected === email.id}
                onSelect={() => setSelected(email.id)}
              />
            ))
          ) : (
            <Empty message="No mail here." />
          )}
        </Scroller>

        <div className="min-h-0 overflow-hidden bg-surface">
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
