import { useState } from "react";

import { useApi } from "../api/client";
import type {
  DeskCustomer,
  DeskProduct,
  DeskReport,
  PeriodChoice,
  ReportResult,
} from "../api/types";
import type { LineSeries } from "../components/charts";
import { DonutChart, MultiLineChart } from "../components/charts";
import {
  Button,
  ErrorNote,
  inr,
  inrShort,
  Loading,
  Scroller,
  Select,
  Sparkline,
} from "../components/ui";
import { useAuth } from "../lib/auth";

/* ---------------------------------------------------------------------------
   The period report.

   This is a *document*, not a dashboard. The distinction is not cosmetic: a
   dashboard answers "what is happening now" and is read at a glance, while a
   report answers "what happened over this period, and does it reconcile" and
   is read line by line, printed, signed, and sent to somebody. So the page is
   set as a sheet - letterhead, numbered statements, ruled totals, footer - and
   every statement is arranged so its lines add up to the total beneath them.

   Four statements, in the order a trader would work through them:

     1. Enquiry and quotation - how much work came in, how much we answered.
     2. Sales and realisation - what we sold, and at what rate.
     3. Trading and profit    - what it cost, and what we kept.
     4. Stock                 - opening, receipts, issues, closing.

   Each line is a subset or a component of the one below it, so the gaps are
   themselves information: mail that was not an enquiry, enquiries never quoted,
   quotations never sent. A list of totals would hide exactly those gaps.

   Figures come from stored rows at the rules in force at the time, so a
   printed report does not change when somebody edits a percentage tomorrow.
   --------------------------------------------------------------------------- */

const DETAIL_REPORTS = [
  { value: "win-loss", label: "Quotation register" },
  { value: "margin", label: "Margin by line" },
  { value: "stock-ageing", label: "Stock ageing" },
  { value: "customers", label: "Customer ledger" },
  { value: "products", label: "Product ledger" },
];

const FALLBACK_PERIODS: PeriodChoice[] = [
  { key: "this-month", label: "This month", range: "" },
  { key: "last-month", label: "Last month", range: "" },
];

const SALES_LINES: LineSeries[] = [
  { key: "quoted", label: "Quoted", colour: "#94A3B8", dashed: true },
  { key: "sold", label: "Sold", colour: "#2563EB" },
];

const AGEING_TONE: Record<string, string> = {
  "0-30 days": "text-brand",
  "31-60 days": "text-brand-soft",
  "61-90 days": "text-attention",
  "Over 90 days": "text-danger",
};

/** Deadstock first, so the ring opens on the slice that matters. */
const AGEING_ORDER = <T extends { label: string; value: number }>(buckets: T[]): T[] => [
  ...buckets.filter((b) => b.label === "Over 90 days" && b.value > 0),
  ...buckets.filter((b) => b.label !== "Over 90 days" && b.value > 0),
];

function mt(value: number): string {
  return `${value.toLocaleString("en-IN", { maximumFractionDigits: 3 })}`;
}

function pct(value: number | null): string {
  return value === null ? "—" : `${value.toFixed(1)}%`;
}

/* --- Document furniture ---------------------------------------------------- */

/** One numbered statement, as a card.
 *
 *  The number is not decoration: these are meant to be referred to ("see
 *  statement 3") the way a set of accounts is. The card gives each statement a
 *  boundary so three can sit side by side and still read as three separate
 *  documents rather than one long column of figures.
 *
 *  Statements carry no chart of their own. A figure exhibit squeezed into a
 *  third of the width becomes decoration; the one chart that earns its place
 *  runs full width beneath the row, where it can actually be read. */
function Statement({
  index,
  title,
  question,
  children,
}: {
  index: number;
  title: string;
  question: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex min-w-0 break-inside-avoid flex-col rounded-card border border-rule bg-surface shadow-card">
      <header className="border-b border-rule px-4 py-3">
        <h2 className="flex items-baseline gap-2 text-sm font-bold text-ink">
          <span className="tabular text-ink-faint">{index}.</span>
          {title}
        </h2>
        <p className="mt-0.5 text-xs italic text-ink-faint">{question}</p>
      </header>
      {/* A column, so the note can be pushed to the bottom: with the cards
          stretched to a common height, notes left in the flow would float at
          three different heights and undo the alignment. */}
      <div className="flex flex-1 flex-col px-4 py-3">{children}</div>
    </section>
  );
}

/** A figure line: label on the left, value on the right, dot leaders between.
 *
 *  Leaders are what let the eye run from a label to a number twenty
 *  centimetres away without losing the row - which is why every printed
 *  statement has used them for a century, and why a plain two-column flexbox
 *  reads worse the wider the page gets. */
function Line({
  label,
  value,
  unit,
  note,
  indent = false,
  muted = false,
  strong = false,
  rule = false,
}: {
  label: string;
  value: string;
  unit?: string;
  note?: string;
  indent?: boolean;
  muted?: boolean;
  strong?: boolean;
  rule?: boolean;
}) {
  return (
    <div
      className={`flex items-baseline gap-1.5 py-1 ${rule ? "border-t border-ink" : ""} ${
        indent ? "pl-5" : ""
      }`}
    >
      <span
        className={`shrink-0 text-[13px] ${strong ? "font-semibold text-ink" : ""} ${
          muted ? "text-ink-faint" : "text-ink-soft"
        }`}
      >
        {label}
      </span>
      {note && <span className="shrink-0 text-[11px] italic text-ink-faint">{note}</span>}
      <span
        aria-hidden="true"
        className={`min-w-4 flex-1 translate-y-[-3px] border-b border-dotted ${
          muted ? "border-rule" : "border-rule-firm"
        }`}
      />
      <span
        className={`tabular shrink-0 text-[13px] ${
          strong ? "font-bold text-ink" : muted ? "text-ink-faint" : "font-medium text-ink"
        }`}
      >
        {value}
      </span>
      {unit && (
        <span className="w-8 shrink-0 text-left text-[11px] text-ink-faint">{unit}</span>
      )}
    </div>
  );
}

/** A note under a statement — the sentence an accountant would write in the
 *  margin, explaining what the figures above do and do not include. */
function Note({ children }: { children: React.ReactNode }) {
  // `mt-auto` seats the note on the floor of its card, so the notes of three
  // statements of different lengths still line up with each other.
  return (
    <p className="mt-auto border-l-2 border-rule pl-2.5 pt-3 text-[11px] leading-relaxed text-ink-faint">
      {children}
    </p>
  );
}

/** A contents card: one per statement, at the head of the report.
 *
 *  A reader who has been handed four pages wants to know, before reading any
 *  of it, whether this was a good period. These are that answer - and they
 *  double as the report's contents page, each card naming the statement it
 *  summarises. Deliberately quiet: a card here must never out-shout the
 *  statement it points at. */
function SummaryCard({
  index,
  title,
  value,
  hint,
  spark,
  tone = "text-ink",
}: {
  index: number;
  title: string;
  value: string;
  hint: string;
  spark?: number[];
  tone?: string;
}) {
  return (
    <div className="flex min-w-0 flex-col gap-2 border border-rule bg-surface px-3.5 py-3">
      <div className="flex items-baseline gap-1.5">
        <span className="tabular text-[11px] font-semibold text-ink-faint">{index}</span>
        <span className="truncate text-[11px] font-medium uppercase tracking-wider text-ink-soft">
          {title}
        </span>
      </div>
      <div className="flex items-end justify-between gap-2">
        <p className={`tabular truncate text-xl font-bold leading-none ${tone}`}>{value}</p>
        {spark && spark.length > 1 && (
          <span className="shrink-0 text-ink-faint">
            <Sparkline points={spark} />
          </span>
        )}
      </div>
      <p className="truncate text-[11px] text-ink-faint">{hint}</p>
    </div>
  );
}

/* --- Schedules (the tables at the back) ------------------------------------ */

const TH = "px-2 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-ink-soft";
const TD = "tabular px-2 py-1.5 text-[12px]";

function Schedule({
  letter,
  title,
  note,
  children,
  minWidth = "26rem",
}: {
  letter: string;
  title: string;
  note?: string;
  children: React.ReactNode;
  minWidth?: string;
}) {
  return (
    <div className="break-inside-avoid">
      <h3 className="mb-1.5 flex items-baseline gap-2 text-xs font-bold text-ink">
        <span className="text-ink-faint">Schedule {letter}</span>
        {title}
        {note && <span className="font-normal italic text-ink-faint">· {note}</span>}
      </h3>
      <Scroller>
        <table className="w-full border-t border-ink text-sm" style={{ minWidth }}>
          {children}
        </table>
      </Scroller>
    </div>
  );
}

function CustomerSchedule({ rows }: { rows: DeskCustomer[] }) {
  return (
    <Schedule letter="A" title="Customers" note="ranked by revenue" minWidth="30rem">
      <thead>
        <tr className="border-b border-rule-firm">
          <th className={`${TH} text-left`}>Customer</th>
          <th className={`${TH} text-right`}>Quoted</th>
          <th className={`${TH} text-right`}>Revenue</th>
          <th className={`${TH} text-right`}>Profit</th>
          <th className={`${TH} text-right`}>Win rate</th>
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 ? (
          <tr>
            <td colSpan={5} className="px-2 py-2 text-[12px] italic text-ink-faint">
              No customer activity in this period.
            </td>
          </tr>
        ) : (
          rows.map((row) => (
            <tr key={row.customer} className="border-b border-rule">
              <td className="max-w-44 truncate px-2 py-1.5 text-[12px] text-ink">
                {row.customer}
              </td>
              <td className={`${TD} text-right text-ink-soft`}>{inrShort(row.quoted_value)}</td>
              <td className={`${TD} text-right font-medium text-ink`}>
                {row.revenue ? inrShort(row.revenue) : "—"}
              </td>
              <td className={`${TD} text-right font-medium text-ink`}>
                {row.profit ? inrShort(row.profit) : "—"}
              </td>
              <td className={`${TD} text-right text-ink-soft`}>{pct(row.win_rate)}</td>
            </tr>
          ))
        )}
      </tbody>
    </Schedule>
  );
}

function ProductSchedule({ rows }: { rows: DeskProduct[] }) {
  return (
    <Schedule letter="B" title="Products" note="tonnage and spread" minWidth="30rem">
      <thead>
        <tr className="border-b border-rule-firm">
          <th className={`${TH} text-left`}>Product</th>
          <th className={`${TH} text-right`}>Quoted MT</th>
          <th className={`${TH} text-right`}>Sold MT</th>
          <th className={`${TH} text-right`}>Profit</th>
          <th className={`${TH} text-right`}>₹ / MT</th>
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 ? (
          <tr>
            <td colSpan={5} className="px-2 py-2 text-[12px] italic text-ink-faint">
              No products quoted in this period.
            </td>
          </tr>
        ) : (
          rows.map((row) => (
            <tr key={row.product} className="border-b border-rule">
              <td className="max-w-44 truncate px-2 py-1.5 text-[12px] text-ink">
                {row.product}
              </td>
              <td className={`${TD} text-right text-ink-soft`}>{mt(row.tonnes_quoted)}</td>
              <td className={`${TD} text-right font-medium text-ink`}>{mt(row.tonnes_won)}</td>
              <td className={`${TD} text-right font-medium text-ink`}>
                {row.profit ? inrShort(row.profit) : "—"}
              </td>
              <td className={`${TD} text-right text-ink-soft`}>
                {row.tonnes_won ? inr(row.profit_per_mt) : "—"}
              </td>
            </tr>
          ))
        )}
      </tbody>
    </Schedule>
  );
}

/* --- Schedule E: the register behind any headline -------------------------- */

function humanise(key: string): string {
  return key
    .replace(/_inr$/, " (₹)")
    .replace(/_pct$/, " %")
    .replace(/_mt$/, " MT")
    .replace(/_/g, " ")
    .replace(/^./, (c) => c.toUpperCase());
}

function cell(key: string, value: string | number): string {
  if (typeof value === "number") return String(value);
  if (key.endsWith("_inr")) return inrShort(value);
  if (key.endsWith("_pct") && value !== "") return `${value}%`;
  return value;
}

function Register({ period }: { period: string }) {
  const [name, setName] = useState("win-loss");
  const { data, loading, error } = useApi<ReportResult>(`/reports/${name}?period=${period}`);
  const columns = data?.rows.length ? Object.keys(data.rows[0]) : [];

  return (
    <div className="break-inside-avoid">
      <div className="mb-1.5 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="flex items-baseline gap-2 text-xs font-bold text-ink">
          <span className="text-ink-faint">Schedule E</span>
          {data?.title ?? "Register"}
          <span className="font-normal italic text-ink-faint">· the working</span>
        </h3>
        <div className="flex items-center gap-2 print:hidden">
          <Select value={name} onChange={setName} options={DETAIL_REPORTS} />
          <a href={`/api/v1/reports/${name}?period=${period}&fmt=csv`} download>
            <Button compact>Export CSV</Button>
          </a>
        </div>
      </div>

      {error && <ErrorNote message={error} />}
      {loading && !data && <Loading label="Building the register" />}

      {data && (
        <>
          {Object.keys(data.totals).length > 0 && (
            <div className="mb-2 flex flex-wrap gap-x-6 gap-y-1 border-y border-rule bg-sunk px-2 py-1.5">
              {Object.entries(data.totals)
                .filter(([, v]) => typeof v !== "object")
                .map(([key, value]) => (
                  <span key={key} className="text-[11px] text-ink-soft">
                    {humanise(key)}{" "}
                    <span className="tabular font-semibold text-ink">
                      {value === null || value === "" ? "—" : cell(key, value as string)}
                    </span>
                  </span>
                ))}
            </div>
          )}

          {data.rows.length === 0 ? (
            <p className="border-t border-ink px-2 py-2 text-[12px] italic text-ink-faint">
              Nothing in this period.
            </p>
          ) : (
            <Scroller>
              <table className="w-full min-w-[40rem] border-t border-ink text-sm">
                <thead>
                  <tr className="border-b border-rule-firm">
                    {columns.map((c) => (
                      <th
                        key={c}
                        className={`${TH} ${
                          /_inr$|_pct$|_mt$/.test(c) ? "text-right" : "text-left"
                        }`}
                      >
                        {humanise(c)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((row, i) => (
                    <tr key={i} className="border-b border-rule">
                      {columns.map((c) => (
                        <td
                          key={c}
                          className={`${TD} ${
                            /_inr$|_pct$|_mt$/.test(c)
                              ? "text-right text-ink"
                              : "text-ink-soft"
                          }`}
                        >
                          {cell(c, row[c])}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </Scroller>
          )}
        </>
      )}
    </div>
  );
}

/* --- Page ------------------------------------------------------------------ */

export default function Reports() {
  const [period, setPeriod] = useState("this-month");
  const { organisation } = useAuth();

  const { data, loading, error } = useApi<DeskReport>(`/reports/desk?period=${period}`);
  const choices = useApi<{ choices: PeriodChoice[] }>("/reports/periods");

  if (loading && !data) return <Loading label="Preparing the report" />;
  if (error)
    return (
      <div className="p-5">
        <ErrorNote message={error} />
      </div>
    );
  if (!data) return null;

  const periodOptions = (choices.data?.choices ?? FALLBACK_PERIODS).map((c) => ({
    value: c.key,
    label: c.label,
  }));

  const { won, quoted, open_book: open, enquiries: enq, stock, stock_movement: sm } = data;
  const generated = new Date().toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });

  return (
    <div className="flex flex-col gap-4 p-4 sm:gap-5 sm:p-5">
      {/* The controls are chrome, not part of the report, so they disappear
          when it is printed or saved to PDF. */}
      <div className="flex flex-wrap items-center justify-between gap-3 print:hidden">
        <Select value={period} onChange={setPeriod} options={periodOptions} />
        {/* Three ways out, for three readers: an accountant who wants to sum a
            column, a partner who wants a file to keep, and anyone who just
            wants it on paper. PDF goes through the browser's own print-to-PDF
            rather than a server-side renderer - it produces the same pages the
            print stylesheet already lays out, without adding a dependency
            whose output would then have to be kept in step with this page. */}
        <div className="flex flex-wrap items-center gap-2">
          <a href={`/api/v1/reports/pack?period=${period}`} download>
            <Button>Excel</Button>
          </a>
          <a href={`/api/v1/reports/document?period=${period}`} download>
            <Button>HTML</Button>
          </a>
          <Button variant="primary" onClick={() => window.print()}>
            Download PDF
          </Button>
        </div>
      </div>

      <div data-report className="flex flex-col gap-4 sm:gap-5">
        {/* --- Letterhead ------------------------------------------------- */}
        <header className="border-b-2 border-ink pb-3">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-lg font-bold tracking-tight text-ink">
                {organisation?.name ?? "Trading desk"}
              </p>
              <h1 className="mt-0.5 text-sm font-semibold uppercase tracking-[0.14em] text-ink-soft">
                Trading period report
              </h1>
            </div>
            <dl className="shrink-0 text-right text-[11px] leading-relaxed">
              <div className="flex justify-end gap-2">
                <dt className="text-ink-faint">Period</dt>
                <dd className="font-semibold text-ink">{data.period_label}</dd>
              </div>
              <div className="flex justify-end gap-2">
                <dt className="text-ink-faint">Covering</dt>
                <dd className="tabular text-ink-soft">{data.period_range}</dd>
              </div>
              <div className="flex justify-end gap-2">
                <dt className="text-ink-faint">Compared with</dt>
                <dd className="tabular text-ink-soft">{data.previous_label}</dd>
              </div>
              <div className="flex justify-end gap-2">
                <dt className="text-ink-faint">Prepared</dt>
                <dd className="tabular text-ink-soft">{generated}</dd>
              </div>
            </dl>
          </div>
        </header>

        {/* Contents: one card per statement, so a reader knows before page two
            whether this was a good period. */}
        <div data-keep-columns className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
          <SummaryCard
            index={1}
            title="Enquiry"
            value={String(enq.identified)}
            hint={`${enq.raised} quoted · ${enq.sent} sent`}
            spark={data.trend.map((p) => p.quoted)}
          />
          <SummaryCard
            index={2}
            title="Sales"
            value={inrShort(won.revenue)}
            hint={`${mt(won.tonnes)} MT over ${won.deals} orders`}
            spark={data.trend.map((p) => p.revenue)}
          />
          <SummaryCard
            index={3}
            title="Gross profit"
            value={inrShort(won.profit)}
            hint={`${won.margin_pct.toFixed(1)}% margin`}
            tone={won.profit > 0 ? "text-settled" : "text-ink"}
            spark={data.trend.map((p) => p.profit)}
          />
          <SummaryCard
            index={4}
            title="Stock"
            value={inrShort(stock.total_value)}
            hint={`${stock.deadstock_pct}% over 90 days`}
            tone={stock.deadstock_pct > 20 ? "text-danger" : "text-ink"}
          />
        </div>

        <div className="mt-6 flex flex-col gap-6">
          {/* Statements 1-3 read across, because a trader compares them:
              work in, what it sold for, what was kept. Stock is a different
              question - what the floor holds today - so it stands apart. */}
          {/* No `items-start`: three cards of different lengths ending at three
              different heights read as unfinished. Stretching them to a common
              height is what makes them a set - the body is `flex-1`, so the
              slack falls below the last figure instead of stretching the rows. */}
          <div className="grid gap-4 xl:grid-cols-3">
          {/* --- 1. Enquiry and quotation --------------------------------- */}
          <Statement
            index={1}
            title="Enquiry and quotation"
            question="How much work came in, and how much of it did we answer?"
          >
            <Line label="Mail received" value={String(enq.received)} unit="no." />
            <Line
              label="Not an enquiry"
              value={`(${enq.not_enquiries})`}
              unit="no."
              indent
              muted
            />
            <Line label="Enquiries identified" value={String(enq.identified)} unit="no." rule />
            <Line label="Not quoted" value={`(${enq.not_raised})`} unit="no." indent muted />
            <Line label="Quotations raised" value={String(enq.raised)} unit="no." rule />
            <Line label="Not yet sent" value={`(${enq.not_sent})`} unit="no." indent muted />
            <Line label="Quotations sent" value={String(enq.sent)} unit="no." strong rule />
            <div className="mt-2.5 border-t border-rule pt-1.5">
              <Line label="Accepted" value={String(enq.won)} unit="no." />
              <Line label="Declined" value={String(enq.lost)} unit="no." />
              <Line label="Awaiting reply" value={String(enq.awaiting)} unit="no." muted />
              <Line label="Win rate on decided" value={pct(enq.win_rate)} strong rule />
            </div>
            <Note>
              Each line is a subset of the one above it. A quotation counts in the period it
              was raised, not the period it was answered, so an enquiry from last month that
              closed this month is reported against last month.
            </Note>
          </Statement>

          {/* --- 2. Sales and realisation --------------------------------- */}
          <Statement
            index={2}
            title="Sales and realisation"
            question="What did we sell, and at what rate?"
          >
            <Line label="Tonnage quoted" value={mt(quoted.tonnes)} unit="MT" />
            <Line label="Tonnage sold" value={mt(won.tonnes)} unit="MT" strong rule />
            <div className="mt-2.5">
              <Line label="Value quoted" value={inr(quoted.revenue)} />
              <Line label="Value sold" value={inr(won.revenue)} strong rule />
              <Line
                label="Average realisation"
                value={won.tonnes ? inr(won.revenue / won.tonnes) : "—"}
                note="per MT"
              />
              <Line
                label="Orders"
                value={String(won.deals)}
                unit="no."
                muted
              />
            </div>
            <div className="mt-2.5 border-t border-rule pt-1.5">
              <Line label="Still with customers" value={inr(open.revenue)} muted />
              <Line
                label="Conversion on value"
                value={
                  quoted.revenue ? `${((won.revenue / quoted.revenue) * 100).toFixed(1)}%` : "—"
                }
                muted
              />
            </div>
            <Note>
              Sold means a customer accepted the quotation. Value is counted at the rate that
              was quoted, and does not include tax or freight billed separately.
            </Note>
          </Statement>

          {/* --- 3. Trading and profit ------------------------------------ */}
          <Statement
            index={3}
            title="Trading and profit"
            question="What did it cost, and what did we keep?"
          >
            <Line label="Revenue from sales" value={inr(won.revenue)} />
            <Line label="Less: cost of goods sold" value={`(${inr(won.cost)})`} indent />
            <Line label="Gross profit" value={inr(won.profit)} strong rule />
            <div className="mt-2.5">
              <Line label="Gross margin" value={`${won.margin_pct.toFixed(2)}%`} />
              <Line
                label="Profit per tonne"
                value={won.tonnes ? inr(won.profit_per_mt) : "—"}
                note="per MT"
              />
              <Line
                label="Gross profit, previous period"
                value={inr(data.won_previous.profit)}
                muted
              />
              <Line
                label="Movement"
                value={
                  data.won_previous.profit
                    ? `${(
                        ((won.profit - data.won_previous.profit) /
                          Math.abs(data.won_previous.profit)) *
                        100
                      ).toFixed(1)}%`
                    : "—"
                }
                muted
              />
            </div>
            {data.lost_reasons.length > 0 && (
              <div className="mt-3 border-t border-rule pt-2">
                <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-ink-soft">
                  Business declined, by reason
                </p>
                {data.lost_reasons.map((r) => (
                  <Line
                    key={r.reason}
                    label={r.label}
                    value={inr(r.value)}
                    note={`${r.count} quotation${r.count === 1 ? "" : "s"}`}
                  />
                ))}
              </div>
            )}
            <Note>
              Cost of goods is the landed cost recorded against each line when it was priced,
              under the rules then in force. Lines priced without a recorded cost are excluded
              from both figures rather than being treated as pure profit.
            </Note>
          </Statement>
          </div>

          {/* The one chart that earns full width. Quoted against sold over the
              period answers the question the three cards raise between them -
              did the work coming in turn into money? - and needs the measure to
              show a shape rather than a squiggle. */}
          <section className="rounded-card border border-rule bg-surface shadow-card">
            <header className="flex flex-wrap items-baseline justify-between gap-2 border-b border-rule px-4 py-3">
              <div>
                <h2 className="text-sm font-bold text-ink">Quoted against sold</h2>
                <p className="mt-0.5 text-xs italic text-ink-faint">
                  Did the work coming in turn into money?
                </p>
              </div>
              <p className="text-xs text-ink-faint">
                {data.period_range} · bucketed by {data.grain}
              </p>
            </header>
            <div className="px-4 py-4">
              <MultiLineChart
                points={data.trend.map((p) => ({
                  label: p.label,
                  values: { quoted: p.quoted, sold: p.revenue },
                }))}
                series={SALES_LINES}
                format={inrShort}
                height={220}
                emptyMessage={`${data.period_label} holds a single bucket — a trend needs two.`}
              />
            </div>
          </section>

          {/* --- 4. Stock -------------------------------------------------- */}
          <Statement
            index={4}
            title="Stock"
            question="What did the floor hold, and what moved?"
          >
            {/* Two columns, because a dot leader running the width of a
                27-inch monitor is exactly the row the eye loses. */}
            <div className="grid items-start gap-6 lg:grid-cols-[1.4fr_1fr]">
            <div className="min-w-0">
            <Line label="Opening stock" value={mt(sm.opening_mt)} unit="MT" />
            <Line
              label="Add: receipts"
              value={mt(sm.receipts_mt)}
              unit="MT"
              indent
              note={`${sm.receipt_count} movement${sm.receipt_count === 1 ? "" : "s"}`}
            />
            <Line
              label="Less: issues"
              value={`(${mt(sm.issues_mt)})`}
              unit="MT"
              indent
              note={`${sm.issue_count} movement${sm.issue_count === 1 ? "" : "s"}`}
            />
            <Line label="Closing stock" value={mt(sm.closing_mt)} unit="MT" strong rule />

            <div className="mt-2.5">
              <Line label="Closing stock at landed cost" value={inr(stock.total_value)} />
              <Line
                label="Of which ageing over 90 days"
                value={inr(stock.deadstock_value)}
                note={`${stock.deadstock_pct}% · ${stock.deadstock_lots} lots`}
                indent
              />
            </div>
            <Note>
              Closing stock is taken from the current stock sheet; opening is derived backwards
              from it using the movement ledger, so the statement always reconciles against
              what the floor actually holds. Reservations and blocks are holds, not movements
              of ownership, and are excluded.
            </Note>

            </div>

            {/* The floor is a whole and the question asked of it is a share. */}
            <div className="min-w-0 lg:border-l lg:border-rule lg:pl-6">
              <DonutChart
                data={AGEING_ORDER(stock.buckets).map((b) => ({
                  label: b.label,
                  value: Math.round(b.value),
                }))}
                tones={AGEING_ORDER(stock.buckets).map(
                  (b) => AGEING_TONE[b.label] ?? "text-brand",
                )}
                format={inrShort}
                size={188}
                centerValue={inrShort(stock.deadstock_value)}
                centerLabel={`over 90 days · ${stock.deadstock_pct}%`}
              />
            </div>
            </div>
          </Statement>

          {/* --- Schedules ------------------------------------------------- */}
          <section className="break-before-page border-t-2 border-ink pt-3">
            <h2 className="mb-3 text-sm font-bold text-ink">Schedules</h2>
            <div className="flex flex-col gap-5">
              {/* Schedules run the full measure. Two five-column tables side by
                  side inside a 60rem sheet clip their right-hand columns, and a
                  schedule whose last column is cut off is not a schedule. */}
              <CustomerSchedule rows={data.customers} />
              <ProductSchedule rows={data.products} />

              {stock.oldest.length > 0 && (
                <Schedule letter="C" title="Oldest lots" note="longest standing first" minWidth="28rem">
                  <thead>
                    <tr className="border-b border-rule-firm">
                      <th className={`${TH} text-left`}>Specification</th>
                      <th className={`${TH} text-left`}>Location</th>
                      <th className={`${TH} text-right`}>Age</th>
                      <th className={`${TH} text-right`}>Balance MT</th>
                      <th className={`${TH} text-right`}>Value</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stock.oldest.slice(0, 8).map((lot) => (
                      <tr key={`${lot.spec}-${lot.ageing_days}`} className="border-b border-rule">
                        <td className="max-w-56 truncate px-2 py-1.5 text-[12px] text-ink">
                          {lot.spec}
                        </td>
                        <td className="px-2 py-1.5 text-[12px] text-ink-soft">
                          {lot.location || "—"}
                        </td>
                        <td className={`${TD} text-right text-ink`}>{lot.ageing_days}d</td>
                        <td className={`${TD} text-right text-ink-soft`}>{mt(lot.tonnes)}</td>
                        <td className={`${TD} text-right font-medium text-ink`}>
                          {inrShort(lot.value)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </Schedule>
              )}

              {data.quiet_customers.length > 0 && (
                <Schedule letter="D" title="Customers gone quiet" note="no enquiry in 60 days">
                  <thead>
                    <tr className="border-b border-rule-firm">
                      <th className={`${TH} text-left`}>Customer</th>
                      <th className={`${TH} text-right`}>Last seen</th>
                      <th className={`${TH} text-right`}>Orders</th>
                      <th className={`${TH} text-right`}>Lifetime revenue</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.quiet_customers.map((c) => (
                      <tr key={c.customer} className="border-b border-rule">
                        <td className="max-w-44 truncate px-2 py-1.5 text-[12px] text-ink">
                          {c.customer}
                        </td>
                        <td className={`${TD} text-right text-ink-soft`}>{c.days_quiet}d ago</td>
                        <td className={`${TD} text-right text-ink-soft`}>{c.orders}</td>
                        <td className={`${TD} text-right font-medium text-ink`}>
                          {inrShort(c.lifetime_revenue)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </Schedule>
              )}

              <Register period={period} />
            </div>
          </section>
        </div>

        {/* --- Footer ------------------------------------------------------ */}
        <footer className="mt-7 border-t border-rule pt-3 text-[10px] leading-relaxed text-ink-faint">
          <p>
            Prepared from stored records for {data.period_range}. Figures are counted at the
            pricing rules in force when each quotation was raised, so this report does not
            change if the rules are edited later.
          </p>
          <p className="mt-1">
            {organisation?.name ?? "Trading desk"} · {data.period_label} · Prepared {generated}
          </p>
        </footer>
      </div>
    </div>
  );
}
