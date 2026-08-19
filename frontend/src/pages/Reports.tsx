import { useState } from "react";

import { useApi } from "../api/client";
import type { FunnelReport, ReportResult } from "../api/types";
import { FunnelChart } from "../components/charts";
import {
  Button,
  Card,
  Empty,
  ErrorNote,
  inrShort,
  Loading,
  Scroller,
  Select,
} from "../components/ui";

/* ---------------------------------------------------------------------------
   Reports.

   Every figure is counted from stored rows, never recomputed against today's
   rules - so last quarter's margin does not move when a trader edits a
   percentage this morning.
   --------------------------------------------------------------------------- */

const REPORTS = [
  { value: "win-loss", label: "Win / loss" },
  { value: "margin", label: "Margin realised" },
  { value: "stock-ageing", label: "Stock ageing" },
  { value: "customers", label: "Customer performance" },
  { value: "products", label: "Product performance" },
];

const PERIODS = [
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last quarter" },
  { value: "365", label: "Last year" },
];

function Funnel({ days }: { days: string }) {
  const { data } = useApi<FunnelReport>(`/reports/funnel?days=${days}`);
  if (!data) return null;

  return (
    <Card title="Enquiry to order" subtitle={data.period}>
      <FunnelChart stages={data.stages} />
    </Card>
  );
}

function formatCell(key: string, value: string | number): string {
  if (typeof value === "number") return String(value);
  if (key.endsWith("_inr")) return inrShort(value);
  if (key.endsWith("_pct") && value !== "") return `${value}%`;
  return value;
}

function humanise(key: string): string {
  return key
    .replace(/_inr$/, " (₹)")
    .replace(/_pct$/, " %")
    .replace(/_mt$/, " MT")
    .replace(/_/g, " ")
    .replace(/^./, (c) => c.toUpperCase());
}

export default function Reports() {
  const [name, setName] = useState("win-loss");
  const [days, setDays] = useState("30");

  const { data, loading, error } = useApi<ReportResult>(`/reports/${name}?days=${days}`);

  const columns = data?.rows.length ? Object.keys(data.rows[0]) : [];

  return (
    <div className="flex flex-col gap-4 p-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-ink">Reports</h1>
          <p className="text-sm text-ink-faint">
            Counted from what was actually quoted, at the rules in force at the time.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Select value={name} onChange={setName} options={REPORTS} />
          <Select value={days} onChange={setDays} options={PERIODS} />
          <a href={`/api/v1/reports/${name}?days=${days}&fmt=csv`} download>
            <Button>Export CSV</Button>
          </a>
        </div>
      </header>

      <Funnel days={days} />

      {error && <ErrorNote message={error} />}
      {loading && !data && <Loading label="Building the report" />}

      {data && (
        <Card title={data.title} subtitle={data.period} padded={false}>
          {Object.keys(data.totals).length > 0 && (
            <div className="flex flex-wrap gap-x-8 gap-y-2 border-b border-rule bg-sunk px-4 py-2.5">
              {Object.entries(data.totals)
                .filter(([, v]) => typeof v !== "object")
                .map(([key, value]) => (
                  <div key={key}>
                    <p className="text-[11px] uppercase tracking-wider text-ink-faint">
                      {humanise(key)}
                    </p>
                    <p className="text-sm font-semibold tabular text-ink">
                      {value === null || value === "" ? "—" : formatCell(key, value as string)}
                    </p>
                  </div>
                ))}
            </div>
          )}

          {data.rows.length === 0 ? (
            <Empty message="Nothing in this period." />
          ) : (
            <Scroller>
              <table className="w-full min-w-[40rem] text-sm">
                <thead>
                  <tr className="border-b border-rule bg-sunk text-[11px] uppercase tracking-wider text-ink-faint">
                    {columns.map((c) => (
                      <th
                        key={c}
                        className={`px-3 py-1.5 font-medium ${
                          c.endsWith("_inr") || c.endsWith("_pct") || c.endsWith("_mt")
                            ? "text-right"
                            : "text-left"
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
                          className={`px-3 py-1.5 tabular ${
                            c.endsWith("_inr") || c.endsWith("_pct") || c.endsWith("_mt")
                              ? "text-right text-ink"
                              : "text-ink-soft"
                          }`}
                        >
                          {formatCell(c, row[c])}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </Scroller>
          )}
        </Card>
      )}
    </div>
  );
}
