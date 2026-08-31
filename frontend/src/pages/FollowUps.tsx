import { useCallback, useEffect, useMemo, useState } from "react";

import { api, useApi } from "../api/client";
import type {
  ChaseBoard,
  ChaseRow,
  LineItem,
  LostReason,
  QuotationStage,
} from "../api/types";
import ThreadView, { type Thread as ThreadData } from "../components/Thread";
import {
  ago,
  Banner,
  Button,
  Empty,
  ErrorNote,
  Input,
  inrShort,
  Loading,
  num,
  SearchInput,
  Select,
} from "../components/ui";
import {
  hueFor,
  initials,
  pcsText,
  PERIODS,
  sizeText,
  STAGE_COLOR,
  STAGES,
} from "../lib/lineItems";

/* ---------------------------------------------------------------------------
   The chase board.

   A row is an open **quotation**. It appears the moment the quotation reaches
   the customer and stays until the deal settles; nothing schedules a nudge on
   the trader's behalf, and the newest activity sits at the top.

   Reading and replying happen in a drawer over the list rather than on another
   route: a trader clearing fifteen follow-ups should never lose their place,
   and the reply is written with the customer's actual words still on screen.

   --------------------------------------------------------------------------- */

type Turn = ChaseRow["turn"];

/** The lifecycle as this screen offers it: everything except "Received".
 *
 *  A quotation only reaches this board once it has gone out, so moving one
 *  back to "received" would drop it off the screen it was moved from - a
 *  control whose only effect is to make the row vanish. */
const FOLLOWUP_LIFECYCLE = STAGES.filter((s) => s.key !== "received");

/** The sub-states of a follow-up, as cards over the table.
 *
 *  The same shape as the Quotations cards - "why hasn't this moved yet" - but
 *  asked of a quotation that has already gone out, so the answer is read off
 *  the lifecycle stage rather than a hand-set reason. Every row on this board
 *  is in exactly one of them. */
const FOLLOWUP_STAGES: { key: QuotationStage; label: string }[] = [
  { key: "sent", label: "Follow up pending" },
  { key: "negotiation", label: "Negotiation" },
  { key: "delivery_pending", label: "Pending PO" },
  { key: "payment_pending", label: "Payment pending" },
];

const LOST_REASONS: { value: LostReason; label: string }[] = [
  { value: "PRICE", label: "Our price was high" },
  { value: "COMPETITOR", label: "Went to a competitor" },
  { value: "DELAYED", label: "Project delayed" },
  { value: "NO_STOCK", label: "We could not supply" },
  { value: "NO_RESPONSE", label: "Never responded" },
  { value: "OTHER", label: "Something else" },
];

/** The stripe down a row's left edge: whose move it is, read before any word
 *  on the row is. Red is ours to answer, amber is theirs and quiet. */
const TURN_STRIPE: Record<Turn, string> = {
  YOURS: "bg-danger",
  THEIRS: "bg-attention",
  COLD: "bg-rule-firm",
  SNOOZED: "bg-brand-soft",
};

/* --------------------------------------------------------------------------
   The drawer: thread above, the reply you are about to send below
   -------------------------------------------------------------------------- */

function ChaseDrawer({
  row,
  onClose,
  onActed,
}: {
  row: ChaseRow;
  onClose: () => void;
  onActed: (message: string) => void;
}) {
  const thread = useApi<ThreadData>(`/quotations/${row.quotation_id}/thread`);
  const [body, setBody] = useState("");
  /* Which action is running: Send, Snooze and Won/Lost share this drawer, and
     one boolean put every one of them into its loading label. */
  const [busy, setBusy] = useState<"send" | "act" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);
  const [asking, setAsking] = useState<"none" | "snooze" | "lost">("none");
  const [snoozeDate, setSnoozeDate] = useState("");
  const [lostReason, setLostReason] = useState<LostReason>("PRICE");

  // Escape closes, matching every other overlay in the app.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // A fresh draft per quotation, so the trader edits rather than composes.
  useEffect(() => {
    setSent(false);
    setError(null);
    setAsking("none");
    setBody(defaultDraft(row));
  }, [row]);

  async function send() {
    setBusy("send");
    setError(null);
    try {
      await api.post(`/follow-ups/quotation/${row.quotation_id}/send`, {
        // No subject: this goes into the existing thread, so the server keeps
        // the one the customer already has in their inbox.
        body,
      });
      setSent(true);
      thread.reload();
      onActed(`Follow-up sent to ${row.customer_name}.`);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function act(path: string, payload: unknown, message: string) {
    setBusy("act");
    setError(null);
    try {
      await api.post(`/follow-ups/quotation/${row.quotation_id}/${path}`, payload);
      onActed(message);
      onClose();
    } catch (e) {
      setError((e as Error).message);
      setBusy(null);
    }
  }

  const hue = hueFor(row.customer_name);

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-ink/30 backdrop-blur-[1px]"
        onClick={onClose}
        aria-hidden
      />
      <aside
        role="dialog"
        aria-modal="true"
        aria-label={`Conversation with ${row.customer_name}`}
        // Same width as the Quotations drawer. A trader moves between the two
        // screens all day, and a panel that changes size on the way is read as
        // a different panel.
        className="fixed inset-y-0 right-0 z-50 flex w-full flex-col border-l border-rule bg-surface shadow-raised md:w-[min(56rem,64vw)]"
      >
        {/* --- who, and the figures that decide the reply ----------------- */}
        <header className="shrink-0 border-b border-rule px-4 py-3 sm:px-5">
          <div className="flex items-center gap-2.5">
            <span
              className="grid size-7 shrink-0 place-items-center rounded-full text-[10px] font-semibold text-white"
              style={{ background: `hsl(${hue} 62% 45%)` }}
            >
              {initials(row.customer_name)}
            </span>
            <div className="flex min-w-0 flex-1 items-baseline gap-2">
              <h2 className="shrink-0 text-[15px] font-semibold text-ink">
                {row.customer_name}
              </h2>
              <p className="truncate text-xs text-ink-faint">
                {row.customer_email ?? "no address on file"}
              </p>
            </div>
            <span className="shrink-0 whitespace-nowrap text-[11.5px] text-ink-faint">
              {row.message_count} {row.message_count === 1 ? "message" : "messages"}
            </span>
            <button
              type="button"
              onClick={onClose}
              aria-label="Close"
              className="shrink-0 rounded-lg p-1.5 text-ink-faint hover:bg-sunk hover:text-ink"
            >
              <svg
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
              >
                <path d="M18 6 6 18M6 6l12 12" />
              </svg>
            </button>
          </div>

          {/* One band: what to do, and what it is about. Everything else folds
              away - the header was four stacked bands and the conversation,
              which is what the drawer exists to show, started below the fold. */}
          <div
            className={`mt-2.5 rounded-lg px-3 py-2 text-[13px] ${
              row.turn === "YOURS"
                ? "bg-danger-wash text-danger-ink"
                : "bg-sunk text-ink-soft"
            }`}
          >
            <p>
              <span className="font-semibold">{row.next_step}.</span> {row.reason}
            </p>
            <p className="mt-0.5 text-[11.5px] opacity-80">
              {row.material} · {row.quantity} · {inrShort(row.value)}
            </p>
          </div>

          {row.stock_note && (
            <p
              className={`mt-1.5 rounded-lg px-3 py-1.5 text-[12.5px] font-medium ${
                row.stock_short
                  ? "bg-danger-wash text-danger-ink"
                  : "bg-attention-wash text-attention-ink"
              }`}
            >
              {row.stock_note}
            </p>
          )}

          <details className="group mt-1.5">
            <summary className="inline-flex cursor-pointer list-none items-center gap-1 text-[11.5px] text-ink-faint hover:text-ink-soft">
              <svg
                viewBox="0 0 24 24"
                className="size-3 transition-transform group-open:rotate-90"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
              >
                <path d="M9 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              Full details
            </summary>
            <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-2 border-t border-rule pt-2 sm:grid-cols-4">
              <Fact label="Quoted" value={row.sent_at ? stamp(row.sent_at) : "—"} />
              <Fact label="Last message" value={stamp(row.last_at)} />
              <Fact
                label="Quote age"
                value={row.quote_age_days === 0 ? "today" : `${row.quote_age_days} days`}
              />
              <Fact
                label="With this buyer"
                value={
                  row.quotes_total > 1
                    ? `won ${row.quotes_won} of ${row.quotes_total}`
                    : "first quote"
                }
              />
              <Fact label="Deliver to" value={row.delivery_location ?? "not stated"} />
              {row.required_by && <Fact label="Delivery date" value={row.required_by} />}
              {row.payment_terms && <Fact label="Payment" value={row.payment_terms} />}
              {row.promised_words && <Fact label="They said" value={row.promised_words} />}
            </dl>
          </details>
        </header>

        {/* --- the conversation ------------------------------------------- */}
        <div className="min-h-0 flex-1 overflow-y-auto bg-ground px-4 py-4 sm:px-5">
          {thread.loading && !thread.data ? (
            <Loading label="Loading the conversation" />
          ) : thread.error ? (
            <ErrorNote message={thread.error} />
          ) : thread.data ? (
            <ThreadView thread={thread.data} showState={false} showCount={false} />
          ) : null}
        </div>

        {/* --- what you are about to send --------------------------------- */}
        <footer className="max-h-[45vh] shrink-0 overflow-y-auto border-t border-rule bg-surface px-4 py-3 sm:px-5">
          {sent ? (
            <div className="flex items-center gap-2 rounded-lg border border-settled/30 bg-settled-wash px-3 py-2.5 text-sm font-medium text-settled-ink">
              <svg
                width="16"
                height="16"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M20 6 9 17l-5-5" />
              </svg>
              Sent. This moves to “Their turn”.
            </div>
          ) : asking === "snooze" ? (
            <div className="flex flex-wrap items-end gap-2">
              <label className="flex flex-col gap-1">
                <span className="text-[11px] uppercase tracking-wider text-ink-faint">
                  Bring it back on
                </span>
                <Input type="date" value={snoozeDate} onChange={setSnoozeDate} />
              </label>
              <Button
                variant="primary"
                disabled={busy !== null || !snoozeDate}
                onClick={() =>
                  act("snooze", { until: snoozeDate }, `${row.customer_name} parked.`)
                }
              >
                Park it
              </Button>
              <Button variant="ghost" onClick={() => setAsking("none")}>
                Cancel
              </Button>
            </div>
          ) : asking === "lost" ? (
            <div className="flex flex-wrap items-end gap-2">
              <label className="flex min-w-56 flex-col gap-1">
                <span className="text-[11px] uppercase tracking-wider text-ink-faint">
                  Why did we lose it?
                </span>
                <Select
                  value={lostReason}
                  onChange={(v) => setLostReason(v as LostReason)}
                  options={LOST_REASONS.map((r) => ({ value: r.value, label: r.label }))}
                />
              </label>
              <Button
                variant="danger"
                disabled={busy !== null}
                onClick={() =>
                  act("lost", { reason: lostReason }, `${row.customer_name} marked lost.`)
                }
              >
                Mark lost
              </Button>
              <Button variant="ghost" onClick={() => setAsking("none")}>
                Cancel
              </Button>
            </div>
          ) : (
            <>
              <div className="mb-2 flex items-center gap-2">
                <span className="text-[11px] font-semibold uppercase tracking-wider text-ink-faint">
                  Your follow-up
                </span>
                <span className="rounded-full bg-brand-wash px-2 py-0.5 text-[10.5px] font-semibold text-brand-ink">
                  drafted for you
                </span>
              </div>
              <textarea
                value={body}
                onChange={(e) => setBody(e.target.value)}
                rows={4}
                className="w-full resize-y rounded-lg border border-rule-firm bg-ground px-3 py-2.5 text-[13px] leading-relaxed text-ink outline-none focus:border-brand focus:bg-surface"
              />
              {error && (
                <div className="mt-2">
                  <ErrorNote message={error} />
                </div>
              )}
              <div className="mt-2.5 flex flex-wrap items-center gap-2">
                <span className="text-[11px] text-ink-faint">Goes into the same thread.</span>
                <span className="ml-auto flex flex-wrap gap-2">
                  <Button compact onClick={() => setAsking("snooze")}>
                    Snooze
                  </Button>
                  <Button compact onClick={() => setAsking("lost")}>
                    Mark lost
                  </Button>
                  <Button
                    compact
                    variant="primary"
                    disabled={busy !== null || !body.trim()}
                    onClick={send}
                  >
                    {busy === "send" ? "Sending…" : "Send follow-up"}
                  </Button>
                </span>
              </div>
            </>
          )}
        </footer>
      </aside>
    </>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[10.5px] font-semibold uppercase tracking-wider text-ink-faint">
        {label}
      </dt>
      {/* Wraps rather than truncates: a payment term runs to a full sentence
          ("30 days credit from date of receipt…"), and cutting it at the
          column edge hides the half that carries the condition. */}
      <dd className="text-[13px] font-medium leading-snug tabular-nums text-ink">{value}</dd>
    </div>
  );
}

/** A starting point, not a finished letter — the trader edits it with the
 *  customer's own words still on screen above. */
function defaultDraft(row: ChaseRow): string {
  const who = row.contact_name ? `Dear ${row.contact_name},` : "Dear Sir,";
  const what = `${row.material}${row.quantity !== "—" ? ` (${row.quantity})` : ""}`;

  if (row.turn === "YOURS" && row.last_direction === "INBOUND") {
    return `${who}\n\nThank you for coming back to us on ${what}.\n\n[your answer here]\n\nRegards,`;
  }
  if (row.promised_date) {
    return `${who}\n\nFollowing up on our quotation for ${what}, which you were kind enough to say you would decide on.\n\nIs there anything you need from us to move it forward?\n\nRegards,`;
  }
  return `${who}\n\nJust following up on our quotation for ${what}, sent ${
    row.sent_at ? ago(row.sent_at) : "recently"
  }.\n\nPlease let me know if the rate works for you, or what needs to change.\n\nRegards,`;
}

/* --------------------------------------------------------------------------
   The table
   -------------------------------------------------------------------------- */

/** Exact date and time, because "who moved last and when" is answerable
 *  precisely and a trader reads a timestamp faster than a relative phrase
 *  when comparing rows against each other. */
function stamp(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function Chip({
  tone,
  children,
}: {
  tone: "info" | "danger" | "attention" | "quiet";
  children: React.ReactNode;
}) {
  const tones = {
    info: "bg-info-wash text-info-ink",
    danger: "bg-danger-wash text-danger-ink",
    attention: "bg-attention-wash text-attention-ink",
    quiet: "bg-sunk text-ink-soft",
  };
  return (
    <span
      className={`whitespace-nowrap rounded-full px-2 py-0.5 text-[10.5px] font-medium ${tones[tone]}`}
    >
      {children}
    </span>
  );
}

/** One material line within a follow-up's row-group.
 *
 *  Deliberately the same shape as the quotations list's `LineRow`: the
 *  quotation-level cells (customer, value, stage, waiting, next step) carry a
 *  rowSpan over the whole group, and each line contributes only its own
 *  specification. A trader crossing between the two screens reads one table,
 *  not two that happen to list the same steel. */
function LineRow({
  row,
  item,
  rowSpan,
  selected,
  onOpen,
  onStage,
}: {
  row: ChaseRow;
  item: LineItem | null;
  rowSpan: number | null;
  selected: boolean;
  onOpen: () => void;
  onStage: (stage: QuotationStage) => void;
}) {
  const hue = hueFor(row.customer_name);
  const urgent = row.turn === "YOURS";

  return (
    <tr
      className={`border-b border-rule align-top last:border-0 ${
        selected
          ? "bg-brand-wash"
          : row.is_priority
            ? "bg-attention-wash/30 hover:bg-attention-wash/50"
            : "hover:bg-ground"
      } ${row.turn === "COLD" ? "opacity-75" : ""}`}
    >
      {/* --- who ---------------------------------------------------------- */}
      {rowSpan !== null && (
        <td
          rowSpan={rowSpan}
          onClick={onOpen}
          className={`relative cursor-pointer border-r border-rule py-2.5 pl-3 pr-3 align-top ${
            row.is_priority ? "bg-attention-wash/20" : ""
          }`}
        >
          {/* The left edge stays the turn stripe rather than the priority one
              the quotations list draws there: on this screen whose move it is
              is the thing that orders the day. Priority shows as the row wash
              and the star, exactly as it does over there. */}
          <span
            className={`absolute inset-y-0 left-0 w-1 ${TURN_STRIPE[row.turn]}`}
            aria-hidden
          />
          <div className="flex items-start gap-2.5">
            <span
              className="mt-0.5 grid size-6 shrink-0 place-items-center rounded-full text-[10px] font-semibold text-white"
              style={{ background: `hsl(${hue} 62% 45%)` }}
            >
              {initials(row.customer_name)}
            </span>
            <span className="min-w-0">
              <span className="flex items-center gap-1.5">
                <span
                  className={`truncate text-[13.5px] leading-tight text-ink ${
                    urgent ? "font-semibold" : "font-medium"
                  }`}
                >
                  {row.customer_name}
                </span>
                {row.is_priority && (
                  <span className="shrink-0 text-attention" title="Priority">
                    ★
                  </span>
                )}
              </span>
              <span className="block truncate text-[11.5px] text-ink-faint">
                {row.customer_email ?? "no address on file"}
              </span>
            </span>
          </div>
        </td>
      )}

      {/* --- the specification, line by line ------------------------------- */}
      <td className="cursor-pointer px-3 py-2 text-[13px] text-ink" onClick={onOpen}>
        {item?.grade ?? "—"}
      </td>
      <td className="cursor-pointer px-3 py-2 text-[13px] text-ink-soft" onClick={onOpen}>
        {item?.product_type ?? "—"}
      </td>
      <td className="cursor-pointer px-3 py-2 text-[13px] text-ink-soft" onClick={onOpen}>
        {item ? sizeText(item) : "—"}
      </td>
      <td
        className="tabular cursor-pointer px-3 py-2 text-right text-[13px] text-ink"
        onClick={onOpen}
      >
        {item?.quantity_mt ? num(item.quantity_mt) : "—"}
      </td>
      <td
        className="tabular cursor-pointer px-3 py-2 text-right text-[13px] text-ink-soft"
        onClick={onOpen}
      >
        {item ? pcsText(item) : "—"}
      </td>
      <td className="cursor-pointer px-3 py-2 text-[13px] text-ink-soft" onClick={onOpen}>
        {item?.matched_stock_item_make ?? "—"}
      </td>

      {/* --- money -------------------------------------------------------- */}
      {rowSpan !== null && (
        <td
          rowSpan={rowSpan}
          className="cursor-pointer border-l border-rule px-3 py-2 text-right align-top"
          onClick={onOpen}
        >
          {row.value > 0 ? (
            <>
              <span className="block whitespace-nowrap text-[13px] font-semibold tabular-nums text-ink">
                {inrShort(row.value)}
              </span>
              {row.quoted_rate ? (
                <span className="block whitespace-nowrap text-[11px] tabular-nums text-ink-faint">
                  ₹{row.quoted_rate.toLocaleString("en-IN", { maximumFractionDigits: 0 })}/MT
                </span>
              ) : null}
            </>
          ) : (
            <span className="text-ink-faint">—</span>
          )}
        </td>
      )}

      {/* --- where it sits commercially ------------------------------------ */}
      {rowSpan !== null && (
        <td rowSpan={rowSpan} className="border-l border-rule px-3 py-2 align-top">
          {/* The click is stopped here: the row opens the drawer, and a trader
              reaching for the stage picker is not asking to read the thread. */}
          <select
            value={row.stage}
            onClick={(e) => e.stopPropagation()}
            onChange={(e) => onStage(e.target.value as QuotationStage)}
            className={`rounded-md border border-rule bg-surface px-1.5 py-1 text-[11.5px] font-medium focus:border-brand focus:outline-none ${
              STAGE_COLOR[row.stage] ?? "text-ink"
            }`}
          >
            {FOLLOWUP_LIFECYCLE.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </select>

          {/* Who moved last and how many messages there are used to sit here.
              Both are in the drawer, which is one click away and shows the
              actual thread - under a stage picker they were three lines of
              detail wrapped around the one control this column exists for.

              The stock note stays: it is not thread history but a warning
              that the yard cannot cover what was quoted, and it changes
              whether chasing this row is worth doing at all. */}
          {row.stock_note && (
            <span className="mt-1.5 flex">
              <Chip tone={row.stock_short ? "danger" : "attention"}>{row.stock_note}</Chip>
            </span>
          )}
        </td>
      )}

      {/* --- how long the ball has sat ------------------------------------- */}
      {rowSpan !== null && (
        <td
          rowSpan={rowSpan}
          className="cursor-pointer border-l border-rule px-3 py-2 pr-4 text-right align-top"
          onClick={onOpen}
        >
          <span
            className={`block whitespace-nowrap text-[13px] tabular-nums ${
              urgent ? "font-semibold text-danger-ink" : "text-ink-soft"
            }`}
          >
            {row.days_waiting === 0 ? "today" : `${row.days_waiting}d`}
          </span>
          <span className="block whitespace-nowrap text-[11px] text-ink-faint">
            {row.waiting_note}
          </span>
          {row.attempts > 0 && (
            <span className="mt-1 block whitespace-nowrap text-[10.5px] text-ink-faint">
              chased {row.attempts}×
            </span>
          )}
        </td>
      )}
    </tr>
  );
}

/* --------------------------------------------------------------------------
   Page
   -------------------------------------------------------------------------- */

export default function FollowUps() {
  const board = useApi<ChaseBoard>("/follow-ups/board", 60_000);
  /* Their turn, not yours. "Your turn" is empty on a desk that is keeping up,
     so opening there shows an empty screen most days; the quotations sitting
     with a customer are the ones a trader actually works down. */
  const [search, setSearch] = useState("");
  const [days, setDays] = useState("30");
  const [stage, setStage] = useState<QuotationStage | "all">("all");
  const [stageFilter, setStageFilter] = useState<QuotationStage | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);
  const [flash, setFlash] = useState<string | null>(null);
  const [stageError, setStageError] = useState<string | null>(null);

  /* The same filter chain as the quotations list, in the same order:
     search, then how far back, then the stage dropdown, then a card. Each
     stage's counts are taken from the step above it, so a dropdown option
     never claims more rows than picking it would show. */
  const searched = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (term === "") return board.data?.rows ?? [];
    return (
      board.data?.rows.filter((r) =>
        [r.customer_name, r.material, r.quotation_number, r.customer_email].some((field) =>
          field?.toLowerCase().includes(term),
        ),
      ) ?? []
    );
  }, [board.data, search]);

  /* Dated from when the quotation went out, not when the enquiry arrived:
     this board only holds quotations that have been sent, and "how long has
     it been out" is the question the screen is about. */
  const periodFiltered = useMemo(() => {
    if (days === "all") return searched;
    const cutoff = Date.now() - Number(days) * 24 * 60 * 60 * 1000;
    return searched.filter((r) => !r.sent_at || new Date(r.sent_at).getTime() >= cutoff);
  }, [searched, days]);

  const countFor = (key: QuotationStage | "all") =>
    key === "all"
      ? periodFiltered.length
      : periodFiltered.filter((r) => r.stage === key).length;

  const stageFiltered = useMemo(
    () => (stage === "all" ? periodFiltered : periodFiltered.filter((r) => r.stage === stage)),
    [periodFiltered, stage],
  );

  /** Count, tonnage and money per sub-state, for the cards. Scoped to the
   *  period rather than the stage dropdown - the cards are how a trader
   *  picks a stage, so scoping them to the stage already picked would leave
   *  three of the four permanently reading zero. */
  const byStage = useMemo(() => {
    const totals: Record<string, { count: number; tonnes: number; value: number }> = {};
    for (const s of FOLLOWUP_STAGES) totals[s.key] = { count: 0, tonnes: 0, value: 0 };
    for (const r of periodFiltered) {
      const bucket = totals[r.stage];
      if (!bucket) continue;
      bucket.count += 1;
      bucket.tonnes += r.tonnes;
      bucket.value += r.value;
    }
    return totals;
  }, [periodFiltered]);

  const rows = useMemo(
    () => (stageFilter ? periodFiltered.filter((r) => r.stage === stageFilter) : stageFiltered),
    [periodFiltered, stageFiltered, stageFilter],
  );
  const openRow = board.data?.rows.find((r) => r.quotation_id === openId) ?? null;

  const onActed = useCallback(
    (message: string) => {
      setFlash(message);
      board.reload();
    },
    [board],
  );

  /* The same endpoint the Quotations list posts to. Reloading the board is
     what keeps the cards honest: moving a row to "payment pending" has to
     move the tonnage between two cards, not just relabel the row. */
  const moveStage = useCallback(
    async (quotationId: number, stage: QuotationStage) => {
      setStageError(null);
      try {
        await api.post(`/quotations/${quotationId}/stage`, { stage });
        board.reload();
      } catch (e) {
        // Not the flash banner: that one is green, and a refused stage change
        // reported in the colour of success is worse than no message at all.
        setStageError((e as Error).message);
      }
    },
    [board],
  );

  useEffect(() => {
    if (!flash) return;
    const t = setTimeout(() => setFlash(null), 4000);
    return () => clearTimeout(t);
  }, [flash]);

  if (board.loading && !board.data) return <Loading label="Working out who needs chasing" />;
  if (board.error) return <ErrorNote message={board.error} />;

  return (
    <div className="flex flex-col gap-3 p-5">
      {/* Search left, filter and Rules right - the same toolbar as the
          quotations list, because a trader crosses between the two screens
          all day. */}
      <header className="flex flex-wrap items-center gap-2">
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder="Search by customer, material or number…"
          className="w-full sm:w-72"
        />
        <div className="ml-auto flex items-center gap-2">
          <Select value={days} onChange={setDays} options={PERIODS} className="py-1.5" />
          <Select
            value={stage}
            onChange={(v) => {
              setStage(v as QuotationStage | "all");
              // The dropdown and the cards ask the same question, so picking
              // one clears the other rather than quietly intersecting.
              setStageFilter(null);
            }}
            options={[
              // The count rides on the option: a filter that hides how much it
              // is hiding makes an empty table look like a broken one.
              { value: "all", label: `All (${countFor("all")})` },
              ...FOLLOWUP_LIFECYCLE.map((s) => ({
                value: s.key,
                label: `${s.label} (${countFor(s.key)})`,
              })),
            ]}
            className="py-1.5"
          />
        </div>
      </header>

      {/* --- Where the followed-up money actually sits -------------------- */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {FOLLOWUP_STAGES.map((s) => (
          <button
            key={s.key}
            type="button"
            onClick={() => setStageFilter((cur) => (cur === s.key ? null : s.key))}
            className={`rounded-card border px-3 py-2.5 text-left transition-colors ${
              stageFilter === s.key
                ? "border-brand bg-brand-wash"
                : "border-rule bg-surface hover:border-brand/50"
            }`}
          >
            <p className="truncate text-[11px] font-medium uppercase tracking-wide text-ink-faint">
              {s.label}
            </p>
            <p className="tabular mt-0.5 text-xl font-semibold text-ink">
              {byStage[s.key]?.count ?? 0}
            </p>
            <p className="tabular truncate text-[11px] text-ink-faint">
              {num(byStage[s.key]?.tonnes ?? 0)} MT · {inrShort(byStage[s.key]?.value ?? 0)}
            </p>
          </button>
        ))}
      </div>

      {flash && <Banner tone="settled">{flash}</Banner>}
      {stageError && <ErrorNote message={stageError} />}

      <div className="overflow-hidden rounded-card border border-rule bg-surface shadow-card">
        {rows.length === 0 ? (
          <Empty
            message={
              /* A search that found nothing is not the same as a filter with
                 nothing in it: one is fixed by changing the term, the other by
                 changing the filter. */
              search.trim()
                ? `No quotation matches “${search.trim()}”.`
                : "Nothing here. Quotations appear once they have gone out."
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[64rem] border-collapse">
              <thead>
                <tr className="border-b border-rule">
                  {[
                    ["Customer", "pl-4 pr-3 text-left"],
                    ["Grade", "px-3 text-left"],
                    ["Type", "px-3 text-left"],
                    ["Size", "px-3 text-left"],
                    ["Weight (MT)", "px-3 text-right"],
                    ["PCS", "px-3 text-right"],
                    ["Make", "px-3 text-left"],
                    ["Price", "px-3 text-right"],
                    ["Status", "px-3 text-left"],
                    ["Waiting", "px-3 pr-4 text-right"],
                  ].map(([label, cls]) => (
                    <th
                      key={label}
                      className={`${cls} whitespace-nowrap py-2 text-[10.5px] font-semibold uppercase tracking-wider text-ink-faint`}
                    >
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  // A quotation with no extracted lines still gets one row, so
                  // it never silently vanishes from the board.
                  const items = row.line_items.length > 0 ? row.line_items : [null];
                  return items.map((item, i) => (
                    <LineRow
                      key={item ? item.id : `${row.quotation_id}-empty`}
                      row={row}
                      item={item}
                      rowSpan={i === 0 ? items.length : null}
                      selected={row.quotation_id === openId}
                      onOpen={() => setOpenId(row.quotation_id)}
                      onStage={(stage) => moveStage(row.quotation_id, stage)}
                    />
                  ));
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {openRow && (
        <ChaseDrawer row={openRow} onClose={() => setOpenId(null)} onActed={onActed} />
      )}
    </div>
  );
}
