import { useState } from "react";
import { Link } from "react-router-dom";

import { useApi } from "../api/client";
import type { FunnelReport, Insights, ReportResult } from "../api/types";
import { AreaChart, ColumnChart, DonutChart, FunnelChart, HBarChart } from "../components/charts";
import {
  Badge,
  Button,
  Card,
  Empty,
  ErrorNote,
  inr,
  inrShort,
  Loading,
  Scroller,
  Select,
} from "../components/ui";

/* ---------------------------------------------------------------------------
   Reports.

   Structured as three questions rather than as a list of tables:

   * **How are we doing?** Headline figures against the same window before,
     with the movement that matters called out in words.
   * **Where is the business?** Composition - which customers, which products,
     which stage things stop at.
   * **What needs me?** The quotations sitting still, ordered by what they are
     worth, because that is the cost of leaving them.

   Every figure is counted from stored rows at the rules in force at the time,
   so last quarter does not move when a trader edits a percentage today.
   --------------------------------------------------------------------------- */

const PERIODS = [
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last quarter" },
  { value: "365", label: "Last year" },
];

const DETAIL_REPORTS = [
  { value: "win-loss", label: "Win / loss" },
  { value: "margin", label: "Margin realised" },
  { value: "stock-ageing", label: "Stock ageing" },
  { value: "customers", label: "Customer performance" },
  { value: "products", label: "Product performance" },
];

const SERIES = [
  { key: "value", label: "Quoted value" },
  { key: "quotations", label: "Quotations" },
  { key: "sent", label: "Sent" },
] as const;

type SeriesKey = (typeof SERIES)[number]["key"];

function Arrow({ direction }: { direction: "up" | "down" | "flat" }) {
  if (direction === "flat") return <span aria-hidden="true">→</span>;
  return (
    <svg viewBox="0 0 12 12" className="size-3" fill="none" stroke="currentColor" strokeWidth="2">
      <path
        d={direction === "up" ? "M6 10V2M2.5 5.5L6 2l3.5 3.5" : "M6 2v8M2.5 6.5L6 10l3.5-3.5"}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function format(value: number, unit: string): string {
  if (unit === "INR") return inrShort(value);
  if (unit === "%") return `${value}%`;
  if (unit === "h") return value ? `${value}h` : "—";
  return value.toLocaleString("en-IN");
}

/** A headline figure, its movement, and what it is measured against. */
function MetricCard({
  metric,
  emphasis = false,
}: {
  metric: Insights["metrics"][number];
  emphasis?: boolean;
}) {
  const tone =
    metric.good === null ? "text-ink-faint" : metric.good ? "text-settled" : "text-danger";

  return (
    <div
      className={`flex flex-col gap-1.5 rounded-card border bg-surface px-4 py-3.5 shadow-card ${
        emphasis ? "border-brand/50" : "border-rule"
      }`}
      title={metric.hint}
    >
      <p className="text-xs font-medium text-ink-soft">{metric.label}</p>
      <p className="tabular text-2xl font-bold leading-none text-ink">
        {format(metric.current, metric.unit)}
      </p>
      <div className={`flex items-center gap-1 text-xs font-medium ${tone}`}>
        <Arrow direction={metric.direction} />
        <span className="tabular">
          {metric.change_pct === null ? "no change" : `${Math.abs(metric.change_pct)}%`}
        </span>
        <span className="font-normal text-ink-faint">
          from {format(metric.previous, metric.unit)}
        </span>
      </div>
    </div>
  );
}

const HIGHLIGHT_TONE = {
  good: "border-settled/40 bg-settled-wash text-settled-ink",
  warn: "border-attention/40 bg-attention-wash text-attention-ink",
  bad: "border-danger/40 bg-danger-wash text-danger-ink",
  info: "border-info/40 bg-info-wash text-info-ink",
};

function Highlight({ item }: { item: Insights["highlights"][number] }) {
  const body = (
    <>
      <p className="text-sm font-semibold">{item.title}</p>
      <p className="mt-0.5 text-xs opacity-90">{item.detail}</p>
    </>
  );
  const className = `block rounded-card border px-4 py-3 ${HIGHLIGHT_TONE[item.tone]}`;

  return item.link ? (
    <Link to={item.link} className={`${className} transition-opacity hover:opacity-80`}>
      {body}
    </Link>
  ) : (
    <div className={className}>{body}</div>
  );
}

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

/** The raw table behind a headline, for anyone who wants to check the working. */
function DetailTable({ days }: { days: string }) {
  const [name, setName] = useState("win-loss");
  const { data, loading, error } = useApi<ReportResult>(`/reports/${name}?days=${days}`);
  const columns = data?.rows.length ? Object.keys(data.rows[0]) : [];

  return (
    <Card
      title="Detail"
      subtitle={data?.period}
      padded={false}
      action={
        <div className="flex items-center gap-2">
          <Select value={name} onChange={setName} options={DETAIL_REPORTS} />
          <a href={`/api/v1/reports/${name}?days=${days}&fmt=csv`} download>
            <Button compact>Export CSV</Button>
          </a>
        </div>
      }
    >
      {error && <div className="p-4"><ErrorNote message={error} /></div>}
      {loading && !data && <Loading label="Building the report" />}

      {data && Object.keys(data.totals).length > 0 && (
        <div className="flex flex-wrap gap-x-8 gap-y-2 border-b border-rule bg-sunk px-4 py-2.5">
          {Object.entries(data.totals)
            .filter(([, v]) => typeof v !== "object")
            .map(([key, value]) => (
              <div key={key}>
                <p className="text-[11px] text-ink-faint">{humanise(key)}</p>
                <p className="tabular text-sm font-semibold text-ink">
                  {value === null || value === "" ? "—" : cell(key, value as string)}
                </p>
              </div>
            ))}
        </div>
      )}

      {data && data.rows.length === 0 ? (
        <Empty message="Nothing in this period." />
      ) : (
        data && (
          <Scroller>
            <table className="w-full min-w-[40rem] text-sm">
              <thead>
                <tr className="border-b border-rule bg-sunk text-xs font-medium text-ink-soft">
                  {columns.map((c) => (
                    <th
                      key={c}
                      className={`px-3 py-2 ${
                        /_inr$|_pct$|_mt$/.test(c) ? "text-right" : "text-left"
                      }`}
                    >
                      {humanise(c)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-rule">
                {data.rows.map((row, i) => (
                  <tr key={i} className="hover:bg-sunk/60">
                    {columns.map((c) => (
                      <td
                        key={c}
                        className={`tabular px-3 py-2 ${
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
        )
      )}
    </Card>
  );
}

/** Group a daily series into at most `target` buckets, each paired with the
 *  one before it. Labels become ranges, which is what a comparison needs. */
function bucketForComparison(
  points: Insights["series"],
  key: SeriesKey,
  target = 6,
): { label: string; current: number; previous?: number }[] {
  if (points.length === 0) return [];

  const width = Math.max(1, Math.ceil(points.length / target));
  const groups: { label: string; total: number }[] = [];

  for (let i = 0; i < points.length; i += width) {
    const slice = points.slice(i, i + width);
    const total = slice.reduce((sum, p) => sum + (p[key] as number), 0);
    const from = slice[0].label;
    const to = slice[slice.length - 1].label;
    groups.push({ label: width === 1 || from === to ? from : `${from}–${to}`, total });
  }

  return groups.map((g, i) => ({
    label: g.label,
    current: g.total,
    previous: i > 0 ? groups[i - 1].total : undefined,
  }));
}

export default function Reports() {
  const [days, setDays] = useState("30");
  const [series, setSeries] = useState<SeriesKey>("value");

  const { data, loading, error } = useApi<Insights>(`/reports/insights?days=${days}`);
  const funnel = useApi<FunnelReport>(`/reports/funnel?days=${days}`);

  if (loading && !data) return <Loading label="Building your reports" />;
  if (error) return <div className="p-5"><ErrorNote message={error} /></div>;
  if (!data) return null;

  const headline = ["quoted_value", "win_rate", "margin_pct", "response_hours"];
  const secondary = ["enquiries", "quotations", "sent", "avg_value", "override_rate"];

  const points = data.series.map((p) => ({
    label: p.label,
    value: p[series] as number,
  }));

  // The comparison answers "is this stretch better than the one before?", so
  // it needs a handful of wide buckets - not one column per day, whose labels
  // collapse into "2.. 2.. 3.." and say nothing.
  const columns = bucketForComparison(data.series, series);

  return (
    <div className="flex flex-col gap-4 p-4 sm:gap-5 sm:p-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-ink">Reports</h1>
          <p className="text-sm text-ink-faint">
            {data.period_label} · compared with {data.previous_label}
          </p>
        </div>
        <Select value={days} onChange={setDays} options={PERIODS} />
      </header>

      {/* --- What changed, in words ---------------------------------------- */}
      {data.highlights.length > 0 && (
        <div className="grid gap-3 md:grid-cols-2">
          {data.highlights.map((h) => (
            <Highlight key={h.title} item={h} />
          ))}
        </div>
      )}

      {/* --- Headline figures ---------------------------------------------- */}
      <div className="grid grid-cols-2 gap-2 sm:gap-3 xl:grid-cols-4">
        {headline.map((key) => {
          const metric = data.metrics.find((m) => m.key === key);
          return metric ? (
            <MetricCard key={key} metric={metric} emphasis={key === "quoted_value"} />
          ) : null;
        })}
      </div>

      <div className="grid grid-cols-2 gap-2 sm:gap-3 xl:grid-cols-5">
        {secondary.map((key) => {
          const metric = data.metrics.find((m) => m.key === key);
          return metric ? <MetricCard key={key} metric={metric} /> : null;
        })}
      </div>

      {/* --- Trend and comparison ------------------------------------------- */}
      <div className="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
        <Card
          title="Trend"
          subtitle={data.period_label}
          action={
            <div className="flex gap-0.5 rounded-lg bg-sunk p-0.5">
              {SERIES.map((s) => (
                <button
                  key={s.key}
                  type="button"
                  onClick={() => setSeries(s.key)}
                  className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                    series === s.key
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
            points={points}
            format={(v) => (series === "value" ? inrShort(v) : v.toLocaleString("en-IN"))}
          />
        </Card>

        <Card title="Period on period" subtitle="Each bucket against the one before">
          <ColumnChart
            points={columns}
            format={(v) => (series === "value" ? inrShort(v) : String(v))}
          />
          <div className="mt-3 flex items-center gap-4 text-[11px] text-ink-faint">
            <span className="flex items-center gap-1.5">
              <span className="size-2 rounded-sm bg-brand" /> This bucket
            </span>
            <span className="flex items-center gap-1.5">
              <span className="size-2 rounded-sm bg-rule-firm" /> Previous
            </span>
          </div>
        </Card>
      </div>

      {/* --- Where the business is ------------------------------------------ */}
      <div className="grid gap-4 xl:grid-cols-[1.6fr_1fr]">
        <Card title="Enquiry to order" subtitle="Where enquiries stop">
          {funnel.data ? <FunnelChart stages={funnel.data.stages} /> : <Loading />}
        </Card>

        <Card title="Quotations by status">
          <DonutChart
            data={data.by_status.map((s) => ({ label: s.label, value: s.value }))}
            centerValue={String(data.by_status.reduce((sum, s) => sum + s.value, 0))}
            centerLabel="raised this period"
          />
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Customers by quoted value" padded={false}>
          {data.top_customers.length === 0 ? (
            <Empty message="No customer activity in this period." />
          ) : (
            <Scroller>
              <table className="w-full min-w-[26rem] text-sm">
                <thead>
                  <tr className="border-b border-rule bg-sunk text-xs font-medium text-ink-soft">
                    <th className="px-4 py-2 text-left">Customer</th>
                    <th className="px-3 py-2 text-right">Quotes</th>
                    <th className="px-3 py-2 text-right">Value</th>
                    <th className="px-4 py-2 text-right">Win rate</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-rule">
                  {data.top_customers.map((c) => (
                    <tr key={c.name} className="hover:bg-sunk/60">
                      <td className="max-w-44 truncate px-4 py-2 text-ink">{c.name}</td>
                      <td className="tabular px-3 py-2 text-right text-ink-soft">
                        {c.quotations}
                      </td>
                      <td className="tabular px-3 py-2 text-right font-medium text-ink">
                        {inr(c.value)}
                      </td>
                      <td className="tabular px-4 py-2 text-right text-ink-soft">
                        {c.win_rate === null ? "—" : `${c.win_rate}%`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Scroller>
          )}
        </Card>

        <Card title="Products by quoted value">
          <HBarChart
            data={data.top_products.map((p) => ({
              label: p.name,
              value: Math.round(p.value),
              tone: "brand" as const,
            }))}
            emptyMessage="No products quoted in this period."
          />
        </Card>
      </div>

      {/* --- What needs a person -------------------------------------------- */}
      <Card
        title="Waiting on you"
        subtitle="Open quotations, largest first — the cost of leaving them"
        padded={false}
      >
        {data.attention.length === 0 ? (
          <Empty message="Nothing is sitting still. Every quotation has been actioned." />
        ) : (
          <Scroller>
            <table className="w-full min-w-[38rem] text-sm">
              <thead>
                <tr className="border-b border-rule bg-sunk text-xs font-medium text-ink-soft">
                  <th className="px-4 py-2 text-left">Quotation</th>
                  <th className="px-3 py-2 text-left">Customer</th>
                  <th className="px-3 py-2 text-right">Value</th>
                  <th className="px-3 py-2 text-right">Waiting</th>
                  <th className="px-4 py-2 text-left">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-rule">
                {data.attention.map((row) => (
                  <tr key={row.id} className="hover:bg-sunk/60">
                    <td className="px-4 py-2">
                      <Link to={row.link} className="font-medium text-brand hover:underline">
                        {row.number}
                      </Link>
                    </td>
                    <td className="max-w-40 truncate px-3 py-2 text-ink-soft">{row.customer}</td>
                    <td className="tabular px-3 py-2 text-right font-medium text-ink">
                      {inr(row.value)}
                    </td>
                    <td
                      className={`tabular px-3 py-2 text-right ${
                        row.age_days >= 3 ? "font-medium text-attention" : "text-ink-soft"
                      }`}
                    >
                      {row.age_days}d
                    </td>
                    <td className="px-4 py-2">
                      <Badge value={row.status} dot={false} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Scroller>
        )}
      </Card>

      <DetailTable days={days} />
    </div>
  );
}
