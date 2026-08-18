import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, useApi } from "../api/client";
import type { ActionResult, LineItem, QuotationDetail as Detail } from "../api/types";
import {
  Badge,
  Button,
  Card,
  ErrorNote,
  Field,
  Loading,
  inr,
  num,
  when,
} from "../components/ui";

/** The availability derivation, step by step. Spec section 22 in one component. */
function StockAvailabilityPanel({ item }: { item: LineItem }) {
  const availability = item.stock_availability;
  if (!availability) return <p className="text-sm text-ink-500">Not checked.</p>;

  if (availability.available_qty_mt === null) {
    return (
      <div className="space-y-2">
        <p className="text-sm text-ink-700">Availability could not be checked for this line.</p>
        <pre className="whitespace-pre-wrap rounded-lg bg-ink-50 p-3 text-xs text-ink-700">
          {availability.explanation}
        </pre>
      </div>
    );
  }

  const inStock = Number(availability.available_qty_mt) > 0;
  const tone =
    availability.sufficient === false
      ? "bg-amber-50 ring-amber-200 text-amber-900"
      : inStock
        ? "bg-emerald-50 ring-emerald-200 text-emerald-900"
        : "bg-rose-50 ring-rose-200 text-rose-900";

  return (
    <div className="space-y-3">
      <div className={`flex items-baseline justify-between rounded-lg px-3 py-2 ring-1 ring-inset ${tone}`}>
        <span className="text-sm font-medium">
          {inStock ? "Available" : "Not currently in stock"}
        </span>
        <span className="tabular text-lg font-semibold">
          {num(availability.available_qty_mt)}
          <span className="ml-1 text-xs font-normal">MT</span>
        </span>
      </div>

      <dl className="grid grid-cols-2 gap-x-6">
        <Field label="Suggested rate">
          {availability.suggested_rate ? `${inr(availability.suggested_rate)} (indicative)` : "—"}
        </Field>
        <Field label="Sufficient?">
          {availability.sufficient === null ? "unknown" : availability.sufficient ? "yes" : "no"}
        </Field>
        <Field label="Lots">{availability.lot_count}</Field>
        <Field label="Ageing">
          {availability.ageing_min_days === null
            ? "—"
            : availability.ageing_min_days === availability.ageing_max_days
              ? `${availability.ageing_min_days}d`
              : `${availability.ageing_min_days}-${availability.ageing_max_days}d`}
        </Field>
        <Field label="Stock as of">{availability.stock_as_of ?? "—"}</Field>
        <Field label="Rules version">{availability.rules_version ?? "—"}</Field>
      </dl>

      {availability.locations.length > 0 && (
        <div className="rounded-lg bg-ink-50 p-2 text-xs text-ink-700">
          {availability.locations
            .map((loc) => `${loc.location ?? "unspecified"}: ${loc.balance_qty_mt.toFixed(3)} MT`)
            .join(" · ")}
        </div>
      )}

      <details className="rounded-lg border border-ink-200">
        <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-ink-700">
          How this was determined ({availability.breakdown.length} steps)
        </summary>
        <ol className="divide-y divide-ink-100 border-t border-ink-200">
          {availability.breakdown.map((step, index) => (
            <li key={index} className={`px-3 py-2 text-sm ${step.applied ? "" : "opacity-60"}`}>
              <span className="font-medium text-ink-900">{step.label}</span>
              <p className="mt-0.5 text-xs text-ink-700">{step.reason}</p>
            </li>
          ))}
        </ol>
      </details>
    </div>
  );
}

function LineItemCard({ item }: { item: LineItem }) {
  return (
    <div className="space-y-3 rounded-lg border border-ink-200 p-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-ink-900">
            {item.matched_stock_item_name ?? item.raw_text ?? `Line ${item.line_no}`}
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          <Badge value={item.match_status} />
          {item.match_score !== null && (
            <span className="tabular text-xs text-ink-500">{item.match_score.toFixed(0)}%</span>
          )}
        </div>
      </div>

      {item.raw_text && (
        <blockquote className="border-l-2 border-ink-200 pl-2 text-xs italic text-ink-500">
          “{item.raw_text}”
        </blockquote>
      )}

      <dl className="grid grid-cols-2 gap-x-6">
        <Field label="Quantity">
          {item.quantity ? `${num(item.quantity)} ${item.quantity_unit}` : "not stated"}
        </Field>
        <Field label="Tonnage">{item.quantity_mt ? `${num(item.quantity_mt)} MT` : "—"}</Field>
      </dl>

      {item.conversion_basis && item.quantity_unit !== "MT" && (
        <p className="rounded bg-ink-50 px-2 py-1 text-xs text-ink-500">
          Converted: {item.conversion_basis}
        </p>
      )}

      {item.match_status !== "MATCH_FOUND" && item.match_candidates.length > 0 && (
        <details className="rounded-lg border border-amber-200 bg-amber-50">
          <summary className="cursor-pointer px-3 py-2 text-sm font-medium text-amber-900">
            {item.match_candidates.length} candidate stock specs — a human must choose
          </summary>
          <ul className="divide-y divide-amber-200 border-t border-amber-200">
            {item.match_candidates.map((candidate) => (
              <li
                key={candidate.stock_item_id}
                className="flex justify-between px-3 py-1.5 text-xs"
              >
                <span className="text-amber-900">
                  {candidate.display_name}
                  {candidate.lot_count > 1 && (
                    <span className="text-amber-700"> ({candidate.lot_count} lots)</span>
                  )}
                </span>
                <span className="tabular shrink-0 pl-3 text-amber-700">
                  {candidate.score.toFixed(1)}
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}

      <StockAvailabilityPanel item={item} />
    </div>
  );
}

export default function QuotationDetail() {
  const { id } = useParams();
  const { data, error, loading, reload } = useApi<Detail>(`/quotations/${id}`);

  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [note, setNote] = useState<{ text: string; bad?: boolean } | null>(null);

  useEffect(() => {
    if (data?.current_draft) {
      setSubject(data.current_draft.subject ?? "");
      setBody(data.current_draft.body ?? "");
    }
  }, [data?.current_draft?.id, data?.current_draft?.version]);

  if (loading && !data) return <Loading label="Loading quotation" />;
  if (error) return <div className="p-6"><ErrorNote message={error} /></div>;
  if (!data) return null;

  const draft = data.current_draft;
  const closed = ["SENT", "REJECTED", "APPROVED", "CUSTOMER_ACCEPTED"].includes(data.status);
  const dirty =
    draft && (subject !== (draft.subject ?? "") || body !== (draft.body ?? ""));

  async function act(label: string, run: () => Promise<ActionResult>) {
    setBusy(label);
    setNote(null);
    try {
      const result = await run();
      setNote({ text: result.detail, bad: !result.ok });
      reload();
    } catch (err) {
      setNote({ text: (err as Error).message, bad: true });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="space-y-4 p-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link to="/quotations" className="text-xs text-ink-500 hover:underline">
            ← All quotations
          </Link>
          <h1 className="mt-1 flex items-center gap-2 text-xl font-semibold text-ink-900">
            {data.quotation_number}
            <Badge value={data.status} />
            <Badge value={data.confidence} />
          </h1>
          <p className="text-sm text-ink-500">
            {data.customer_company || data.customer_name || "Unknown customer"} ·{" "}
            {data.customer_email} · {data.delivery_location ?? "no delivery location"}
          </p>
        </div>
        <Button onClick={reload}>Refresh</Button>
      </header>

      {note && (
        <div
          className={`rounded-lg px-4 py-3 text-sm ${
            note.bad
              ? "border border-rose-200 bg-rose-50 text-rose-800"
              : "border border-emerald-200 bg-emerald-50 text-emerald-800"
          }`}
        >
          {note.text}
        </div>
      )}

      {data.status === "CUSTOMER_ACCEPTED" && (
        <div className="rounded-lg border border-emerald-300 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
          <p className="font-medium">Customer wants to proceed — close this deal</p>
          <p className="mt-1">
            They replied to say yes. Time to follow through outside this tool: purchase order,
            invoice, dispatch.
          </p>
        </div>
      )}

      {data.status === "CUSTOMER_DECLINED" && (
        <div className="rounded-lg border border-ink-300 bg-ink-50 px-4 py-3 text-sm text-ink-800">
          <p className="font-medium">Customer declined for now</p>
          <p className="mt-1">
            A polite courtesy reply has been drafted below, keeping the door open for next time.
            Review and send it, or edit it first.
          </p>
        </div>
      )}

      {data.missing_information.length > 0 && (
        <div className="rounded-lg border border-orange-200 bg-orange-50 px-4 py-3 text-sm text-orange-900">
          <p className="font-medium">The enquiry is missing information</p>
          <ul className="mt-1 list-inside list-disc">
            {data.missing_information.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </div>
      )}

      {data.review_notes && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <p className="font-medium">Why this needs a human</p>
          <pre className="mt-1 whitespace-pre-wrap font-sans">{data.review_notes}</pre>
        </div>
      )}

      {data.send_error && (
        <ErrorNote message={`Approved, but sending failed: ${data.send_error}`} />
      )}

      <div className="grid gap-4 xl:grid-cols-3">
        {/* Column 1: what the customer actually sent */}
        <Card title="Customer enquiry">
          {data.email ? (
            <div className="space-y-3">
              <dl>
                <Field label="From">{data.email.sender_name ?? data.email.sender_email}</Field>
                <Field label="Received">{when(data.email.received_at)}</Field>
                <Field label="Classified">
                  <span className="inline-flex items-center gap-1.5">
                    <Badge value={data.email.category} />
                    {data.email.classification_confidence !== null && (
                      <span className="tabular text-xs text-ink-500">
                        {(data.email.classification_confidence * 100).toFixed(0)}%
                      </span>
                    )}
                  </span>
                </Field>
              </dl>
              {data.email.classification_reason && (
                <p className="text-xs italic text-ink-500">{data.email.classification_reason}</p>
              )}
              <p className="text-sm font-medium text-ink-900">{data.email.subject}</p>
              <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded-lg bg-ink-50 p-3 text-xs text-ink-700">
                {data.email.body_text}
              </pre>
              {data.email.attachments && data.email.attachments.length > 0 && (
                <ul className="space-y-1 text-xs text-ink-500">
                  {data.email.attachments.map((file) => (
                    <li key={file.id}>
                      📎 {file.filename}
                      {file.extraction_error && (
                        <span className="text-amber-600"> — {file.extraction_error}</span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : (
            <p className="text-sm text-ink-500">Original email unavailable.</p>
          )}

          {data.replies.length > 0 && (
            <div className="mt-4 space-y-3 border-t border-ink-200 pt-3">
              <p className="text-xs font-medium uppercase tracking-wide text-ink-500">
                Customer replies
              </p>
              {data.replies.map((reply) => (
                <div key={reply.id} className="space-y-1.5 rounded-lg bg-ink-50 p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="inline-flex items-center gap-1.5">
                      {reply.reply_intent && <Badge value={reply.reply_intent} />}
                      {reply.reply_intent_confidence !== null && (
                        <span className="tabular text-xs text-ink-500">
                          {((reply.reply_intent_confidence ?? 0) * 100).toFixed(0)}%
                        </span>
                      )}
                    </span>
                    <span className="text-xs text-ink-500">{when(reply.received_at)}</span>
                  </div>
                  {reply.reply_intent_reason && (
                    <p className="text-xs italic text-ink-500">{reply.reply_intent_reason}</p>
                  )}
                  <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded bg-white p-2 text-xs text-ink-700">
                    {reply.body_text}
                  </pre>
                </div>
              ))}
            </div>
          )}
        </Card>

        {/* Column 2: what the system understood, and what it found in stock */}
        <Card title={`Understanding & stock (${data.line_items.length} line${data.line_items.length === 1 ? "" : "s"})`}>
          <div className="space-y-3">
            {data.line_items.map((item) => (
              <LineItemCard key={item.id} item={item} />
            ))}
            {data.additional_requirements.length > 0 && (
              <div className="rounded-lg bg-ink-50 p-3 text-xs">
                <p className="font-medium text-ink-700">Customer also asked for</p>
                <ul className="mt-1 list-inside list-disc text-ink-700">
                  {data.additional_requirements.map((requirement, index) => (
                    <li key={index}>{requirement}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </Card>

        {/* Column 3: the reply, and the decision */}
        <Card
          title="Draft reply"
          action={
            draft && (
              <span className="text-xs text-ink-500">
                v{draft.version} · {draft.generated_by}
              </span>
            )
          }
        >
          {!draft ? (
            <div className="space-y-3">
              <p className="text-sm text-ink-700">
                No draft was generated, because no line could be matched against stock. Resolve
                the issues above, then generate a draft.
              </p>
              <Button
                onClick={() =>
                  act("regenerate", () => api.post<ActionResult>(`/quotations/${id}/regenerate`))
                }
                disabled={busy !== null}
              >
                {busy === "regenerate" ? "Generating…" : "Generate draft"}
              </Button>
            </div>
          ) : (
            <div className="space-y-3">
              <input
                value={subject}
                onChange={(event) => setSubject(event.target.value)}
                disabled={closed}
                className="w-full rounded-lg border border-ink-300 px-3 py-2 text-sm font-medium disabled:bg-ink-50"
              />
              <textarea
                value={body}
                onChange={(event) => setBody(event.target.value)}
                disabled={closed}
                rows={18}
                className="w-full rounded-lg border border-ink-300 px-3 py-2 font-mono text-xs leading-relaxed disabled:bg-ink-50"
              />

              {closed ? (
                <div className="space-y-2">
                  <p className="text-sm text-ink-500">
                    This quotation is {data.status.toLowerCase().replace(/_/g, " ")}
                    {data.sent_at && ` — sent ${when(data.sent_at)}`}.
                  </p>
                  {data.status === "SENT" && (
                    <Button
                      disabled={busy !== null}
                      onClick={() =>
                        act("follow-up", () =>
                          api.post<ActionResult>(`/quotations/${id}/follow-up`),
                        )
                      }
                    >
                      {busy === "follow-up" ? "Sending…" : "Send follow-up"}
                    </Button>
                  )}
                </div>
              ) : (
                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="primary"
                    disabled={busy !== null}
                    onClick={() =>
                      act("approve", () =>
                        api.post<ActionResult>(`/quotations/${id}/approve`, { subject, body }),
                      )
                    }
                  >
                    {busy === "approve" ? "Sending…" : "Approve & send"}
                  </Button>
                  <Button
                    disabled={busy !== null || !dirty}
                    onClick={() =>
                      act("save", () =>
                        api.put<ActionResult>(`/quotations/${id}/draft`, { subject, body }),
                      )
                    }
                  >
                    {busy === "save" ? "Saving…" : dirty ? "Save edits" : "Saved"}
                  </Button>
                  <Button
                    disabled={busy !== null}
                    onClick={() =>
                      act("regenerate", () =>
                        api.post<ActionResult>(`/quotations/${id}/regenerate`),
                      )
                    }
                  >
                    {busy === "regenerate" ? "Regenerating…" : "Regenerate"}
                  </Button>
                  <Button
                    variant="danger"
                    disabled={busy !== null}
                    onClick={() => {
                      const reason = window.prompt("Reason for rejecting?") ?? undefined;
                      act("reject", () =>
                        api.post<ActionResult>(`/quotations/${id}/reject`, { reason }),
                      );
                    }}
                  >
                    Reject
                  </Button>
                </div>
              )}

              <p className="text-xs text-ink-500">
                Nothing is sent until you press Approve &amp; send. The availability and suggested
                rate above come from the stock list, not the model — the rate is indicative and
                yours to override.
              </p>
            </div>
          )}

          {data.approvals.length > 0 && (
            <div className="mt-4 border-t border-ink-200 pt-3">
              <p className="text-xs font-medium uppercase tracking-wide text-ink-500">
                Decision history
              </p>
              <ul className="mt-1.5 space-y-1 text-xs text-ink-700">
                {data.approvals.map((approval) => (
                  <li key={approval.id} className="flex justify-between gap-3">
                    <span>
                      {approval.action}
                      {approval.was_edited && " (edited)"}
                      {approval.user_name && ` · ${approval.user_name}`}
                      {approval.comments && ` — ${approval.comments}`}
                    </span>
                    <span className="shrink-0 text-ink-500">{when(approval.acted_at)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {data.follow_ups.length > 0 && (
            <div className="mt-4 border-t border-ink-200 pt-3">
              <p className="text-xs font-medium uppercase tracking-wide text-ink-500">
                Follow-ups
              </p>
              <ul className="mt-1.5 space-y-1 text-xs text-ink-700">
                {data.follow_ups.map((followUp) => (
                  <li key={followUp.id} className="flex justify-between gap-3">
                    <span>
                      {followUp.sent ? "Sent" : "Failed"}
                      {followUp.user_name && ` · ${followUp.user_name}`}
                      {followUp.error && ` — ${followUp.error}`}
                    </span>
                    <span className="shrink-0 text-ink-500">{when(followUp.created_at)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
