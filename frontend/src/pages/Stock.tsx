import { useState } from "react";

import { useApi } from "../api/client";
import type { StockItem, StockSummary } from "../api/types";
import { HBarChart, type BarDatum } from "../components/charts";
import { Card, Empty, ErrorNote, Loading, num } from "../components/ui";

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
    <div className="overflow-x-auto border-y border-ink-200 bg-ink-50/60 px-4 py-3">
      <table className="w-full min-w-5xl text-xs">
        <thead className="text-left uppercase tracking-wide text-ink-500">
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
        <tbody className="divide-y divide-ink-200/70">
          {lots.map((lot) => (
            <tr key={lot.id} className="text-ink-700">
              <td className="py-1.5 pr-4">{lot.location ?? "—"}</td>
              <td className="py-1.5 pr-4">{lot.make ?? "—"}</td>
              <td className="py-1.5 pr-4 font-mono">{lot.coil_no ?? "—"}</td>
              <td className="tabular py-1.5 pr-4 text-right">{num(lot.nop, 0)}</td>
              <td className="tabular py-1.5 pr-4 text-right">{num(lot.qty_kg, 0)}</td>
              <td className="tabular py-1.5 pr-4 text-right">{num(lot.balance_nop, 0)}</td>
              <td className="tabular py-1.5 pr-4 text-right font-medium text-ink-900">
                {num(lot.balance_qty_kg, 0)}
              </td>
              <td className="tabular py-1.5 pr-4 text-right">{rate(lot.purchase_rate_per_kg)}</td>
              <td className="tabular py-1.5 pr-4 text-right">{rate(lot.landed_cost_per_kg)}</td>
              <td className="tabular py-1.5 pr-4 text-right">
                {lot.ageing_days === null ? "—" : `${lot.ageing_days}d`}
              </td>
              <td className="tabular py-1.5 text-right text-ink-500">{day(lot.stock_date)}</td>
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

  const { data, error, loading } = useApi<StockSummary[]>(`/stock/summary`);

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

  return (
    <div className="space-y-4 p-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink-900">Stock on hand</h1>
          <p className="text-sm text-ink-500">
            {data ? `${data.length} spec${data.length === 1 ? "" : "s"}` : "…"} across{" "}
            {data ? `${lotTotal} lot${lotTotal === 1 ? "" : "s"}` : "…"} · balance quantity after
            existing orders. Expand a row for the individual lots.
          </p>
        </div>
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search grade, type, location, mill or coil"
          className="w-72 rounded-lg border border-ink-300 bg-white px-3 py-1.5 text-sm"
        />
      </header>

      {error && <ErrorNote message={error} />}

      {data && data.length > 0 && (
        <Card title="Stock on hand by product type (MT)">
          <HBarChart data={byProductType(data)} unit="MT" />
        </Card>
      )}

      <Card className="overflow-hidden">
        {loading && !data ? (
          <Loading />
        ) : filtered.length === 0 ? (
          <Empty message="No stock matches." />
        ) : (
          <div className="-m-4 max-h-[70vh] overflow-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 z-10 border-b border-ink-200 bg-ink-50 text-left text-xs uppercase tracking-wide text-ink-500">
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
              <tbody className="divide-y divide-ink-100">
                {filtered.map((row) => {
                  const key = specKey(row);
                  const open = expanded.has(key);
                  return [
                    <tr
                      key={key}
                      onClick={() => toggle(key)}
                      className={`cursor-pointer hover:bg-ink-50 ${open ? "bg-ink-50" : ""}`}
                    >
                      <td className="px-2 py-2 text-center text-ink-400">{open ? "▾" : "▸"}</td>
                      <td className="px-4 py-2 font-mono text-xs">{row.grade ?? "—"}</td>
                      <td className="px-4 py-2 text-ink-700">{row.product_type ?? "—"}</td>
                      <td className="px-4 py-2 text-ink-700">{row.display_name}</td>
                      <td className="px-4 py-2 text-ink-700">
                        {row.locations.join(", ") || "—"}
                      </td>
                      <td className="tabular px-4 py-2 text-right">
                        {num(row.balance_qty_mt)}
                        <span className="ml-1 text-xs text-ink-500">MT</span>
                      </td>
                      <td className="tabular px-4 py-2 text-right">{num(row.balance_nop, 0)}</td>
                      <td className="tabular px-4 py-2 text-right">
                        {rate(row.avg_landed_cost_per_kg)}
                      </td>
                      <td className="tabular px-4 py-2 text-right">{row.lot_count}</td>
                      <td className="tabular px-4 py-2 text-right text-ink-500">
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
