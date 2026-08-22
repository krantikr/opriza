import { useRef, useState } from "react";

import { api, useApi } from "../api/client";
import type { StockHold, StockImportResult, StockItem, StockSummary } from "../api/types";
import { HoldsPanel, StockAdjustDialog } from "../components/StockAdjust";
import {
  Banner,
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
function LotTable({ lots, onAdjust }: { lots: StockItem[]; onAdjust: (lot: StockItem) => void }) {
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
            <th className="py-1 pr-4 text-right font-medium">Stock date</th>
            <th className="py-1 text-right font-medium" />
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
              <td className="tabular py-1.5 pr-4 text-right text-ink-faint">
                {day(lot.stock_date)}
              </td>
              <td className="py-1.5 text-right">
                <button
                  type="button"
                  onClick={() => onAdjust(lot)}
                  className="rounded-lg px-2 py-1 text-xs font-medium text-brand transition-colors hover:bg-brand-wash"
                >
                  Update
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The "Replace from Excel" control - the button only.

    The outcome is deliberately not rendered here: this sits in a flex row
    beside the search field, and a full-width result banner as a sibling would
    wedge itself between the controls. The parent owns the result and draws it
    under the header, where a multi-line report belongs.

    The file replaces the stock list rather than merging into it, so the label
    says "Replace" rather than "Upload": a trader should know what the action
    does before picking a file, not discover it afterwards. */
function StockUpload({
  busy,
  onPicked,
}: {
  busy: boolean;
  onPicked: (file: File) => void;
}) {
  const input = useRef<HTMLInputElement>(null);

  return (
    <>
      <input
        ref={input}
        type="file"
        accept=".xlsx,.xlsm,.xls"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) onPicked(file);
          // Cleared so re-picking the same file after correcting it still fires
          // a change event; without this the second attempt looks like a dead
          // button.
          e.target.value = "";
        }}
      />
      <Button disabled={busy} onClick={() => input.current?.click()}>
        {busy ? "Importing…" : "Replace from Excel"}
      </Button>
    </>
  );
}

/** What one import did: lots loaded, and every row that was rejected with its
    row number, because a partly-loaded file is the normal case with real
    spreadsheets and a bare "done" would hide it. */
function ImportReport({ result }: { result: StockImportResult }) {
  return (
    <Banner tone={result.rows_failed > 0 ? "attention" : "settled"}>
      {result.rows_imported} lot{result.rows_imported === 1 ? "" : "s"} loaded from{" "}
      {result.source_file}
      {result.rows_failed > 0 && ` · ${result.rows_failed} row(s) rejected`}
      {result.errors.length > 0 && (
        <ul className="mt-1.5 list-disc pl-4 text-xs">
          {result.errors.slice(0, 5).map((err, i) => (
            <li key={i}>
              Row {err.row}: {err.error}
            </li>
          ))}
          {result.errors.length > 5 && <li>…and {result.errors.length - 5} more</li>}
        </ul>
      )}
    </Banner>
  );
}

export default function Stock() {
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const { data, error, loading, reload } = useApi<StockSummary[]>(`/stock/summary`);
  const holds = useApi<StockHold[]>("/stock/holds", 60_000);
  const [adjusting, setAdjusting] = useState<StockItem | null>(null);
  const [showHolds, setShowHolds] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<StockImportResult | null>(null);
  const [importError, setImportError] = useState<string | null>(null);

  function refreshAll() {
    reload();
    holds.reload();
  }

  async function importStock(file: File) {
    setImporting(true);
    setImportError(null);
    setImportResult(null);
    try {
      setImportResult(await api.upload<StockImportResult>("/stock/import", file));
      refreshAll();
    } catch (e) {
      setImportError((e as Error).message);
    } finally {
      setImporting(false);
    }
  }

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
  const heldMt = (holds.data ?? []).reduce(
    (sum, h) => sum + Number(h.quantity_kg) / 1000,
    0,
  );

  return (
    <div className="flex flex-col gap-4 p-4 sm:p-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-ink">Stock on hand</h1>
          <p className="text-sm text-ink-faint">
            {data ? `${data.length} spec${data.length === 1 ? "" : "s"}` : "…"} across{" "}
            {data ? `${lotTotal} lot${lotTotal === 1 ? "" : "s"}` : "…"} · balance after existing
            orders. Expand a row for the individual lots.
          </p>
        </div>
        {/* The search field is the only element here that may give up width:
            it flexes down to a usable minimum while the two buttons keep their
            natural size, so a narrow window shortens the input instead of
            breaking the buttons apart. */}
        <div className="flex flex-1 items-center justify-end gap-2">
          <Input
            value={search}
            onChange={setSearch}
            placeholder="Search grade, type, location, mill or coil"
            className="w-full min-w-40 max-w-72"
          />
          <StockUpload busy={importing} onPicked={importStock} />
          <Button onClick={reload}>Refresh</Button>
        </div>
      </header>

      {error && <ErrorNote message={error} />}
      {importError && <ErrorNote message={importError} />}
      {importResult && <ImportReport result={importResult} />}

      <div className="grid grid-cols-2 gap-2 sm:gap-3 xl:grid-cols-4">
        <Kpi label="On hand" value={`${Math.round(totalMt).toLocaleString("en-IN")} MT`} hint={`${data?.length ?? 0} specs`} />
        <Kpi label="Stock value" value={inrShort(totalValue)} hint="at landed cost" tone="brand" />
        <Kpi
          label="Over 90 days"
          value={`${Math.round(deadMt).toLocaleString("en-IN")} MT`}
          hint={`${dead.length} spec${dead.length === 1 ? "" : "s"} ageing`}
          tone={deadMt > 0 ? "warn" : "default"}
        />
        <Kpi
          label="Held back"
          value={`${Math.round(heldMt).toLocaleString("en-IN")} MT`}
          hint={locations > 0 ? `across ${locations} location${locations === 1 ? "" : "s"}` : undefined}
          tone={heldMt > 0 ? "warn" : "default"}
        />
      </div>

      {(holds.data?.length ?? 0) > 0 && (
        <Card
          title="Held back from quoting"
          subtitle={`${holds.data!.length} hold${holds.data!.length === 1 ? "" : "s"} · this tonnage is on hand but not offered`}
          padded={false}
          action={
            <Button onClick={() => setShowHolds((v) => !v)}>
              {showHolds ? "Hide" : "Show"}
            </Button>
          }
        >
          {showHolds && <HoldsPanel holds={holds.data!} onChanged={refreshAll} />}
        </Card>
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
                          <LotTable lots={row.lots} onAdjust={setAdjusting} />
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

      {adjusting && (
        <StockAdjustDialog
          lot={adjusting}
          onClose={() => setAdjusting(null)}
          onSaved={refreshAll}
        />
      )}
    </div>
  );
}
