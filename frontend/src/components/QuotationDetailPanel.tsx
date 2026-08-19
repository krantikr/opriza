import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { api, useApi } from "../api/client";
import type { ActionResult, LineItem, QuotationDetail as Detail } from "../api/types";
import PricingCalculator from "./PricingCalculator";
import {
  ago,
  Badge,
  Banner,
  Button,
  Card,
  Empty,
  ErrorNote,
  Field,
  Input,
  inr,
  Loading,
  num,
  Tabs,
  when,
} from "./ui";

/* ---------------------------------------------------------------------------
   One quotation, in four views.

   Tabbed rather than stacked because the four questions are asked at different
   moments: what is this (Overview), is the price right (Pricing Calculator),
   does the reply read well (Response Content), what has happened (Activity).
   Stacking them all would bury the reply under the arithmetic.
   --------------------------------------------------------------------------- */

type TabKey = "overview" | "pricing" | "content" | "activity";

function SendIcon() {
  return (
    <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="M22 2L11 13M22 2l-7 20-4-9-9-4z" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** One message in the thread, inbound or outbound. */
function Message({
  from,
  address,
  at,
  subject,
  body,
  outbound = false,
  label,
  action,
}: {
  from: string;
  address?: string | null;
  at: string | null;
  subject?: string | null;
  body?: string | null;
  outbound?: boolean;
  label?: React.ReactNode;
  action?: React.ReactNode;
}) {
  const [expanded, setExpanded] = useState(false);
  const text = body ?? "";
  const long = text.length > 420;
  const shown = expanded || !long ? text : `${text.slice(0, 420)}…`;

  let hash = 0;
  for (const ch of from) hash = (hash * 31 + ch.charCodeAt(0)) % 360;

  return (
    <article
      className={`overflow-hidden rounded-card border shadow-card ${
        outbound ? "border-brand/25 bg-brand-wash/40" : "border-rule bg-surface"
      }`}
    >
      <header className="flex flex-wrap items-start justify-between gap-2 px-4 py-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <span
            className="grid size-8 shrink-0 place-items-center rounded-full text-[11px] font-semibold text-white"
            style={{ background: outbound ? "var(--color-brand)" : `oklch(0.58 0.1 ${hash})` }}
            aria-hidden="true"
          >
            {from.slice(0, 2).toUpperCase()}
          </span>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[13px] font-semibold text-ink">{from}</span>
              {label}
            </div>
            {address && <p className="truncate text-[11px] text-ink-faint">{address}</p>}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {action}
          <span className="text-[11px] text-ink-faint">{when(at)}</span>
        </div>
      </header>

      <div className="border-t border-rule/70 px-4 py-3">
        {subject && <p className="mb-1.5 text-sm font-medium text-ink">{subject}</p>}
        <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-ink-soft">
          {shown || "(no content)"}
        </pre>
        {long && (
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            className="mt-1.5 text-xs font-medium text-brand hover:underline"
          >
            {expanded ? "Show less" : "Show full message"}
          </button>
        )}
      </div>
    </article>
  );
}

/** The commercial terms a reviewer completes when the enquiry did not state them. */
function EnquiryTerms({
  quotation,
  onSaved,
}: {
  quotation: Detail;
  onSaved: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState({
    delivery_location: quotation.delivery_location ?? "",
    required_delivery_date: quotation.required_delivery_date ?? "",
    payment_terms: quotation.payment_terms ?? "",
  });
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setDraft({
      delivery_location: quotation.delivery_location ?? "",
      required_delivery_date: quotation.required_delivery_date ?? "",
      payment_terms: quotation.payment_terms ?? "",
    });
  }, [quotation.id, quotation.delivery_location, quotation.required_delivery_date, quotation.payment_terms]);

  const missing = [
    !draft.delivery_location && "delivery location",
    !draft.required_delivery_date && "delivery date",
    !draft.payment_terms && "payment terms",
  ].filter(Boolean) as string[];

  const dirty =
    draft.delivery_location !== (quotation.delivery_location ?? "") ||
    draft.required_delivery_date !== (quotation.required_delivery_date ?? "") ||
    draft.payment_terms !== (quotation.payment_terms ?? "");

  async function save() {
    setBusy(true);
    try {
      await api.put(`/quotations/${quotation.id}/details`, draft);
      onSaved();
      setOpen(false);
    } finally {
      setBusy(false);
    }
  }

  const field = (
    key: keyof typeof draft,
    label: string,
    placeholder: string,
  ) => (
    <label className="flex flex-col gap-1">
      <span className="text-[11px] font-medium text-ink-faint">{label}</span>
      {open ? (
        <Input
          value={draft[key]}
          onChange={(v) => setDraft({ ...draft, [key]: v })}
          placeholder={placeholder}
        />
      ) : (
        <span className={`text-sm ${draft[key] ? "text-ink" : "text-ink-faint"}`}>
          {draft[key] || "not stated"}
        </span>
      )}
    </label>
  );

  return (
    <section className="overflow-hidden rounded-card border border-rule bg-surface shadow-card">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-rule px-4 py-2.5">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-ink">Enquiry details</h3>
          {missing.length > 0 && !open && (
            <span className="rounded-full bg-attention-wash px-2 py-0.5 text-[11px] font-medium text-attention-ink">
              {missing.length} to fill in
            </span>
          )}
        </div>
        {open ? (
          <div className="flex items-center gap-2">
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button variant="primary" disabled={!dirty || busy} onClick={save}>
              {busy ? "Saving…" : "Save"}
            </Button>
          </div>
        ) : (
          <Button onClick={() => setOpen(true)}>
            {missing.length > 0 ? "Fill in" : "Edit"}
          </Button>
        )}
      </header>

      <div className="grid gap-3 px-4 py-3 sm:grid-cols-2 lg:grid-cols-3">
        <div className="flex flex-col gap-1">
          <span className="text-[11px] font-medium text-ink-faint">Customer</span>
          <span className="truncate text-sm text-ink">
            {quotation.customer_company || quotation.customer_name || "—"}
          </span>
        </div>
        <div className="flex flex-col gap-1">
          <span className="text-[11px] font-medium text-ink-faint">Email</span>
          <span className="truncate text-sm text-ink">{quotation.customer_email ?? "—"}</span>
        </div>
        {field("delivery_location", "Deliver to", "e.g. Patna")}
        {field("required_delivery_date", "Wanted by", "e.g. within 2 weeks")}
        {field("payment_terms", "Payment terms", "e.g. 30 days from invoice")}
      </div>

      {open && (
        <p className="border-t border-rule px-4 py-2 text-[11px] text-ink-faint">
          Saving re-prices every line — a delivery location brings freight into the build-up.
        </p>
      )}
    </section>
  );
}

/** Everything understood about one requested material. */
function MaterialOverview({ item }: { item: LineItem }) {
  const availability = item.stock_availability;

  return (
    <div className="rounded-card border border-rule bg-surface p-4 shadow-card">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-semibold text-ink">
            {item.matched_stock_item_name ?? item.raw_text ?? `Line ${item.line_no}`}
          </p>
          <p className="mt-0.5 text-xs text-ink-faint">
            {item.quantity ? `${num(item.quantity)} ${item.quantity_unit}` : "quantity not stated"}
            {item.quantity_mt && item.quantity_unit !== "MT" && ` · ${num(item.quantity_mt)} MT`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge value={item.match_status} dot={false} />
          {item.pricing?.quote_rate && (
            <span className="tabular text-sm font-bold text-brand">
              {inr(item.pricing.quote_rate)}/MT
            </span>
          )}
        </div>
      </div>

      <dl className="mt-3 grid gap-x-8 border-t border-rule pt-2 sm:grid-cols-2">
        <Field label="In stock">
          {availability?.available_qty_mt != null
            ? `${num(availability.available_qty_mt)} MT`
            : "—"}
        </Field>
        <Field label="Enough for this order">
          {availability?.sufficient === null || availability?.sufficient === undefined
            ? "not judged"
            : availability.sufficient
              ? "yes"
              : "no"}
        </Field>
        <Field label="Held for">
          {availability?.ageing_min_days == null
            ? "—"
            : availability.ageing_min_days === availability.ageing_max_days
              ? `${availability.ageing_min_days} days`
              : `${availability.ageing_min_days}–${availability.ageing_max_days} days`}
        </Field>
        <Field label="Line total">
          {item.pricing?.line_total ? inr(item.pricing.line_total) : "—"}
        </Field>
      </dl>

      {item.match_status !== "MATCH_FOUND" && item.match_candidates.length > 0 && (
        <div className="mt-3 overflow-hidden rounded-lg border border-attention/30 bg-attention-wash">
          <p className="px-3 py-2 text-xs font-semibold text-attention-ink">
            {item.match_candidates.length} specs fit equally well — a human must choose
          </p>
          <ul className="divide-y divide-attention/20 border-t border-attention/20">
            {item.match_candidates.map((c) => (
              <li key={c.stock_item_id} className="flex justify-between gap-3 px-3 py-1.5 text-xs">
                <span className="min-w-0 truncate text-attention-ink">{c.display_name}</span>
                <span className="tabular shrink-0 text-attention-ink/80">
                  {c.score.toFixed(1)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default function QuotationDetailPanel({
  id,
  onChanged,
  onBack,
}: {
  id: number;
  onChanged: () => void;
  /** Shown on narrow screens, where the detail replaces the list. */
  onBack?: () => void;
}) {
  const { data, error, loading, reload } = useApi<Detail>(`/quotations/${id}`);
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as TabKey) || "overview";
  const setTab = (next: TabKey) =>
    setParams(next === "overview" ? {} : { tab: next }, { replace: true });
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<{ text: string; bad?: boolean } | null>(null);

  const draftId = data?.current_draft?.id;
  useEffect(() => {
    if (data?.current_draft) {
      setSubject(data.current_draft.subject ?? "");
      setBody(data.current_draft.body ?? "");
    }
  }, [draftId]);

  useEffect(() => setNote(null), [id]);

  if (loading && !data) return <Loading label="Loading quotation" />;
  if (error) return <div className="p-5"><ErrorNote message={error} /></div>;
  if (!data) return null;

  const draft = data.current_draft;
  const edited = Boolean(
    draft && (subject !== (draft.subject ?? "") || body !== (draft.body ?? "")),
  );
  const sendable = ["READY_FOR_REVIEW", "EDITED", "NEEDS_INFORMATION"].includes(data.status);
  const stale = data.line_items.some((i) => i.pricing?.draft_stale);
  const totalValue = data.line_items.reduce(
    (sum, i) => sum + Number(i.pricing?.line_total ?? 0),
    0,
  );
  const headline = data.line_items[0];

  async function act(label: string, run: () => Promise<ActionResult>) {
    setBusy(label);
    setNote(null);
    try {
      const result = await run();
      setNote({ text: result.detail, bad: !result.ok });
      reload();
      onChanged();
    } catch (e) {
      setNote({ text: (e as Error).message, bad: true });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col">
      {/* --- Action bar ----------------------------------------------------- */}
      <header className="sticky top-0 z-10 flex flex-col gap-2 border-b border-rule bg-surface px-4 py-2.5 sm:flex-row sm:items-center sm:justify-between sm:px-5 sm:py-3">
        <div className="flex min-w-0 items-center gap-2">
          {onBack && (
            <button
              type="button"
              onClick={onBack}
              aria-label="Back to the list"
              className="-ml-1 rounded-lg p-1 text-ink-faint hover:bg-sunk hover:text-ink xl:hidden"
            >
              <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="1.8">
                <path d="M15 6l-6 6 6 6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </button>
          )}
          <h2 className="truncate text-base font-semibold text-ink">Quotation details</h2>
        </div>
        <div className="flex w-full items-center gap-2 sm:w-auto">
          <Button
            className="flex-1 sm:flex-none"
            disabled={busy !== null}
            onClick={() => act("regen", () => api.post(`/quotations/${data.id}/regenerate`))}
          >
            {busy === "regen" ? "Regenerating…" : "Regenerate"}
          </Button>
          <Button
            variant="danger"
            className="flex-1 sm:flex-none"
            disabled={busy !== null}
            onClick={() => act("reject", () => api.post(`/quotations/${data.id}/reject`, {}))}
          >
            Reject
          </Button>
          <Button
            variant="primary"
            className="flex-1 sm:flex-none"
            disabled={!sendable || busy !== null}
            onClick={() =>
              act("send", () =>
                api.post(`/quotations/${data.id}/approve`, {
                  subject: edited ? subject : undefined,
                  body: edited ? body : undefined,
                }),
              )
            }
          >
            <SendIcon />
            {busy === "send" ? "Sending…" : "Send response"}
          </Button>
        </div>
      </header>

      <div className="flex flex-col gap-4 p-4 sm:p-5">
        {/* --- Identity --------------------------------------------------- */}
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-xl font-bold tracking-tight text-ink sm:text-2xl">
                {data.quotation_number}
              </h3>
              <Badge value={data.status} dot={false} />
              <Badge value={data.confidence} dot={false} />
            </div>
            <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-sm text-ink-soft">
              <span>{headline?.matched_stock_item_name ?? headline?.raw_text ?? "—"}</span>
              <span className="text-ink-faint">|</span>
              <span>{data.customer_company || data.customer_name || "Unknown customer"}</span>
              {headline?.quantity_mt && (
                <>
                  <span className="text-ink-faint">|</span>
                  <span>{num(headline.quantity_mt)} MT</span>
                </>
              )}
            </p>
          </div>

          <div className="text-sm sm:text-right">
            <p className="text-ink-soft">
              Indicative value{" "}
              <span className="tabular ml-1 font-bold text-brand">{inr(totalValue)}</span>
            </p>
            <p className="mt-0.5 text-xs text-ink-faint">Raised {ago(data.created_at)}</p>
          </div>
        </div>

        {note && <Banner tone={note.bad ? "danger" : "settled"}>{note.text}</Banner>}

        {stale && (
          <Banner
            tone="attention"
            action={
              <Button
                disabled={busy !== null}
                onClick={() => act("regen", () => api.post(`/quotations/${data.id}/regenerate`))}
              >
                Regenerate
              </Button>
            }
          >
            A price changed after this draft was written. Regenerate before sending.
          </Banner>
        )}

        {data.send_error && <Banner tone="danger">Send failed: {data.send_error}</Banner>}

        <Tabs<TabKey>
          tabs={[
            { key: "overview", label: "Overview" },
            { key: "pricing", label: "Pricing Calculator" },
            { key: "content", label: "Response Content" },
            { key: "activity", label: "Activity" },
          ]}
          value={tab}
          onChange={setTab}
        />

        {/* --- Overview ---------------------------------------------------- */}
        {tab === "overview" && (
          <div className="flex flex-col gap-4">
            {/* Commercial terms first: these are the fields a reviewer fills
                in or corrects, and they gate everything downstream. */}
            <EnquiryTerms quotation={data} onSaved={() => { reload(); onChanged(); }} />

            {/* Then the conversation, in the order it happened. */}
            <div className="flex flex-col gap-2">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-faint">
                Conversation
              </p>

              {data.email && (
                <Message
                  from={data.email.sender_name || data.email.sender_email || "Customer"}
                  address={data.email.sender_email}
                  at={data.email.received_at}
                  subject={data.email.subject}
                  body={data.email.body_text}
                  label={data.email.category ? <Badge value={data.email.category} dot={false} /> : null}
                />
              )}

              {data.replies?.map((r) => (
                <Message
                  key={r.id}
                  from={r.sender_name || r.sender_email || "Customer"}
                  address={r.sender_email}
                  at={r.received_at}
                  body={r.body_text}
                  label={r.reply_intent ? <Badge value={r.reply_intent} dot={false} /> : null}
                />
              ))}

              {data.follow_ups?.map((f) => (
                <Message
                  key={`f-${f.id}`}
                  from="You"
                  at={f.created_at}
                  subject={f.subject}
                  body={f.body}
                  outbound
                  label={<Badge value={f.sent ? "SENT" : "FAILED"} dot={false} />}
                />
              ))}

              {/* The reply being composed sits at the end of the thread, where
                  the next message in a mail client would be. */}
              {draft && (
                <Message
                  from="You"
                  at={data.sent_at}
                  subject={subject}
                  body={body}
                  outbound
                  label={
                    <Badge value={data.sent_at ? "SENT" : `DRAFT V${draft.version}`} dot={false} />
                  }
                  action={
                    !data.sent_at && (
                      <Button onClick={() => setTab("content")}>
                        Edit reply
                      </Button>
                    )
                  }
                />
              )}
            </div>

            {(data.review_notes || data.missing_information.length > 0) && (
              <Banner tone="attention">
                {data.missing_information.length > 0 && (
                  <p>
                    <span className="font-semibold">Missing from the enquiry: </span>
                    {data.missing_information.join(" · ")}
                  </p>
                )}
                {data.review_notes && (
                  <pre className="mt-1 whitespace-pre-wrap font-sans text-xs leading-relaxed">
                    {data.review_notes}
                  </pre>
                )}
              </Banner>
            )}

            <div className="flex flex-col gap-2">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-faint">
                Materials
              </p>
              {data.line_items.map((item) => (
                <MaterialOverview key={item.id} item={item} />
              ))}
            </div>
          </div>
        )}

        {/* --- Pricing ------------------------------------------------------ */}
        {tab === "pricing" && (
          <div className="flex flex-col gap-4">
            {data.line_items.map((item) => (
              <div key={item.id} className="flex flex-col gap-2">
                {data.line_items.length > 1 && (
                  <p className="text-sm font-semibold text-ink">
                    Line {item.line_no} ·{" "}
                    {item.matched_stock_item_name ?? item.raw_text ?? "Material"}
                  </p>
                )}
                {item.pricing ? (
                  <PricingCalculator
                    pricing={item.pricing}
                    quotationId={data.id}
                    lineId={item.id}
                    onChange={() => {
                      reload();
                      onChanged();
                    }}
                  />
                ) : (
                  <Banner tone="attention">
                    This line has not been priced — no landed cost on the matched stock and no
                    current mill offer covers it.
                  </Banner>
                )}
              </div>
            ))}
            <p className="text-xs text-ink-faint">
              Any change here updates the quoted price in the list, and marks the drafted reply
              for regeneration so it can never go out with a superseded figure.
            </p>
          </div>
        )}

        {/* --- Response content --------------------------------------------- */}
        {tab === "content" && (
          <>
            {draft ? (
              <Card
                padded={false}
                title={`Draft v${draft.version}`}
                subtitle={draft.generated_by ?? undefined}
                action={
                  <span className="text-xs text-ink-faint">
                    {edited ? "Unsaved edits" : "No changes"}
                  </span>
                }
              >
                <label className="flex items-center gap-2 border-b border-rule px-4 py-2.5">
                  <span className="w-16 shrink-0 text-xs font-medium text-ink-faint">Subject</span>
                  <input
                    value={subject}
                    onChange={(e) => setSubject(e.target.value)}
                    className="min-w-0 flex-1 bg-transparent text-sm text-ink outline-none"
                  />
                </label>
                <textarea
                  value={body}
                  onChange={(e) => setBody(e.target.value)}
                  rows={24}
                  spellCheck
                  className="w-full resize-y bg-transparent px-4 py-3 font-sans text-sm leading-relaxed text-ink outline-none"
                />
                <div className="flex justify-end gap-2 border-t border-rule bg-sunk px-4 py-2.5">
                  <Button
                    disabled={!edited || busy !== null}
                    onClick={() =>
                      act("save", () =>
                        api.put(`/quotations/${data.id}/draft`, { subject, body }),
                      )
                    }
                  >
                    Save edits
                  </Button>
                </div>
              </Card>
            ) : (
              <Card>
                <Empty message="No draft was generated. Resolve the notes on Overview, then regenerate." />
              </Card>
            )}
          </>
        )}

        {/* --- Activity ------------------------------------------------------ */}
        {tab === "activity" && (
          <Card padded={false}>
            <ol className="flex flex-col">
              {[
                { at: data.created_at, title: "Enquiry received and processed", tone: "bg-brand" },
                ...(data.approvals ?? []).map((a) => ({
                  at: a.acted_at ?? data.created_at,
                  title: `${a.action.toLowerCase()}${a.was_edited ? " (edited first)" : ""}`,
                  tone: "bg-settled",
                })),
                ...(data.sent_at
                  ? [{ at: data.sent_at, title: "Quotation sent", tone: "bg-settled" }]
                  : []),
                ...(data.follow_ups ?? []).map((f) => ({
                  at: f.created_at,
                  title: f.sent ? "Follow-up sent" : "Follow-up failed",
                  tone: f.sent ? "bg-info" : "bg-danger",
                })),
                ...(data.replies ?? []).map((r) => ({
                  at: r.received_at ?? data.created_at,
                  title: `Customer replied${r.reply_intent ? ` — ${r.reply_intent.toLowerCase()}` : ""}`,
                  tone: "bg-info",
                })),
              ]
                .sort((a, b) => new Date(a.at).getTime() - new Date(b.at).getTime())
                .map((entry, i, list) => (
                  <li key={`${entry.at}-${i}`} className="flex gap-3 px-4">
                    <div className="flex flex-col items-center">
                      <span className={`mt-3.5 size-2 shrink-0 rounded-full ${entry.tone}`} />
                      {i < list.length - 1 && <span className="w-px flex-1 bg-rule" />}
                    </div>
                    <div className="flex flex-1 items-baseline justify-between gap-2 py-3">
                      <span className="text-sm capitalize text-ink">{entry.title}</span>
                      <span className="shrink-0 text-[11px] text-ink-faint">{when(entry.at)}</span>
                    </div>
                  </li>
                ))}
            </ol>
          </Card>
        )}
      </div>
    </div>
  );
}
