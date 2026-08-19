import { useState } from "react";

import { useApi } from "../api/client";
import type { StockItem, StockSummary } from "../api/types";
import { DonutChart, HBarChart, type BarDatum } from "../components/charts";
import {
  Button,
  Card,
  Empty,
  ErrorNote,
  Input,
  inrShort,
  Kpi,
  Loading,
  num,
} from "../components/ui";

/** Top product types by balance tonnage - one consistent hue since this is a
 * single ranked series, not a comparison of distinct categorical series. */
function byProductType(rows: StockSummary[]): BarDatum[] {
  const totals = new Map<string, number>();
  for (const row of rows) {
    const key = row.product_type ?? "Unspecified";
    totals.set(key, (totals.get(key) ?? 0) + Number(row.balance_qty_mt));
  }
  return [...totals.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8)
    .map(([label, value]) => ({ label, value: Math.round(value), tone: "brand" as const }));
}

/** Ageing buckets. Deadstock is cash on the floor, so it is worth surfacing. */
function byAgeing(rows: StockSummary[]): BarDatum[] {
  const buckets = { "0-30 days": 0, "31-60 days": 0, "61-90 days": 0, "Over 90 days": 0 };
  for (const row of rows) {
    const age = row.ageing_max_days ?? 0;
    const key =
      age <= 30 ? "0-30 days" : age <= 60 ? "31-60 days" : age <= 90 ? "61-90 days" : "Over 90 days";
    buckets[key as keyof typeof buckets] += Math.round(Number(row.balance_qty_mt));
  }
  return Object.entries(buckets).map(([label, value]) => ({ label, value }));
}

/** A spec key stable across reloads, so an expanded row stays expanded. */
function specKey(row: StockSummary): string {
  return [row.product_type, row.grade, row.thickness_mm, row.width_mm, row.length_mm].join("|");
}

function rate(value: number | null): string {
  return value === null ? "—" : `₹${value.toFixed(2)}`;
}

function day(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "2-digit",
  });
}

/** Every per-lot column the rollup has to collapse, straight from the
 * stock list: location, mill, coil, pieces, weight, cost and purchase date. */
function LotTable({ lots }: { lots: StockItem[] }) {
  return (
    <div className="overflow-x-auto border-y border-rule bg-sunk/60 px-4 py-3">
      <table className="w-full min-w-5xl text-xs">
        <thead className="text-left uppercase tracking-wide text-ink-faint">
          <tr>
            <th className="py-1 pr-4 font-medium">Location</th>
            <th className="py-1 pr-4 font-medium">Make / mill</th>
            <th className="py-1 pr-4 font-medium">Coil no</th>
            <th className="py-1 pr-4 text-right font-medium">NOP</th>
            <th className="py-1 pr-4 text-right font-medium">Qty (kg)</th>
            <th className="py-1 pr-4 text-right font-medium">Bal. NOP</th>
            <th className="py-1 pr-4 text-right font-medium">Bal. qty (kg)</th>
            <th className="py-1 pr-4 text-right font-medium">Purchase /kg</th>
            <th className="py-1 pr-4 text-right font-medium">Landed /kg</th>
            <th className="py-1 pr-4 text-right font-medium">Ageing</th>
            <th className="py-1 text-right font-medium">Stock date</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-rule/70">
          {lots.map((lot) => (
            <tr key={lot.id} className="text-ink-soft">
              <td className="py-1.5 pr-4">{lot.location ?? "—"}</td>
              <td className="py-1.5 pr-4">{lot.make ?? "—"}</td>
              <td className="py-1.5 pr-4 font-mono">{lot.coil_no ?? "—"}</td>
              <td className="tabular py-1.5 pr-4 text-right">{num(lot.nop, 0)}</td>
              <td className="tabular py-1.5 pr-4 text-right">{num(lot.qty_kg, 0)}</td>
              <td className="tabular py-1.5 pr-4 text-right">{num(lot.balance_nop, 0)}</td>
              <td className="tabular py-1.5 pr-4 text-right font-medium text-ink">
                {num(lot.balance_qty_kg, 0)}
              </td>
              <td className="tabular py-1.5 pr-4 text-right">{rate(lot.purchase_rate_per_kg)}</td>
              <td className="tabular py-1.5 pr-4 text-right">{rate(lot.landed_cost_per_kg)}</td>
              <td className="tabular py-1.5 pr-4 text-right">
                {lot.ageing_days === null ? "—" : `${lot.ageing_days}d`}
              </td>
              <td className="tabular py-1.5 text-right text-ink-faint">{day(lot.stock_date)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Stock() {
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const { data, error, loading, reload } = useApi<StockSummary[]>(`/stock/summary`);

  function toggle(key: string) {
    setExpanded((current) => {
      const next = new Set(current);
      if (!next.delete(key)) next.add(key);
      return next;
    });
  }

  const filtered = (data ?? []).filter((row) => {
    if (!search) return true;
    const needle = search.toLowerCase();
    return (
      (row.grade ?? "").toLowerCase().includes(needle) ||
      (row.product_type ?? "").toLowerCase().includes(needle) ||
      row.locations.some((loc) => loc.toLowerCase().includes(needle)) ||
      // Searching a mill or coil number should find the spec holding it, even
      // though neither survives the rollup into a summary row.
      row.lots.some(
        (lot) =>
          (lot.make ?? "").toLowerCase().includes(needle) ||
          (lot.coil_no ?? "").toLowerCase().includes(needle),
      )
    );
  });

  const lotTotal = (data ?? []).reduce((sum, row) => sum + row.lot_count, 0);

  const totalMt = (data ?? []).reduce((sum, r) => sum + Number(r.balance_qty_mt), 0);
  const totalValue = (data ?? []).reduce(
    (sum, r) => sum + Number(r.balance_qty_mt) * 1000 * (r.avg_landed_cost_per_kg ?? 0),
    0,
  );
  const dead = (data ?? []).filter((r) => (r.ageing_max_days ?? 0) > 90);
  const deadMt = dead.reduce((sum, r) => sum + Number(r.balance_qty_mt), 0);
  const locations = new Set((data ?? []).flatMap((r) => r.locations)).size;

  return (
    <div className="flex flex-col gap-4 p-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-ink">Stock on hand</h1>
          <p className="text-sm text-ink-faint">
            {data ? `${data.length} spec${data.length === 1 ? "" : "s"}` : "…"} across{" "}
            {data ? `${lotTotal} lot${lotTotal === 1 ? "" : "s"}` : "…"} · balance after existing
            orders. Expand a row for the individual lots.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Input
            value={search}
            onChange={setSearch}
            placeholder="Search grade, type, location, mill or coil"
            className="w-72"
          />
          <Button onClick={reload}>Refresh</Button>
        </div>
      </header>

      {error && <ErrorNote message={error} />}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi label="On hand" value={`${Math.round(totalMt).toLocaleString("en-IN")} MT`} hint={`${data?.length ?? 0} specs`} />
        <Kpi label="Stock value" value={inrShort(totalValue)} hint="at landed cost" tone="brand" />
        <Kpi
          label="Over 90 days"
          value={`${Math.round(deadMt).toLocaleString("en-IN")} MT`}
          hint={`${dead.length} spec${dead.length === 1 ? "" : "s"} ageing`}
          tone={deadMt > 0 ? "warn" : "default"}
        />
        <Kpi label="Locations" value={String(locations)} hint="holding stock" />
      </div>

      {data && data.length > 0 && (
        <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
          <Card title="By product type" subtitle="Balance tonnage">
            <HBarChart data={byProductType(data)} unit="MT" />
          </Card>
          <Card title="By age" subtitle="Where the tonnage is sitting">
            <DonutChart
              data={byAgeing(data)}
              centerValue={`${Math.round(totalMt).toLocaleString("en-IN")}`}
              centerLabel="MT on hand"
            />
          </Card>
        </div>
      )}

      <Card padded={false}>
        {loading && !data ? (
          <Loading />
        ) : filtered.length === 0 ? (
          <Empty message="No stock matches." />
        ) : (
          <div className="max-h-[70vh] overflow-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 z-10 border-b border-rule bg-sunk text-left text-xs uppercase tracking-wide text-ink-faint">
                <tr>
                  <th className="w-8 px-2 py-2" />
                  <th className="px-4 py-2 font-medium">Grade</th>
                  <th className="px-4 py-2 font-medium">Type</th>
                  <th className="px-4 py-2 font-medium">Specification</th>
                  <th className="px-4 py-2 font-medium">Locations</th>
                  <th className="px-4 py-2 text-right font-medium">Balance qty</th>
                  <th className="px-4 py-2 text-right font-medium">Bal. NOP</th>
                  <th className="px-4 py-2 text-right font-medium">Avg landed /kg</th>
                  <th className="px-4 py-2 text-right font-medium">Lots</th>
                  <th className="px-4 py-2 text-right font-medium">Ageing</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-sunk">
                {filtered.map((row) => {
                  const key = specKey(row);
                  const open = expanded.has(key);
                  return [
                    <tr
                      key={key}
                      onClick={() => toggle(key)}
                      className={`cursor-pointer hover:bg-sunk ${open ? "bg-sunk" : ""}`}
                    >
                      <td className="px-2 py-2 text-center text-ink-400">{open ? "▾" : "▸"}</td>
                      <td className="px-4 py-2 font-mono text-xs">{row.grade ?? "—"}</td>
                      <td className="px-4 py-2 text-ink-soft">{row.product_type ?? "—"}</td>
                      <td className="px-4 py-2 text-ink-soft">{row.display_name}</td>
                      <td className="px-4 py-2 text-ink-soft">
                        {row.locations.join(", ") || "—"}
                      </td>
                      <td className="tabular px-4 py-2 text-right">
                        {num(row.balance_qty_mt)}
                        <span className="ml-1 text-xs text-ink-faint">MT</span>
                      </td>
                      <td className="tabular px-4 py-2 text-right">{num(row.balance_nop, 0)}</td>
                      <td className="tabular px-4 py-2 text-right">
                        {rate(row.avg_landed_cost_per_kg)}
                      </td>
                      <td className="tabular px-4 py-2 text-right">{row.lot_count}</td>
                      <td className="tabular px-4 py-2 text-right text-ink-faint">
                        {row.ageing_min_days === null
                          ? "—"
                          : row.ageing_min_days === row.ageing_max_days
                            ? `${row.ageing_min_days}d`
                            : `${row.ageing_min_days}-${row.ageing_max_days}d`}
                      </td>
                    </tr>,
                    open ? (
                      <tr key={`${key}-lots`}>
                        <td colSpan={10} className="p-0">
                          <LotTable lots={row.lots} />
                        </td>
                      </tr>
                    ) : null,
                  ];
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
