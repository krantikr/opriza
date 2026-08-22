import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { api, useApi } from "../api/client";
import type {
  ActionResult,
  LineItem,
  PastOrders,
  QuotationDetail as Detail,
} from "../api/types";
import PricingCalculator from "./PricingCalculator";
import ThreadView, { type Thread } from "./Thread";
import {
  ago,
  Badge,
  Banner,
  Button,
  Card,
  Empty,
  ErrorNote,
  Input,
  inr,
  inrShort,
  Loading,
  num,
  Scroller,
  StatCard,
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

type TabKey = "overview" | "content" | "pricing" | "past" | "activity";

function SendIcon() {
  return (
    <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="1.8">
      <path d="M22 2L11 13M22 2l-7 20-4-9-9-4z" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

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

  /* Only the terms that were actually agreed. The rest are named once by the
     "N to fill in" chip rather than three times as empty cells. */
  const known: [string, string][] = [
    draft.delivery_location ? ["Deliver to", draft.delivery_location] : null,
    draft.required_delivery_date ? ["Wanted by", draft.required_delivery_date] : null,
    draft.payment_terms ? ["Payment", draft.payment_terms] : null,
  ].filter(Boolean) as [string, string][];

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
    // A strip inside the summary card, not a card of its own: the two
    // together described one quotation and repeated its customer.
    <section className="mt-3 border-t border-rule pt-3">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <h3 className="text-[10.5px] font-semibold uppercase tracking-wider text-ink-faint">
            Terms
          </h3>
          {missing.length > 0 && !open && (
            <span className="rounded-full bg-attention-wash px-2 py-0.5 text-[10.5px] font-medium text-attention-ink">
              {missing.length} to fill in
            </span>
          )}
        </div>
        {open ? (
          <div className="flex items-center gap-2">
            <Button compact variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button compact variant="primary" disabled={!dirty || busy} onClick={save}>
              {busy ? "Saving…" : "Save"}
            </Button>
          </div>
        ) : (
          <Button compact variant="ghost" onClick={() => setOpen(true)}>
            {missing.length > 0 ? "Fill in" : "Edit"}
          </Button>
        )}
      </header>

      {/* Customer and email are deliberately absent: the summary card above
          already names the buyer, and repeating it made the two cards read as
          two different subjects. This card is only the terms a reviewer fills
          in or corrects. */}
      {/* Three cells reading "not stated" is an empty grid pretending to be
          data. Until a reviewer opens the editor, only what is known shows. */}
      {open ? (
        <div className="mt-2 grid gap-3 sm:grid-cols-3">
          {field("delivery_location", "Deliver to", "e.g. Patna")}
          {field("required_delivery_date", "Wanted by", "e.g. within 2 weeks")}
          {field("payment_terms", "Payment terms", "e.g. 30 days from invoice")}
        </div>
      ) : (
        known.length > 0 && (
          <dl className="mt-1.5 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs">
            {known.map(([label, value]) => (
              <div key={label} className="flex items-center gap-1.5">
                <dt className="text-ink-faint">{label}</dt>
                <dd className="font-medium text-ink">{value}</dd>
              </div>
            ))}
          </dl>
        )
      )}

      {open && (
        <p className="mt-2 text-[11px] text-ink-faint">
          Saving re-prices every line — a delivery location brings freight into the build-up.
        </p>
      )}
    </section>
  );
}

/** A line as a trader says it: "8 × 1250 × 5800 mm C-45 Plate".
 *
 *  Built from the *parsed* specification rather than the sentence it came
 *  from. `raw_text` is whatever the customer typed - often a whole paragraph -
 *  and putting that where the material belongs buries the one thing the card
 *  exists to state. The matched lot's name wins when there is one, because
 *  that is the desk's own vocabulary for the same steel. */
function specOf(item: LineItem | undefined): string {
  if (!item) return "Material not stated";
  if (item.matched_stock_item_name) return item.matched_stock_item_name;

  const dims = [item.thickness_mm, item.width_mm, item.length_mm].filter(Boolean);
  const parts = [
    dims.length >= 2 ? `${dims.join(" × ")} mm` : null,
    item.product_type,
    item.grade && item.grade !== item.product_type ? item.grade : null,
  ].filter(Boolean);

  // Fall back to the customer's own words only when nothing was extracted -
  // a long sentence still beats an empty card.
  return parts.length > 0 ? parts.join(" ") : (item.raw_text?.slice(0, 90) ?? "Material not stated");
}

/** What this customer has bought and been quoted before.
 *
 *  Fetched only when the tab is opened - it is two extra queries, and most
 *  visits to a quotation never ask the question.
 *
 *  Note on scope: the desk has no proforma invoice anywhere in the system
 *  (no model, no field, no generation), so this shows what genuinely exists -
 *  billed sales from `sales_invoices` and earlier quotations. */
function PastOrdersTab({ quotationId }: { quotationId: number }) {
  const { data, error, loading } = useApi<PastOrders>(
    `/quotations/${quotationId}/past-orders`,
  );

  if (loading && !data) return <Loading label="Looking up their history" />;
  if (error) return <ErrorNote message={error} />;
  if (!data) return null;

  const nothing = data.invoices.length === 0 && data.quotations.length === 0;
  const delta = data.rate_delta === null ? null : Number(data.rate_delta);

  return (
    <div className="flex flex-col gap-4">
      {/* The comparison, first and largest: the reason to open this tab is to
          check today's rate against what they have actually paid. */}
      {data.avg_rate_same_material !== null && (
        <Card>
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <p className="text-[10.5px] font-semibold uppercase tracking-wider text-ink-faint">
                They usually pay
              </p>
              <p className="tabular text-xl font-bold text-ink">
                {inr(data.avg_rate_same_material)}
                <span className="ml-1 text-xs font-medium text-ink-faint">/MT</span>
              </p>
            </div>
            <div>
              <p className="text-[10.5px] font-semibold uppercase tracking-wider text-ink-faint">
                You are quoting
              </p>
              <p className="tabular text-xl font-bold text-brand">
                {inr(data.current_rate)}
                <span className="ml-1 text-xs font-medium text-ink-faint">/MT</span>
              </p>
            </div>
            {delta !== null && (
              <div
                className={`rounded-lg px-3 py-1.5 text-sm font-semibold ${
                  delta > 0
                    ? "bg-attention-wash text-attention-ink"
                    : delta < 0
                      ? "bg-settled-wash text-settled-ink"
                      : "bg-sunk text-ink-soft"
                }`}
              >
                {delta > 0 ? "▲" : delta < 0 ? "▼" : "="} {inr(Math.abs(delta))}
                <span className="ml-1 text-xs font-normal">
                  {delta > 0 ? "above" : delta < 0 ? "below" : "same as"} their average
                </span>
              </div>
            )}
          </div>
          <p className="mt-2 border-t border-rule pt-2 text-xs text-ink-faint">
            Averaged over past invoices for this same specification only.
          </p>
        </Card>
      )}

      {nothing ? (
        <Card>
          <Empty message="No earlier invoices or quotations for this customer. Nothing to compare today's rate against." />
        </Card>
      ) : (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <StatCard label="Past orders" value={data.orders_count} />
          <StatCard label="Total billed" value={inrShort(data.total_value)} tone="settled" />
          <StatCard
            label="Quoted before"
            value={`${data.quotes_won}/${data.quotes_count}`}
            tone={data.quotes_count > 0 && data.quotes_won === 0 ? "attention" : "info"}
          />
          <StatCard
            label="Last order"
            value={data.last_order_at ? when(data.last_order_at).split(",")[0] : "—"}
          />
        </div>
      )}

      {data.invoices.length > 0 && (
        <Card title="Invoiced sales" subtitle="What they have actually paid" padded={false}>
          <Scroller>
            <table className="w-full min-w-[38rem] border-collapse text-sm">
              <thead>
                <tr className="border-b border-rule">
                  {["Invoice", "Date", "Material", "Qty (MT)", "Rate/MT", "Value"].map(
                    (h, i) => (
                      <th
                        key={h}
                        className={`whitespace-nowrap px-3 py-2 text-[10.5px] font-semibold uppercase tracking-wider text-ink-faint ${
                          i >= 3 ? "text-right" : "text-left"
                        }`}
                      >
                        {h}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {data.invoices.map((row, i) => (
                  <tr
                    key={`${row.invoice_no}-${i}`}
                    className="border-b border-rule last:border-0"
                  >
                    <td className="whitespace-nowrap px-3 py-2 text-ink">
                      {row.invoice_no ?? "—"}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-ink-soft">
                      {row.invoice_date ? when(row.invoice_date).split(",")[0] : "—"}
                    </td>
                    <td className="px-3 py-2">
                      <span className="text-ink">{row.material}</span>
                      {/* Marked because these are the only rows that anchor a
                          price; the rest are relationship context. */}
                      {row.same_material && (
                        <span className="ml-1.5 rounded-full bg-brand-wash px-1.5 py-0.5 text-[10px] font-medium text-brand-ink">
                          same spec
                        </span>
                      )}
                    </td>
                    <td className="tabular whitespace-nowrap px-3 py-2 text-right text-ink-soft">
                      {row.quantity_mt ? num(row.quantity_mt) : "—"}
                    </td>
                    <td className="tabular whitespace-nowrap px-3 py-2 text-right font-medium text-ink">
                      {row.rate_per_mt ? inr(row.rate_per_mt) : "—"}
                    </td>
                    <td className="tabular whitespace-nowrap px-3 py-2 text-right text-ink-soft">
                      {row.line_total ? inrShort(row.line_total) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Scroller>
        </Card>
      )}

      {data.quotations.length > 0 && (
        <Card
          title="Earlier quotations"
          subtitle="Whether this buyer converts, or shops around"
          padded={false}
        >
          <Scroller>
            <table className="w-full min-w-[38rem] border-collapse text-sm">
              <thead>
                <tr className="border-b border-rule">
                  {["Quotation", "Raised", "Material", "Rate/MT", "Value", "Outcome"].map(
                    (h, i) => (
                      <th
                        key={h}
                        className={`whitespace-nowrap px-3 py-2 text-[10.5px] font-semibold uppercase tracking-wider text-ink-faint ${
                          i === 3 || i === 4 ? "text-right" : "text-left"
                        }`}
                      >
                        {h}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody>
                {data.quotations.map((row) => (
                  <tr key={row.id} className="border-b border-rule last:border-0">
                    <td className="whitespace-nowrap px-3 py-2 font-medium text-ink">
                      {row.quotation_number}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-ink-soft">
                      {ago(row.created_at)}
                    </td>
                    <td className="px-3 py-2">
                      <span className="text-ink">{row.material}</span>
                      {row.same_material && (
                        <span className="ml-1.5 rounded-full bg-brand-wash px-1.5 py-0.5 text-[10px] font-medium text-brand-ink">
                          same spec
                        </span>
                      )}
                    </td>
                    <td className="tabular whitespace-nowrap px-3 py-2 text-right text-ink">
                      {row.rate_per_mt ? inr(row.rate_per_mt) : "—"}
                    </td>
                    <td className="tabular whitespace-nowrap px-3 py-2 text-right text-ink-soft">
                      {row.value ? inrShort(row.value) : "—"}
                    </td>
                    <td className="px-3 py-2">
                      <Badge value={row.status} dot={false} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Scroller>
        </Card>
      )}
    </div>
  );
}

export default function QuotationDetailPanel({
  id,
  onChanged,
  onBack,
  asDrawer = false,
}: {
  id: number;
  onChanged: () => void;
  /** Shown on narrow screens, where the detail replaces the list. */
  onBack?: () => void;
  /** Rendered inside a slide-over rather than a side-by-side pane. The
   *  dismiss control then has to be visible at every width - `xl:hidden`
   *  would leave a desktop drawer with no way out but the scrim. */
  asDrawer?: boolean;
}) {
  const { data, error, loading, reload } = useApi<Detail>(`/quotations/${id}`);
  // The conversation, from the endpoint that assembles it. Fetched separately
  // so a slow thread never delays the pricing and line items a trader is
  // usually here for.
  const [thread, setThread] = useState<Thread | null>(null);
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

  // Reloaded whenever the quotation changes underneath - sending, approving
  // or recording a reply all add a message, and a stale thread would show a
  // conversation that is one step behind what the trader just did.
  useEffect(() => {
    let current = true;
    setThread(null);
    api
      .get<Thread>(`/quotations/${id}/thread`)
      .then((t) => current && setThread(t))
      .catch(() => current && setThread(null));
    return () => {
      current = false;
    };
  }, [id, data?.status, data?.sent_at]);

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

  /* Status as colour, matching the stripe on the list and the chase board so
     one glance carries across all three screens. */
  const statusStripe =
    (
      {
        CUSTOMER_ACCEPTED: "bg-settled",
      SENT: "bg-brand-soft",
      APPROVED: "bg-brand-soft",
      READY_FOR_REVIEW: "bg-attention",
      NEEDS_INFORMATION: "bg-attention",
      EDITED: "bg-info",
        FAILED: "bg-danger",
      } as Record<string, string>
    )[data.status] ?? "bg-rule-firm";

  /* What is actually stopping a price, in the order a trader would clear it.
     Derived from the current record rather than from `review_notes`, which is
     a snapshot taken at processing time and goes stale the moment somebody
     publishes rules or receives stock. */
  const blockers = [
    data.line_items.some((i) => i.match_status === "NO_MATCH")
      ? "no matching stock"
      : null,
    data.line_items.some((i) => i.match_status === "MULTIPLE_MATCHES")
      ? "more than one spec fits — pick one"
      : null,
    !data.delivery_location ? "add a delivery location for freight" : null,
  ].filter(Boolean) as string[];

  /* Stock figures worth printing. A cell reading "—" tells a trader nothing
     he did not already know from "no matching stock" above. */
  const availability = headline?.stock_availability;
  const stockFacts: [string, string][] = [];
  if (availability?.available_qty_mt != null) {
    stockFacts.push(["In stock", `${num(availability.available_qty_mt)} MT`]);
  }
  if (availability?.sufficient != null) {
    stockFacts.push(["Covers this order", availability.sufficient ? "yes" : "no"]);
  }
  if (availability?.ageing_min_days != null) {
    stockFacts.push([
      "Ageing",
      availability.ageing_min_days === availability.ageing_max_days
        ? `${availability.ageing_min_days} days`
        : `${availability.ageing_min_days}–${availability.ageing_max_days} days`,
    ]);
  }

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
          {/* A back arrow only where the detail replaced the list. In a drawer
              the dismiss control lives on the right with the other actions,
              matching the chase drawer - a lone ✕ stranded at the far left of
              a wide panel reads as belonging to nothing. */}
          {onBack && !asDrawer && (
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
          {onBack && asDrawer && (
            <button
              type="button"
              onClick={onBack}
              aria-label="Close"
              className="ml-1 shrink-0 rounded-lg p-1.5 text-ink-faint hover:bg-sunk hover:text-ink"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <path d="M18 6 6 18M6 6l12 12" />
              </svg>
            </button>
          )}
        </div>
      </header>

      <div className="flex flex-col gap-4 p-4 sm:p-5">
        {/* --- Summary -----------------------------------------------------
            One card, built on one rule: show what is known, say plainly what
            is blocking, and render nothing for what is simply absent.

            Before this, six cells read "not stated / — / not judged / No
            Match / ₹0.00". A trader scanning that learns nothing except that
            the screen is full of holes, and the two facts that *do* matter -
            what was asked for, and what is stopping a price - are buried
            among them. ------------------------------------------------- */}
        <section className="relative overflow-hidden rounded-card border border-rule bg-surface shadow-card">
          {/* A status stripe, matching the chase board and the list. State
              reads before any word does, and it ties the three screens
              together. */}
          <span
            className={`absolute inset-y-0 left-0 w-1 ${statusStripe}`}
            aria-hidden
          />

          <div className="p-4 pl-5">
            <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-2">
              <div className="min-w-0 flex-1">
                {/* The material leads. It is what the quotation is *about*;
                    the reference number identifies it to the system and can
                    sit quietly above. */}
                <p className="flex flex-wrap items-center gap-2 text-[11px] text-ink-faint">
                  <span className="font-semibold tracking-wide text-ink-soft">
                    {data.quotation_number}
                  </span>
                  <Badge value={data.status} dot={false} />
                </p>
                <h3 className="mt-1 text-[17px] font-semibold leading-snug tracking-tight text-ink">
                  {specOf(headline)}
                </h3>
                <p className="mt-1 flex flex-wrap items-center gap-x-1.5 text-xs text-ink-soft">
                  <span className="font-medium text-ink">
                    {data.customer_company || data.customer_name || "Unknown customer"}
                  </span>
                  {headline?.quantity_mt && (
                    <>
                      <span className="text-ink-faint">·</span>
                      <span className="tabular">{num(headline.quantity_mt)} MT</span>
                    </>
                  )}
                  {data.line_count > 1 && (
                    <>
                      <span className="text-ink-faint">·</span>
                      <span>{data.line_count} lines</span>
                    </>
                  )}
                  <span className="text-ink-faint">·</span>
                  <span className="text-ink-faint">
                    {data.sent_at ? "sent " : "raised "}
                    {ago(data.sent_at ?? data.created_at)}
                  </span>
                </p>
              </div>

              {/* A price only earns the largest type on the card once there is
                  one. Zero in bold blue reads as a real quote of nothing. */}
              {totalValue && Number(totalValue) > 0 ? (
                <div className="shrink-0 text-right">
                  <p className="text-[10px] font-semibold uppercase tracking-wider text-ink-faint">
                    Indicative value
                  </p>
                  <p className="tabular text-[22px] font-bold leading-tight tracking-tight text-brand">
                    {inr(totalValue)}
                  </p>
                  {headline?.pricing?.quote_rate && (
                    <p className="tabular text-[11px] text-ink-faint">
                      {inr(headline.pricing.quote_rate)}/MT
                    </p>
                  )}
                </div>
              ) : (
                <span className="shrink-0 rounded-full border border-rule bg-sunk px-2.5 py-1 text-[11px] font-medium text-ink-soft">
                  Not priced yet
                </span>
              )}
            </div>

            {/* One line naming what is actually in the way, in the order a
                trader would resolve it. Silent when nothing is blocking. */}
            {blockers.length > 0 && (
              <div className="mt-3 flex items-start gap-2 rounded-lg border border-attention/25 bg-attention-wash px-3 py-2 text-[13px] text-attention-ink">
                <svg
                  viewBox="0 0 24 24"
                  className="mt-0.5 size-3.5 shrink-0"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.2"
                  strokeLinecap="round"
                >
                  <path d="M12 8v5M12 16.5v.01" />
                  <circle cx="12" cy="12" r="9" strokeWidth="1.6" />
                </svg>
                <p>
                  <span className="font-semibold">To price this: </span>
                  {blockers.join(" · ")}
                </p>
              </div>
            )}

          {/* Stock, only where there is stock to report. "In stock —, held
              for —, enough? not judged" is four cells saying nothing. */}
            {stockFacts.length > 0 && (
              <dl className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1.5 border-t border-rule pt-3 text-xs">
                {stockFacts.map(([label, value]) => (
                  <div key={label} className="flex items-center gap-1.5">
                    <dt className="text-ink-faint">{label}</dt>
                    <dd className="tabular font-medium text-ink">{value}</dd>
                  </div>
                ))}
              </dl>
            )}

            {/* Terms: a compact line when known, expanded into fields only
                when a reviewer chooses to fill them in. */}
            <EnquiryTerms quotation={data} onSaved={() => { reload(); onChanged(); }} />
          </div>
        </section>

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
            { key: "content", label: "Response Content" },
            { key: "pricing", label: "Pricing Calculator" },
            { key: "past", label: "Past orders" },
            { key: "activity", label: "Activity" },
          ]}
          value={tab}
          onChange={setTab}
        />

        {/* --- Overview ---------------------------------------------------- */}
        {tab === "overview" && (
          <div className="flex flex-col gap-4">
            {/* Then the conversation, in the order it happened.

                Assembled by the backend rather than stitched together here:
                a customer who replies directly to our mail creates rows the
                frontend has no way to correlate, and the thread and the
                pipeline state must come from the same place or they drift. */}
            <div className="flex flex-col gap-2">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-ink-faint">
                Conversation
              </p>

              {thread ? (
                <ThreadView thread={thread} />
              ) : (
                <p className="py-4 text-sm text-ink-faint">Loading the conversation…</p>
              )}

              {/* The reply being composed sits after the thread, where the
                  next message would go. */}
              {draft && !data.sent_at && (
                <div className="mt-2 rounded-xl border border-dashed border-rule bg-sunk px-3.5 py-3">
                  <div className="mb-1.5 flex flex-wrap items-baseline gap-2">
                    <span className="text-[13px] font-medium text-ink">You</span>
                    <Badge value={`DRAFT V${draft.version}`} dot={false} />
                    <span className="ml-auto">
                      <Button compact onClick={() => setTab("content")}>
                        Edit reply
                      </Button>
                    </span>
                  </div>
                  {subject && (
                    <p className="mb-1 text-[13px] font-semibold text-ink">{subject}</p>
                  )}
                  <p className="line-clamp-6 whitespace-pre-wrap text-[13px] leading-relaxed text-ink-soft">
                    {body}
                  </p>
                </div>
              )}

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
                {/* Drafting no longer waits on the notes being resolved - an
                    enquiry gets a reply either way, with the rate left blank
                    where there is no figure. So this offers the action rather
                    than sending the reviewer off to fix something first. */}
                <Empty
                  message="No draft has been written for this enquiry yet."
                  action={
                    <Button
                      variant="primary"
                      disabled={busy !== null}
                      onClick={() =>
                        act("regen", () => api.post(`/quotations/${data.id}/regenerate`))
                      }
                    >
                      {busy === "regen" ? "Generating…" : "Generate draft"}
                    </Button>
                  }
                />
              </Card>
            )}
          </>
        )}

        {/* --- Past orders --------------------------------------------------- */}
        {tab === "past" && <PastOrdersTab quotationId={data.id} />}

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
