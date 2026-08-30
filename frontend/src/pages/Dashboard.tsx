import { useState } from "react";
import { Link } from "react-router-dom";

import { api, useApi } from "../api/client";
import type {
  DashboardMetrics,
  FunnelReport,
  PipelineReport,
  TrendPoint,
  Trends,
} from "../api/types";
import { AreaChart, ColumnChart, FunnelChart, HBarChart } from "../components/charts";
import {
  Button,
  Card,
  Kpi,
  Empty,
  ErrorNote,
  inrShort,
  Loading,
  num,
  Select,
} from "../components/ui";

/* ---------------------------------------------------------------------------
   The morning screen.

   Ordered by what a trader needs to decide, not by what is easy to query:
   what needs me now, how is the desk doing against last period, where is
   work getting stuck, and what just happened.
   --------------------------------------------------------------------------- */

const PERIODS = [
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last quarter" },
];

const METRIC_SERIES = [
  { key: "quotations", label: "Quotations" },
  { key: "enquiries", label: "Enquiries" },
  { key: "value", label: "Quoted value" },
  { key: "sent", label: "Sent" },
] as const;

type MetricKey = (typeof METRIC_SERIES)[number]["key"];

const VIEWS = [
  { key: "tonnes", label: "Volume" },
  { key: "value", label: "Value" },
  { key: "count", label: "Number" },
] as const;

type ViewKey = (typeof VIEWS)[number]["key"];

/** An enquiry has a requested tonnage (what the customer asked for, read off
 *  the line items as extracted) but no value — pricing hasn't run yet, so
 *  ₹0 there is honest, not a bug. In Value view this stage falls back to a
 *  count instead of showing a ₹0 that reads like every stage after it. */
const ENQUIRIES_STAGE = "Enquiries received";

/** One funnel stage's raw figures, reduced to whichever measure the view toggle wants. */
function pick(
  view: ViewKey,
  stage: { stage?: string; count: number; tonnes: number; value: number },
): number {
  if (view === "value" && stage.stage === ENQUIRIES_STAGE) return stage.count;
  return stage[view];
}

function formatView(
  view: ViewKey,
  stage: { stage?: string; count: number; tonnes: number; value: number },
): string {
  const v = pick(view, stage);
  // Labelled explicitly rather than left as a bare number: a "7" sitting next
  // to "₹89.6k" reads as a broken figure in the same unit, when it is
  // actually a count of emails in a different unit entirely.
  if (view === "value" && stage.stage === ENQUIRIES_STAGE) {
    return `${v} enquir${v === 1 ? "y" : "ies"}`;
  }
  if (view === "value") return inrShort(v);
  if (view === "tonnes") return v > 0 ? `${num(v)} MT` : "—";
  return String(v);
}

export default function Dashboard() {
  const [days, setDays] = useState("30");
  const [metric, setMetric] = useState<MetricKey>("quotations");
  const [view, setView] = useState<ViewKey>("tonnes");
  const [running, setRunning] = useState(false);

  const metrics = useApi<DashboardMetrics>("/dashboard/metrics", 60_000);
  const pipeline = useApi<PipelineReport>("/dashboard/pipeline", 60_000);
  const p = pipeline.data;
  const trends = useApi<Trends>(`/dashboard/trends?days=${days}`, 120_000);
  const funnel = useApi<FunnelReport>(`/reports/funnel?days=${days}`);

  if (metrics.loading && !metrics.data) return <Loading label="Loading the desk" />;
  if (metrics.error) return <div className="p-6"><ErrorNote message={metrics.error} /></div>;

  const m = metrics.data;
  const t = trends.data;

  const series = (t?.series ?? []).map((p) => ({
    label: new Date(p.day).toLocaleDateString("en-IN", { day: "2-digit", month: "short" }),
    value: metric === "value" ? Number(p.value) : p[metric],
  }));

  // Weekly buckets make the this-vs-last comparison legible; 30 daily pairs
  // would be a picket fence nobody can read.
  const weekly = bucketByWeek(t?.series ?? [], metric);

  const needsAttention =
    (m?.quotations.pending_approval ?? 0) + (m?.quotations.needs_information ?? 0);

  const salesStages = funnel.data?.stages ?? [];

  // The three numbers that answer "is the desk winning": how many enquiries
  // came in, how many got a quote, how many turned into an order — each a
  // stage the funnel already carries, just picked out and given a rate.
  const winTiles = ["Enquiries received", "Quotations provided", "Orders received"]
    .map((label) => salesStages.find((s) => s.stage === label))
    .filter((s): s is (typeof salesStages)[number] => !!s)
    .map((s, i, arr) => ({
      label: s.stage,
      stage: s,
      rate: i > 0 && arr[i - 1].count > 0 ? `${Math.round((s.count / arr[i - 1].count) * 100)}%` : "—",
    }));

  async function runPipeline() {
    setRunning(true);
    try {
      await api.post("/pipeline/run");
      setTimeout(() => {
        metrics.reload();
        trends.reload();
      }, 2500);
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="flex flex-col gap-4 p-4 sm:gap-5 sm:p-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-0.5 rounded-lg bg-sunk p-0.5">
          {VIEWS.map((v) => (
            <button
              key={v.key}
              type="button"
              onClick={() => setView(v.key)}
              className={`w-20 rounded-md px-2.5 py-2 text-sm font-medium transition-colors ${
                view === v.key
                  ? "bg-surface text-brand-soft-ink shadow-card"
                  : "text-ink-faint hover:text-ink"
              }`}
            >
              {v.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <Select value={days} onChange={setDays} options={PERIODS} />
          <Button variant="primary" onClick={runPipeline} disabled={running}>
            {running ? "Fetching…" : "Fetch & process email"}
          </Button>
        </div>
      </header>

      {needsAttention > 0 && (
        <Link
          to="/quotations"
          className="flex items-center justify-between gap-3 rounded-card border border-attention/40 bg-attention-wash px-4 py-3 transition-colors hover:border-attention"
        >
          <div>
            <p className="text-sm font-semibold text-attention-ink">
              {needsAttention} quotation{needsAttention === 1 ? "" : "s"} waiting on you
            </p>
            <p className="text-xs text-attention-ink/80">
              {m?.quotations.pending_approval ?? 0} ready to review ·{" "}
              {m?.quotations.needs_information ?? 0} need information
            </p>
          </div>
          <span className="text-sm font-medium text-attention-ink">Review →</span>
        </Link>
      )}

      {/* --- What the desk has to act on --------------------------------
          Three figures that each mean a job: steel to buy, money arriving,
          money late. Shown only when non-zero - a row of zeroes trains a
          trader to stop reading the row. */}
      {(!!p?.to_buy_mt || !!p?.due_this_week || !!p?.overdue_count) && (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3 sm:gap-3">
          {!!p?.to_buy_mt && (
            <Kpi
              label="To buy for orders won"
              value={`${p.to_buy_mt.toFixed(2)} MT`}
              hint="not on the floor, already sold"
              tone="warn"
            />
          )}
          {!!p?.due_this_week && (
            <Kpi
              label="Payment due this week"
              value={inrShort(p.due_this_week)}
              hint="by the agreed terms"
            />
          )}
          {!!p?.overdue_count && (
            <Kpi
              label="Overdue"
              value={inrShort(p.overdue_value)}
              hint={`${p.overdue_count} invoice${p.overdue_count === 1 ? "" : "s"} past terms`}
              tone="warn"
            />
          )}
        </div>
      )}

      {/* --- What has to ship, and what has to be collected -------------
          The two tables a trader acts from. Rendered only when they have
          rows: an empty table is a promise that something will appear there,
          and a dashboard full of empty promises stops being read. */}
      {(p?.deliveries.length ?? 0) > 0 && (
        <Card
          title="Deliveries pending"
          subtitle="Won, not yet shipped — soonest first"
          padded={false}
        >
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-rule bg-sunk text-left text-xs uppercase tracking-wide text-ink-faint">
                <tr>
                  <th className="px-4 py-2 font-medium">Customer</th>
                  <th className="px-4 py-2 font-medium">Material</th>
                  <th className="px-4 py-2 font-medium">Wanted by</th>
                  <th className="px-4 py-2 text-right font-medium">Ordered (MT)</th>
                  <th className="px-4 py-2 text-right font-medium">In stock (MT)</th>
                  <th className="px-4 py-2 text-right font-medium">To buy (MT)</th>
                  <th className="px-4 py-2 text-right font-medium">Value</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-sunk">
                {p!.deliveries.map((d) => (
                  <tr key={d.quotation_id} className="hover:bg-sunk">
                    <td className="px-4 py-2">
                      <Link to={`/quotations/${d.quotation_id}`} className="text-ink hover:text-brand">
                        {d.customer}
                      </Link>
                      <span className="ml-2 text-xs text-ink-faint">{d.quotation_number}</span>
                    </td>
                    <td className="px-4 py-2 text-ink-soft">{d.material}</td>
                    <td className="px-4 py-2 text-ink-soft">{d.wanted_by ?? "—"}</td>
                    <td className="tabular px-4 py-2 text-right">{d.tonnes.toFixed(2)}</td>
                    <td className="tabular px-4 py-2 text-right text-ink-soft">
                      {d.in_stock_mt.toFixed(2)}
                    </td>
                    {/* The column that costs money to ignore: material sold
                        and not on the floor. */}
                    <td
                      className={`tabular px-4 py-2 text-right ${
                        d.to_buy_mt > 0 ? "font-semibold text-attention-ink" : "text-ink-faint"
                      }`}
                    >
                      {d.to_buy_mt > 0 ? d.to_buy_mt.toFixed(2) : "—"}
                    </td>
                    <td className="tabular px-4 py-2 text-right">{inrShort(d.value)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* --- Enquiry -> quote -> win, compressed to three numbers --------- */}
      {salesStages.length > 0 && (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3 sm:gap-3">
          {winTiles.map((t, i) => (
            <div
              key={t.label}
              className="flex flex-col gap-1 rounded-card border border-rule bg-surface px-4 py-3.5 shadow-card"
            >
              <p className="text-xs font-medium text-ink-soft">{t.label}</p>
              <p className="tabular text-2xl font-bold leading-none text-ink">
                {formatView(view, t.stage)}
              </p>
              {i > 0 && (
                <p className="text-xs text-ink-faint">
                  {t.rate} of {winTiles[i - 1].label.toLowerCase()}
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      {/* --- Sales funnel and payment funnel, side by side ---------------- */}
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Sales funnel" subtitle="Where deals stop">
          {funnel.data ? (
            <FunnelChart
              stages={salesStages.map((s) => ({
                stage: s.stage,
                value: pick(view, s),
                displayValue: formatView(view, s),
                approx: view === "value" && s.stage === ENQUIRIES_STAGE,
                note:
                  view !== "count" && s.stage === ENQUIRIES_STAGE && s.unquantified > 0
                    ? `+${s.unquantified} qty unknown`
                    : undefined,
              }))}
            />
          ) : (
            <Loading label="Building the funnel" />
          )}
        </Card>

        <Card title="Payment funnel" subtitle="Money owed, by how soon it's due">
          {!p ? (
            <Loading label="Building the funnel" />
          ) : (
            <HBarChart
              data={p.payment_buckets.map((b) => ({
                label: b.label,
                value: pick(view, b),
                tone: b.key === "overdue" ? "bad" : b.key === "due_soon" ? "warn" : "neutral",
              }))}
              unit={view === "tonnes" ? "MT" : undefined}
              emptyMessage="Nothing shipped and unpaid yet."
            />
          )}
        </Card>
      </div>

      {/* --- Who to chase, and when ---------------------------------------
          The payment funnel above says how much is at each stage; this says
          who, so a trader can act rather than just look. */}
      {(p?.payments.length ?? 0) > 0 && (
        <Card
          title="Payments pending"
          subtitle="Shipped, not yet paid — most overdue first"
          padded={false}
        >
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-rule bg-sunk text-left text-xs uppercase tracking-wide text-ink-faint">
                <tr>
                  <th className="px-4 py-2 font-medium">Customer</th>
                  <th className="px-4 py-2 font-medium">Despatched</th>
                  <th className="px-4 py-2 font-medium">Terms</th>
                  <th className="px-4 py-2 font-medium">Due</th>
                  <th className="px-4 py-2 text-right font-medium">Amount</th>
                  <th className="px-4 py-2 text-right font-medium">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-sunk">
                {p!.payments.map((row) => (
                  <tr key={row.quotation_id} className="hover:bg-sunk">
                    <td className="px-4 py-2">
                      <Link to={`/quotations/${row.quotation_id}`} className="text-ink hover:text-brand">
                        {row.customer}
                      </Link>
                      <span className="ml-2 text-xs text-ink-faint">{row.quotation_number}</span>
                    </td>
                    <td className="px-4 py-2 text-ink-soft">{row.despatched_on ?? "—"}</td>
                    {/* Terms are shown because the due date is derived from
                        them: a trader disputing the date needs to see what it
                        was calculated from. */}
                    <td className="px-4 py-2 text-xs text-ink-faint">{row.terms ?? "30 days (assumed)"}</td>
                    <td className="px-4 py-2 text-ink-soft">{row.due_on ?? "—"}</td>
                    <td className="tabular px-4 py-2 text-right">{inrShort(row.value)}</td>
                    <td className="px-4 py-2 text-right">
                      {row.days_overdue > 0 ? (
                        <span className="rounded-full bg-attention-wash px-2 py-0.5 text-[11px] font-medium text-attention-ink">
                          {row.days_overdue}d overdue
                        </span>
                      ) : (
                        <span className="text-xs text-ink-faint">on terms</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* --- Trend -------------------------------------------------------- */}
      <div className="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
        <Card
          title="Trend"
          subtitle={t?.period_label}
          action={
            <div className="flex gap-0.5 rounded-lg bg-sunk p-0.5">
              {METRIC_SERIES.map((s) => (
                <button
                  key={s.key}
                  type="button"
                  onClick={() => setMetric(s.key)}
                  className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                    metric === s.key
                      ? "bg-surface text-brand-soft-ink shadow-card"
                      : "text-ink-faint hover:text-ink"
                  }`}
                >
                  {s.label}
                </button>
              ))}
            </div>
          }
        >
          <AreaChart
            points={series}
            unit=""
            format={(v) => (metric === "value" ? inrShort(v) : v.toLocaleString("en-IN"))}
          />
        </Card>

        <Card title="This period vs last" subtitle="By week">
          {weekly.length > 0 ? (
            <>
              <ColumnChart
                points={weekly}
                format={(v) => (metric === "value" ? inrShort(v) : String(v))}
              />
              <div className="mt-3 flex items-center gap-4 text-[11px] text-ink-faint">
                <span className="flex items-center gap-1.5">
                  <span className="size-2 rounded-sm bg-brand" /> This period
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="size-2 rounded-sm bg-rule-firm" /> Previous
                </span>
              </div>
            </>
          ) : (
            <Empty message="Not enough history yet." />
          )}
        </Card>
      </div>
    </div>
  );
}

/** Group the daily series into weeks, pairing each with the week before it. */
function bucketByWeek(
  series: TrendPoint[],
  metric: MetricKey,
): { label: string; current: number; previous?: number }[] {
  if (series.length === 0) return [];

  const weeks: { label: string; total: number }[] = [];
  for (let i = 0; i < series.length; i += 7) {
    const slice = series.slice(i, i + 7);
    const total = slice.reduce(
      (sum, p) => sum + (metric === "value" ? Number(p.value) : p[metric]),
      0,
    );
    const from = new Date(slice[0].day);
    weeks.push({ label: from.toLocaleDateString("en-IN", { day: "2-digit", month: "short" }), total });
  }

  return weeks.map((w, i) => ({
    label: w.label,
    current: w.total,
    previous: i > 0 ? weeks[i - 1].total : undefined,
  }));
}
