import { useRef, useState } from "react";

import { api, useApi } from "../api/client";
import type {
  PriorityProduct,
  StockHold,
  StockImportResult,
  StockItem,
  StockPosition,
  StockSummary,
} from "../api/types";
import AddStock from "../components/AddStock";
import { HoldsPanel, StockAdjustDialog } from "../components/StockAdjust";
import {
  Banner,
  Button,
  Card,
  Empty,
  ErrorNote,
  Input,
  Kpi,
  Loading,
  num,
} from "../components/ui";

/** A spec's lots may span more than one mill; priority is settable only when
 *  every lot in the group agrees on a grade+make, since that is the only
 *  case where "toggle this row" points at one unambiguous product. */
function solePriorityKey(row: StockSummary): { grade: string; make: string } | null {
  if (!row.grade) return null;
  const makes = new Set(row.lots.map((l) => l.make).filter(Boolean));
  if (makes.size !== 1) return null;
  return { grade: row.grade, make: [...makes][0] as string };
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

/** Whole tonnes, grouped the way the desk reads numbers. */
function mt(value: string | number | null | undefined): string {
  return Math.round(Number(value ?? 0)).toLocaleString("en-IN");
}

export default function Stock() {
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const { data, error, loading, reload } = useApi<StockSummary[]>(`/stock/summary`);
  /* The demand side. Fetched separately so a slow join over quotations never
     delays the stock list itself, which is what the page is mostly used for. */
  const positionApi = useApi<StockPosition>("/stock/position");
  const position = positionApi.data;

  const priorityApi = useApi<PriorityProduct[]>("/priority-products");
  const priorityId = (grade: string, make: string) =>
    priorityApi.data?.find((p) => p.grade === grade && p.make === make)?.id;

  async function togglePriorityProduct(grade: string, make: string, on: boolean) {
    if (on) {
      await api.post("/priority-products", { grade, make });
    } else {
      const id = priorityId(grade, make);
      if (id) await api.del(`/priority-products/${id}`);
    }
    priorityApi.reload();
    reload();
  }

  /* Matched on grade and the three dimensions rather than the product word:
     the server groups "Plate" and "C-45 Plates" together, and matching on the
     raw type here would fail to find exactly the rows that were merged. */
  const positionFor = (row: StockSummary) =>
    position?.specs.find(
      (p) =>
        (p.grade ?? "") === (row.grade ?? "") &&
        p.thickness_mm === row.thickness_mm &&
        p.width_mm === row.width_mm &&
        p.length_mm === row.length_mm,
    );
  const holds = useApi<StockHold[]>("/stock/holds", 60_000);
  const [adjusting, setAdjusting] = useState<StockItem | null>(null);
  const [adding, setAdding] = useState(false);
  const [showHolds, setShowHolds] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState<StockImportResult | null>(null);
  const [importError, setImportError] = useState<string | null>(null);

  function refreshAll() {
    reload();
    holds.reload();
    positionApi.reload();
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

  /* Ageing keeps a mention but loses its tile. It is money sitting still and
     worth knowing, but it is not one of the four figures a trader decides
     from - and giving it equal billing was part of what made the page read
     as a report rather than a working screen. */
  const dead = (data ?? []).filter((r) => (r.ageing_max_days ?? 0) > 90);
  const deadMt = dead.reduce((sum, r) => sum + Number(r.balance_qty_mt), 0);

  return (
    <div className="flex flex-col gap-4 p-4 sm:p-5">
      {/* Search left, actions right - the same shape as the Inbox and the
          quotations list. What is left of the old subtitle is the count
          itself, kept because nothing else on this page states how much
          stock there is; the sentence around it went. */}
      <header className="flex flex-wrap items-center justify-between gap-3">
        {/* Search leads, as on every other list screen. It is also the only
            element that gives up width, flexing down to a usable minimum so a
            narrow window shortens the input rather than breaking the buttons
            apart. */}
        <Input
          value={search}
          onChange={setSearch}
          placeholder="Search grade, type, location, mill or coil"
          className="w-full min-w-40 max-w-72 flex-1"
        />
        <div className="flex shrink-0 items-center gap-2">
          <p className="text-sm text-ink-soft">
            {data ? `${data.length} spec${data.length === 1 ? "" : "s"}` : "…"} ·{" "}
            {data ? `${lotTotal} lot${lotTotal === 1 ? "" : "s"}` : "…"}
          </p>
          <Button variant="primary" onClick={() => setAdding(true)}>
            Add stock
          </Button>
          <StockUpload busy={importing} onPicked={importStock} />
          <Button onClick={refreshAll}>Refresh</Button>
        </div>
      </header>

      {error && <ErrorNote message={error} />}
      {importError && <ErrorNote message={importError} />}
      {importResult && <ImportReport result={importResult} />}

      {/* The position, not the cost sheet.
          What a trader decides from is the relationship between three
          numbers - held, owed, short - and the old row showed none of them:
          it led with stock value and ageing, which answer questions nobody
          opens this page to ask. "To buy" is the one that costs money to get
          wrong, so it is given its own tone the moment it is non-zero. */}
      <div className="grid grid-cols-2 gap-2 sm:gap-3 xl:grid-cols-4">
        <Kpi
          label="In stock"
          value={`${mt(position?.in_stock_mt)} MT`}
          hint={`${position?.specs.length ?? 0} specs`}
        />
        <Kpi
          label="To deliver"
          value={`${mt(position?.committed_mt)} MT`}
          hint="accepted, not yet despatched"
        />
        <Kpi
          label="Free to sell"
          value={`${mt(position?.free_mt)} MT`}
          hint="on hand and not owed"
          tone="brand"
        />
        <Kpi
          label="To buy"
          value={`${mt(position?.to_buy_mt)} MT`}
          hint={
            (position?.specs_short ?? 0) > 0
              ? `${position!.specs_short} spec${position!.specs_short === 1 ? "" : "s"} short`
              : "nothing short"
          }
          tone={Number(position?.to_buy_mt ?? 0) > 0 ? "warn" : "default"}
        />
      </div>

      <p className="text-xs text-ink-faint">
        {Number(position?.prospective_mt ?? 0) > 0 && (
          <>
            A further{" "}
            <span className="font-medium text-ink-soft">
              {mt(position?.prospective_mt)} MT
            </span>{" "}
            is quoted and still with customers — not counted as owed, because a
            quotation is not an order.
          </>
        )}
        {deadMt > 0 && (
          <>
            {Number(position?.prospective_mt ?? 0) > 0 && " "}
            <span className="font-medium text-ink-soft">{mt(deadMt)} MT</span> has
            been on the floor over 90 days.
          </>
        )}
      </p>

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
                  {/* Five columns, down from nine. Grade, type and
                      specification all described the same material three
                      times over, and NOP, average landed cost, lot count and
                      ageing are per-lot facts that belong in the expanded
                      view - which is where they still are. What replaces them
                      is the demand side, which was not shown at all. */}
                  {/* Location is a column, not a suffix on the material.
                      Codes like "788" sat beside a column of tonnages and
                      read as a quantity - the one thing a number in this
                      table must never be mistaken for.

                      Every quantity heading carries MT, and the price says
                      what it is per: a bare figure on a commercial screen
                      leaves the reader to infer the unit, which is exactly
                      the inference that must not be left to them. */}
                  <th className="w-8 px-2 py-2" />
                  <th className="w-8 px-2 py-2" />
                  <th className="px-4 py-2 font-medium">Material</th>
                  <th className="px-4 py-2 font-medium">Location</th>
                  <th className="px-4 py-2 text-right font-medium">In stock (MT)</th>
                  <th className="px-4 py-2 text-right font-medium">To deliver (MT)</th>
                  <th className="px-4 py-2 text-right font-medium">Free (MT)</th>
                  <th className="px-4 py-2 text-right font-medium">To buy (MT)</th>
                  <th className="px-4 py-2 text-right font-medium">Cost (₹/MT)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-sunk">
                {filtered.map((row) => {
                  const key = specKey(row);
                  const open = expanded.has(key);
                  const demand = positionFor(row);
                  const owed = Number(demand?.committed_mt ?? 0);
                  const buy = Number(demand?.to_buy_mt ?? 0);
                  // Falls back to the plain balance when the position has no
                  // row for this spec, so the column is never blank.
                  const free = Number(demand?.free_mt ?? row.balance_qty_mt);
                  const solePriority = solePriorityKey(row);
                  return [
                    <tr
                      key={key}
                      onClick={() => toggle(key)}
                      className={`cursor-pointer hover:bg-sunk ${
                        row.is_priority ? "bg-attention-wash/40" : ""
                      } ${open ? "bg-sunk" : ""}`}
                    >
                      <td className="px-2 py-2 text-center">
                        {solePriority ? (
                          <button
                            type="button"
                            title={
                              row.is_priority
                                ? `Priority (${solePriority.grade} / ${solePriority.make})`
                                : `Mark ${solePriority.grade} / ${solePriority.make} as priority`
                            }
                            onClick={(e) => {
                              e.stopPropagation();
                              togglePriorityProduct(
                                solePriority.grade,
                                solePriority.make,
                                !row.is_priority,
                              );
                            }}
                            className={row.is_priority ? "text-attention" : "text-ink-faint hover:text-attention"}
                          >
                            ★
                          </button>
                        ) : row.is_priority ? (
                          <span className="text-attention" title="Priority (mixed makes in this spec)">
                            ★
                          </span>
                        ) : null}
                      </td>
                      <td className="px-2 py-2 text-center text-ink-400">{open ? "▾" : "▸"}</td>
                      <td className="px-4 py-2">
                        <span className="text-ink">{row.display_name}</span>
                        {row.lot_count > 1 && (
                          <span className="ml-2 text-xs text-ink-faint">
                            {row.lot_count} lots
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-2 text-xs text-ink-soft">
                        {row.locations.join(", ") || "—"}
                      </td>
                      <td className="tabular px-4 py-2 text-right">{num(row.balance_qty_mt)}</td>
                      <td className="tabular px-4 py-2 text-right text-ink-soft">
                        {owed > 0 ? num(owed) : "—"}
                      </td>
                      <td className="tabular px-4 py-2 text-right">{num(free)}</td>
                      {/* The only figure that changes colour. A shortfall is
                          an action, not a statistic. */}
                      <td
                        className={`tabular px-4 py-2 text-right ${
                          buy > 0 ? "font-semibold text-attention-ink" : "text-ink-faint"
                        }`}
                      >
                        {buy > 0 ? num(buy) : "—"}
                      </td>
                      <td className="tabular px-4 py-2 text-right text-ink-soft">
                        {demand?.cost_per_mt
                          ? Math.round(Number(demand.cost_per_mt)).toLocaleString("en-IN")
                          : "—"}
                      </td>
                    </tr>,
                    open ? (
                      <tr key={`${key}-lots`}>
                        <td colSpan={9} className="p-0">
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

      {adding && (
        <AddStock onClose={() => setAdding(false)} onSaved={refreshAll} />
      )}

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
