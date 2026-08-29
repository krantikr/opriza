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
import { AreaChart, ColumnChart, DonutChart, FunnelChart } from "../components/charts";
import {
  ago,
  Badge,
  Button,
  Card,
  Kpi,
  Empty,
  ErrorNote,
  inrShort,
  Loading,
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

function Arrow({ direction }: { direction: "up" | "down" | "flat" }) {
  if (direction === "flat") return <span aria-hidden="true">→</span>;
  return (
    <svg viewBox="0 0 12 12" className="size-3" fill="none" stroke="currentColor" strokeWidth="2">
      {direction === "up" ? (
        <path d="M6 10V2M2.5 5.5L6 2l3.5 3.5" strokeLinecap="round" strokeLinejoin="round" />
      ) : (
        <path d="M6 2v8M2.5 6.5L6 10l3.5-3.5" strokeLinecap="round" strokeLinejoin="round" />
      )}
    </svg>
  );
}

/** A headline figure with its movement against the previous period. */
function DeltaTile({
  label,
  current,
  changePct,
  direction,
  good,
  unit,
  format,
  emphasis = false,
}: {
  label: string;
  current: number;
  changePct: number | null;
  direction: "up" | "down" | "flat";
  good: boolean | null;
  unit: string;
  format?: (v: number) => string;
  emphasis?: boolean;
}) {
  const tone =
    good === null ? "text-ink-faint" : good ? "text-settled" : "text-danger";
  const rendered = format
    ? format(current)
    : `${current.toLocaleString("en-IN")}${unit && unit !== "INR" ? unit : ""}`;

  return (
    <div
      className={`flex flex-col gap-1.5 rounded-card border bg-surface px-4 py-3.5 shadow-card ${
        emphasis ? "border-brand/50" : "border-rule"
      }`}
    >
      <p className="text-xs font-medium text-ink-soft">{label}</p>
      <p className="tabular text-2xl font-bold leading-none text-ink">{rendered}</p>
      <div className={`flex items-center gap-1 text-xs font-medium ${tone}`}>
        <Arrow direction={direction} />
        <span className="tabular">
          {changePct === null ? "no change" : `${Math.abs(changePct)}%`}
        </span>
        <span className="font-normal text-ink-faint">vs previous</span>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const [days, setDays] = useState("30");
  const [metric, setMetric] = useState<MetricKey>("quotations");
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

  const deltaFor = (key: string) => t?.deltas.find((d) => d.key === key);

  const series = (t?.series ?? []).map((p) => ({
    label: new Date(p.day).toLocaleDateString("en-IN", { day: "2-digit", month: "short" }),
    value: metric === "value" ? Number(p.value) : p[metric],
  }));

  // Weekly buckets make the this-vs-last comparison legible; 30 daily pairs
  // would be a picket fence nobody can read.
  const weekly = bucketByWeek(t?.series ?? [], metric);

  const needsAttention =
    (m?.quotations.pending_approval ?? 0) + (m?.quotations.needs_information ?? 0);

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
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm text-ink-soft">
            {t ? `${t.period_label} · compared with ${t.previous_label}` : "Loading…"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Select value={days} onChange={setDays} options={PERIODS} />
          <Button onClick={() => { metrics.reload(); trends.reload(); }}>Refresh</Button>
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

      {/* --- The desk, stage by stage ------------------------------------
          Money moves left to right: an enquiry nobody has answered, through
          a quotation out with the customer, to cash that has not arrived.
          Derived from status rather than stored, so a quotation can never sit
          in a stage that contradicts its own state. */}
      <div className="grid grid-cols-2 gap-2 sm:gap-3 lg:grid-cols-5">
        {(p?.stages ?? []).map((stage) => (
          <Link
            key={stage.key}
            to={`/quotations?stage=${stage.key}`}
            className="rounded-card border border-rule bg-surface px-3 py-2.5 transition-colors hover:border-brand"
          >
            <p className="truncate text-[11px] font-medium uppercase tracking-wide text-ink-faint">
              {stage.label}
            </p>
            {/* Tonnage leads. Twelve quotations is not a workload a trader
                can feel; 340 MT is. The count stays as the smaller figure
                beside it, because it still answers "how many customers am I
                dealing with here". */}
            <p className="tabular mt-0.5 text-xl font-semibold text-ink">
              {stage.tonnes > 0 ? `${stage.tonnes.toFixed(2)}` : "—"}
              {stage.tonnes > 0 && (
                <span className="ml-1 text-xs font-normal text-ink-faint">MT</span>
              )}
            </p>
            <p className="tabular text-xs text-ink-faint">
              {stage.count} quote{stage.count === 1 ? "" : "s"}
              {stage.value > 0 && ` · ${inrShort(stage.value)}`}
            </p>
          </Link>
        ))}
      </div>

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

      {/* --- Headline movement ------------------------------------------- */}
      <div className="grid grid-cols-2 gap-2 sm:gap-3 xl:grid-cols-4">
        {(["quotations", "value", "win_rate", "response_hours"] as const).map((key) => {
          const d = deltaFor(key);
          if (!d) return null;
          return (
            <DeltaTile
              key={key}
              label={d.label}
              current={d.current}
              changePct={d.change_pct}
              direction={d.direction}
              good={d.good}
              unit={d.unit}
              emphasis={key === "value"}
              format={
                d.unit === "INR"
                  ? (v) => inrShort(v)
                  : d.unit === "%"
                    ? (v) => `${v}%`
                    : d.unit === "h"
                      ? (v) => (v ? `${v}h` : "—")
                      : undefined
              }
            />
          );
        })}
      </div>

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

      {/* --- Where work sits ---------------------------------------------- */}
      <div className="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
        <Card title="Enquiry to order" subtitle="Where enquiries stop">
          {funnel.data ? (
            <FunnelChart stages={funnel.data.stages} />
          ) : (
            <Loading label="Building the funnel" />
          )}
        </Card>

        <Card title="Quotations by status">
          <DonutChart
            data={Object.entries(m?.quotations.by_status ?? {})
              .filter(([, v]) => v > 0)
              .map(([label, value]) => ({
                label: label
                  .replace(/_/g, " ")
                  .toLowerCase()
                  .replace(/^./, (c) => c.toUpperCase()),
                value,
              }))}
            centerValue={String(m?.quotations.total ?? 0)}
            centerLabel="total quotations"
          />
        </Card>
      </div>

      {/* --- Quality and activity ----------------------------------------- */}
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Review quality" subtitle="How often a human had to step in">
          <dl className="flex flex-col divide-y divide-rule">
            {[
              ["Decisions recorded", String(m?.approvals.decisions ?? 0)],
              [
                "Approval rate",
                m?.approvals.approval_rate != null
                  ? `${(m.approvals.approval_rate * 100).toFixed(0)}%`
                  : "—",
              ],
              [
                "Edit rate",
                m?.approvals.edit_rate != null
                  ? `${(m.approvals.edit_rate * 100).toFixed(0)}%`
                  : "—",
              ],
              [
                "Avg processing time",
                m?.emails.avg_processing_ms
                  ? `${(m.emails.avg_processing_ms / 1000).toFixed(1)}s`
                  : "—",
              ],
            ].map(([label, value]) => (
              <div key={label} className="flex justify-between gap-4 py-2 text-sm">
                <dt className="text-ink-soft">{label}</dt>
                <dd className="tabular font-medium text-ink">{value}</dd>
              </div>
            ))}
          </dl>
          <p className="mt-3 text-xs leading-relaxed text-ink-faint">
            Edit rate is how often a reviewer changed the draft before sending — the clearest
            signal of how well the system is actually writing.
          </p>
        </Card>

        <Card title="Recent activity" padded={false}>
          <div className="max-h-72 overflow-y-auto">
            {m?.recent_activity.length ? (
              m.recent_activity.slice(0, 12).map((a, i) => (
                <div
                  key={`${a.entity_id}-${i}`}
                  className="flex items-start justify-between gap-3 border-b border-rule px-4 py-2 last:border-0"
                >
                  <div className="min-w-0">
                    <Badge value={a.action} dot={false} />
                    {a.detail && (
                      <p className="mt-1 truncate text-xs text-ink-soft">{a.detail}</p>
                    )}
                  </div>
                  <span className="shrink-0 text-[11px] text-ink-faint">{ago(a.at)}</span>
                </div>
              ))
            ) : (
              <Empty message="Nothing has happened yet." />
            )}
          </div>
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
