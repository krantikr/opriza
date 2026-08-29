import { useCallback, useEffect, useMemo, useState } from "react";

import { api, useApi } from "../api/client";
import type { ChaseBoard, ChaseRow, FollowUpRule, LostReason } from "../api/types";
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
  SearchInput,
  Select,
  Toggle,
} from "../components/ui";

/* ---------------------------------------------------------------------------
   The chase board.

   A row is an open **quotation**, not a scheduled nudge. That inversion is the
   whole design, and it fixes what the schedule-shaped screen could not:

   * a customer who replied and was never answered now has somewhere to appear
     (their reply cancels the schedule, so the old screen structurally hid the
     most urgent thing on the desk);
   * ordering is money at risk rather than `due_at`, so an ₹18 lakh quotation
     never sits under a ₹2,000 one that went overdue an hour earlier.

   Reading and replying happen in a drawer over the list rather than on another
   route: a trader clearing fifteen follow-ups should never lose their place,
   and the reply is written with the customer's actual words still on screen.

   The rules that decide *when* a nudge is owed live behind the Rules button.
   They are configured a few times a year; this screen is opened every morning.
   --------------------------------------------------------------------------- */

type Turn = ChaseRow["turn"];

const TABS: { key: Turn; label: string; hint: string }[] = [
  {
    key: "YOURS",
    label: "Your turn",
    hint: "They replied, sent an order, or a promised date passed — and nobody has answered.",
  },
  {
    key: "THEIRS",
    label: "Their turn",
    hint: "You answered. The ball is with them and it has gone quiet.",
  },
  {
    key: "COLD",
    label: "Going cold",
    hint: "Nothing has moved for three weeks. One decision each: chase hard, or write it off.",
  },
  {
    key: "SNOOZED",
    label: "Snoozed",
    hint: "Parked until a date you chose. Nothing here needs you yet.",
  },
];

const LOST_REASONS: { value: LostReason; label: string }[] = [
  { value: "PRICE", label: "Our price was high" },
  { value: "COMPETITOR", label: "Went to a competitor" },
  { value: "DELAYED", label: "Project delayed" },
  { value: "NO_STOCK", label: "We could not supply" },
  { value: "NO_RESPONSE", label: "Never responded" },
  { value: "OTHER", label: "Something else" },
];

/** Stable hue per customer, matching the Inbox: the same buyer is always the
 *  same colour, so the eye learns the list faster than it reads it. */
function hueFor(name: string): number {
  const hues = [212, 340, 152, 28, 265, 190];
  let total = 0;
  for (const ch of name) total += ch.charCodeAt(0);
  return hues[total % hues.length];
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0] ?? "")
    .join("")
    .toUpperCase();
}

const TURN_STRIPE: Record<Turn, string> = {
  YOURS: "bg-danger",
  THEIRS: "bg-attention",
  COLD: "bg-rule-firm",
  SNOOZED: "bg-brand-soft",
};

/* --------------------------------------------------------------------------
   Rules, in a panel rather than on the page
   -------------------------------------------------------------------------- */

function RuleEditor({ rule, onSaved }: { rule: FollowUpRule; onSaved: () => void }) {
  const [draft, setDraft] = useState(rule);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setDraft(rule), [rule]);

  const dirty = JSON.stringify(draft) !== JSON.stringify(rule);
  const promised = draft.trigger === "PROMISED_DATE";

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await api.put(`/follow-up-rules/${rule.id}`, draft);
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const numberField = (
    key: "first_after_days" | "interval_days" | "max_attempts" | "stop_after_days",
    label: string,
    unit: string,
  ) => (
    <label className="flex flex-col gap-1">
      <span className="text-[10.5px] font-semibold uppercase tracking-wider text-ink-faint">
        {label}
      </span>
      <span className="flex items-center gap-1.5">
        <Input
          type="number"
          value={String(draft[key] ?? "")}
          onChange={(v) =>
            setDraft({ ...draft, [key]: v === "" ? null : Number(v) } as FollowUpRule)
          }
          className="w-16 text-center tabular-nums"
        />
        <span className="text-xs text-ink-faint">{unit}</span>
      </span>
    </label>
  );

  return (
    <section
      className={`rounded-card border p-4 transition-colors ${
        draft.is_active ? "border-rule bg-surface" : "border-rule bg-sunk/60"
      }`}
    >
      {/* The switch sits on its own line above the name. Beside it, a long
          label and the Save button competed for the same row and the flex
          parent compressed the switch until its text lost a letter. */}
      <div className="mb-3 flex items-center justify-between gap-3">
        <Toggle
          checked={draft.is_active}
          onChange={(is_active) => setDraft({ ...draft, is_active })}
          label={draft.is_active ? "Active" : "Paused"}
        />
        <Button variant="primary" compact disabled={!dirty || busy} onClick={save}>
          {busy ? "Saving…" : dirty ? "Save" : "Saved"}
        </Button>
      </div>

      <Input
        value={draft.label}
        onChange={(label) => setDraft({ ...draft, label })}
        className="mb-3 font-medium"
      />

      <label className="mb-3 flex flex-col gap-1">
        <span className="text-[10.5px] font-semibold uppercase tracking-wider text-ink-faint">
          Start the clock
        </span>
        <Select
          value={draft.trigger}
          onChange={(v) => setDraft({ ...draft, trigger: v as FollowUpRule["trigger"] })}
          options={[
            { value: "ELAPSED", label: "When the quotation went out" },
            { value: "PROMISED_DATE", label: "On the date the customer gave" },
          ]}
          className="w-full"
        />
      </label>

      {promised ? (
        <label className="flex flex-col gap-1">
          <span className="text-[10.5px] font-semibold uppercase tracking-wider text-ink-faint">
            Remind before
          </span>
          <span className="flex items-center gap-1.5">
            <Input
              type="number"
              value={String(draft.remind_before_hours)}
              onChange={(v) => setDraft({ ...draft, remind_before_hours: Number(v) })}
              className="w-16 text-center tabular-nums"
            />
            <span className="text-xs text-ink-faint">hours · 0 means on the day</span>
          </span>
        </label>
      ) : (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {numberField("first_after_days", "First after", "days")}
          {numberField("interval_days", "Then every", "days")}
          {numberField("max_attempts", "At most", "times")}
          {numberField("stop_after_days", "Give up after", "days")}
        </div>
      )}

      <p className="mt-3 border-t border-rule pt-3 text-xs leading-relaxed text-ink-soft">
        {promised
          ? draft.remind_before_hours === 0
            ? "Raises a reminder on the day the customer said they would decide."
            : `Raises a reminder ${draft.remind_before_hours} hours before the date the customer gave.`
          : `Chases ${draft.max_attempts} time${draft.max_attempts === 1 ? "" : "s"}, first ${
              draft.first_after_days
            } day${draft.first_after_days === 1 ? "" : "s"} after sending, then every ${
              draft.interval_days
            } days.`}
        {draft.mark_cold_when_exhausted && " Marked cold once the attempts are spent."}
      </p>

      {draft.auto_send && (
        <div className="mt-3">
          <Banner tone="attention">
            This rule sends without asking. Every other rule queues its nudge for a person.
          </Banner>
        </div>
      )}
      {error && (
        <div className="mt-3">
          <ErrorNote message={error} />
        </div>
      )}
    </section>
  );
}

/** Rules live in a modal, not on the page.
 *
 *  They are configured a few times a year; the board is opened every morning.
 *  Inline, four number fields per rule pushed the actual work below the fold
 *  and made the screen read as a settings page that happens to list quotations. */
function RulesModal({ onClose }: { onClose: () => void }) {
  const rules = useApi<FollowUpRule[]>("/follow-up-rules");
  const [running, setRunning] = useState(false);
  const [ran, setRan] = useState<string | null>(null);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  async function runNow() {
    setRunning(true);
    try {
      const r = await api.post<{ due: number; scheduled: number }>("/follow-ups/run");
      setRan(`${r.due} due now, ${r.scheduled} scheduled.`);
    } catch (e) {
      setRan((e as Error).message);
    } finally {
      setRunning(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-ink/40 p-0 backdrop-blur-[1px] sm:items-center sm:p-4"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Follow-up rules"
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[92vh] w-full flex-col overflow-hidden rounded-t-card border border-rule bg-surface shadow-raised sm:max-w-2xl sm:rounded-card"
      >
        <header className="flex shrink-0 items-start justify-between gap-3 border-b border-rule px-5 py-3.5">
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-ink">When a quotation gets chased</h2>
            <p className="text-xs text-ink-faint">
              The rules work out when a nudge is owed and draft it. You still press send.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="shrink-0 rounded-lg p-1.5 text-ink-faint hover:bg-sunk hover:text-ink"
          >
            <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="1.8">
              <path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" />
            </svg>
          </button>
        </header>

        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto bg-ground px-5 py-4">
          {rules.loading && !rules.data ? (
            <Loading label="Loading rules" />
          ) : rules.data?.length ? (
            rules.data.map((rule) => (
              <RuleEditor key={rule.id} rule={rule} onSaved={rules.reload} />
            ))
          ) : (
            <Empty message="No rules yet, so nothing is chased automatically. You can still chase any row by hand." />
          )}
        </div>

        <footer className="flex shrink-0 flex-wrap items-center gap-3 border-t border-rule px-5 py-3">
          <span className="text-xs text-ink-faint">
            {ran ?? "Rules are evaluated on a timer."}
          </span>
          <span className="ml-auto flex gap-2">
            <Button compact disabled={running} onClick={runNow}>
              {running ? "Checking…" : "Check now"}
            </Button>
            <Button compact variant="primary" onClick={onClose}>
              Done
            </Button>
          </span>
        </footer>
      </div>
    </div>
  );
}

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

  // A fresh draft per quotation. Seeded from the nudge the scheduler already
  // wrote where there is one, so the trader edits rather than composes.
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
        schedule_id: row.schedule_id,
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
              <Fact label="Delivery" value={row.delivery_location ?? "not stated"} />
              {row.required_by && <Fact label="Needed by" value={row.required_by} />}
              {row.payment_terms && <Fact label="Payment" value={row.payment_terms} />}
              {row.promised_words && <Fact label="They said" value={row.promised_words} />}
              {row.chase_note && <Fact label="Chasing" value={row.chase_note} />}
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
      <dd className="truncate text-[13px] font-medium tabular-nums text-ink">{value}</dd>
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

function Row({
  row,
  selected,
  onOpen,
}: {
  row: ChaseRow;
  selected: boolean;
  onOpen: () => void;
}) {
  const hue = hueFor(row.customer_name);
  const urgent = row.turn === "YOURS";
  const inbound = row.last_direction === "INBOUND";

  return (
    <tr
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen();
        }
      }}
      tabIndex={0}
      aria-selected={selected}
      className={`cursor-pointer border-b border-rule align-top outline-none last:border-0 focus-visible:bg-sunk ${
        selected ? "bg-brand-wash" : "hover:bg-ground"
      } ${row.turn === "COLD" ? "opacity-75" : ""}`}
    >
      {/* --- who ---------------------------------------------------------- */}
      <td className="relative py-2.5 pl-3 pr-3">
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
            <span
              className={`block truncate text-[13.5px] leading-tight text-ink ${
                urgent ? "font-semibold" : "font-medium"
              }`}
            >
              {row.customer_name}
            </span>
            <span className="block truncate text-[11.5px] text-ink-faint">
              {row.customer_note}
            </span>
          </span>
        </div>
      </td>

      {/* --- what, and whether we can actually supply it ------------------- */}
      <td className="px-3 py-2.5">
        <span className="block text-[13px] leading-tight text-ink">{row.material}</span>
        <span className="block text-[11.5px] tabular-nums text-ink-faint">{row.quantity}</span>
        {(row.stock_note || row.delivery_location) && (
          <span className="mt-1 flex flex-wrap gap-1">
            {row.stock_note && (
              <Chip tone={row.stock_short ? "danger" : "attention"}>{row.stock_note}</Chip>
            )}
            {row.delivery_location && <Chip tone="quiet">{row.delivery_location}</Chip>}
          </span>
        )}
      </td>

      {/* --- the exact last movement on the thread ------------------------- */}
      <td className="px-3 py-2.5">
        <span className="flex items-center gap-1.5 text-[12.5px] leading-tight">
          <span
            className={`inline-block size-1.5 shrink-0 rounded-full ${
              inbound ? "bg-attention" : "bg-brand-soft"
            }`}
            aria-hidden
          />
          <span className={inbound ? "font-medium text-ink" : "text-ink-soft"}>
            {row.last_actor}
          </span>
        </span>
        <span className="mt-0.5 block whitespace-nowrap text-[11.5px] tabular-nums text-ink-faint">
          {stamp(row.last_at)}
        </span>
        <span className="mt-1 flex flex-wrap gap-1">
          <Chip tone="quiet">
            {row.message_count} {row.message_count === 1 ? "msg" : "msgs"}
          </Chip>
          {row.has_attachment && <Chip tone="info">attachment</Chip>}
          {row.attempts > 0 && (
            <Chip tone="quiet">
              chased {row.attempts}×
              {row.last_chased_at ? ` · ${ago(row.last_chased_at)}` : ""}
            </Chip>
          )}
        </span>
      </td>

      {/* --- money -------------------------------------------------------- */}
      <td className="px-3 py-2.5 text-right">
        <span className="block whitespace-nowrap text-[14px] font-semibold tabular-nums text-ink">
          {inrShort(row.value)}
        </span>
        {row.quoted_rate ? (
          <span className="block whitespace-nowrap text-[11px] tabular-nums text-ink-faint">
            ₹{row.quoted_rate.toLocaleString("en-IN", { maximumFractionDigits: 0 })}/MT
          </span>
        ) : null}
      </td>

      {/* --- the two clocks: ball-in-court, and the quote's own shelf life -- */}
      <td className="px-3 py-2.5 text-right">
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
        {/* Only appears when the desk's own give-up deadline is close. It is
            deliberately not called validity: how long a price stands is a
            promise to the customer that this system never recorded. */}
        {row.chase_note && (
          <span className="mt-1 block whitespace-nowrap text-[10.5px] font-medium text-attention-ink">
            {row.chase_note}
          </span>
        )}
      </td>

      {/* --- what to do about it ------------------------------------------- */}
      <td className="border-l border-rule py-2.5 pl-4 pr-4">
        <span
          className={`block text-[12.5px] leading-tight ${
            urgent ? "font-semibold text-ink" : "font-medium text-ink-soft"
          }`}
        >
          {row.next_step}
        </span>
        <span className="mt-0.5 block text-[11px] leading-snug text-ink-faint">
          {row.reason}
        </span>
      </td>
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
  const [tab, setTab] = useState<Turn>("THEIRS");
  const [search, setSearch] = useState("");
  const [openId, setOpenId] = useState<number | null>(null);
  const [showRules, setShowRules] = useState(false);
  const [flash, setFlash] = useState<string | null>(null);

  const rows = useMemo(() => {
    const term = search.trim().toLowerCase();
    return (
      board.data?.rows.filter(
        (r) =>
          r.turn === tab &&
          (term === "" ||
            [r.customer_name, r.material, r.quotation_number, r.customer_email]
              .some((field) => field?.toLowerCase().includes(term))),
      ) ?? []
    );
  }, [board.data, tab, search]);
  const openRow = board.data?.rows.find((r) => r.quotation_id === openId) ?? null;

  const onActed = useCallback(
    (message: string) => {
      setFlash(message);
      board.reload();
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

  const counts = board.data?.counts ?? {};
  const hint = TABS.find((t) => t.key === tab)?.hint;

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
          <Select
            value={tab}
            onChange={(v) => setTab(v as Turn)}
            options={TABS.map((t) => ({
              value: t.key,
              // The count rides on the option: a filter that hides how much it
              // is hiding makes an empty table look like a broken one.
              label: `${t.label} (${counts[t.key] ?? 0})`,
            }))}
            className="py-1.5"
          />
          <Button onClick={() => setShowRules(true)}>Rules</Button>
        </div>
      </header>

      {flash && <Banner tone="settled">{flash}</Banner>}

      {/* What the selected filter means. Carried the tab strip's weight once
          the strip became a dropdown - "Their turn" alone does not say the
          ball is with the customer and has gone quiet. */}
      <p className="text-xs text-ink-faint">{hint}</p>

      <div className="overflow-hidden rounded-card border border-rule bg-surface shadow-card">
        {rows.length === 0 ? (
          <Empty
            message={
              /* A search that found nothing is not the same as a filter with
                 nothing in it: one is fixed by changing the term, the other by
                 changing the filter. */
              search.trim()
                ? `No ${(TABS.find((t) => t.key === tab)?.label ?? "").toLowerCase()} quotation matches “${search.trim()}”.`
                : tab === "YOURS"
                  ? "Nothing is waiting on you. That is the whole point of this screen."
                  : "Nothing here."
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[64rem] border-collapse">
              <thead>
                <tr className="border-b border-rule">
                  {[
                    ["Customer", "pl-4 pr-3 text-left"],
                    ["Material", "px-3 text-left"],
                    ["Last activity", "px-3 text-left"],
                    ["Value", "px-3 text-right"],
                    ["Waiting", "px-3 text-right"],
                    ["Next step", "pl-4 pr-4 text-left"],
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
                {rows.map((row) => (
                  <Row
                    key={row.quotation_id}
                    row={row}
                    selected={row.quotation_id === openId}
                    onOpen={() => setOpenId(row.quotation_id)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {openRow && (
        <ChaseDrawer row={openRow} onClose={() => setOpenId(null)} onActed={onActed} />
      )}
      {showRules && <RulesModal onClose={() => setShowRules(false)} />}
    </div>
  );
}
