import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api, query, useApi } from "../api/client";
import type { LineItem, NotSentReason, Page, Quotation, QuotationStage } from "../api/types";
import QuotationDetailPanel from "../components/QuotationDetailPanel";
import {
  ago,
  Button,
  Empty,
  ErrorNote,
  inrShort,
  Loading,
  num,
  Pagination,
  SearchInput,
  Select,
  when,
} from "../components/ui";

/* ---------------------------------------------------------------------------
   Quotations: a mill-sheet-style table, with the open one in a drawer over it.

   One row per material, not per quotation - a quotation with three line
   items is three rows, with the customer/status/raised cells merged down the
   group. Same shape a trader already reads on a supplier's weight sheet.

   Selecting a row still changes the URL, so an individual quotation stays
   linkable and the back button behaves.
   --------------------------------------------------------------------------- */

const PAGE_SIZE = 20;

const PERIODS = [
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last quarter" },
  { value: "180", label: "Last 6 months" },
  { value: "365", label: "Last year" },
  { value: "all", label: "All time" },
];

/** The six working stages, mirrored from `stages.py::COMMERCIAL_STAGES`.
 *  Duplicated rather than fetched for the same reason the detail drawer's
 *  stage picker duplicates it: a round trip to render six tabs would leave
 *  them blank for a moment on every load, and the server remains the
 *  authority - it rejects a stage it does not know. */
const STAGES: { key: QuotationStage; label: string }[] = [
  { key: "received", label: "Received" },
  { key: "sent", label: "Sent" },
  { key: "negotiation", label: "Negotiation" },
  { key: "delivery_pending", label: "Delivery pending" },
  { key: "payment_pending", label: "Payment pending" },
  { key: "completed", label: "Completed" },
];

/** One colour per stage, so the dropdown reads before its label does -
 *  amber while waiting on the desk, blue while out with the customer,
 *  settling to green once the money is in. */
const STAGE_COLOR: Record<QuotationStage, string> = {
  received: "text-attention-ink",
  sent: "text-brand-ink",
  negotiation: "text-info-ink",
  delivery_pending: "text-attention-ink",
  payment_pending: "text-attention-ink",
  completed: "text-settled-ink",
};

const REASONS: { key: NotSentReason; label: string }[] = [
  { key: "PENDING_MARKET_RATE", label: "Pending rates from market" },
  { key: "PENDING_CUSTOMER_RATE", label: "Pending customer rate" },
  { key: "PENDING_HEAD_APPROVAL", label: "Pending head approval" },
];

/** Stable hue per customer, matching the chase board and the Inbox: the same
 *  buyer is always the same colour on every screen. */
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

/** thickness x width x length, or OD x thickness for round stock - the same
 *  formatting `StockItem.dimension_text` uses server-side. */
function sizeText(item: LineItem): string {
  if (item.diameter_mm) {
    const base = `OD ${item.diameter_mm}mm`;
    return item.thickness_mm ? `${base} x ${item.thickness_mm}mm` : base;
  }
  const dims = [item.thickness_mm, item.width_mm, item.length_mm].filter(
    (d): d is number => d != null,
  );
  return dims.length ? `${dims.join(" x ")} mm` : "—";
}

function pcsText(item: LineItem): string {
  if (item.quantity_unit !== "PCS" || !item.quantity) return "—";
  return num(item.quantity, 0);
}

/** One material line within a quotation's row-group. `first` carries the
 *  quotation-level cells (customer, status, raised), rendered with a rowSpan
 *  covering the whole group; later rows omit them entirely. */
function LineRow({
  q,
  item,
  rowSpan,
  selected,
  onOpen,
  stage,
  onStageChange,
  onReasonChange,
}: {
  q: Quotation;
  item: LineItem;
  rowSpan: number | null;
  selected: boolean;
  onOpen: () => void;
  stage: QuotationStage | null;
  onStageChange: (stage: QuotationStage) => void;
  onReasonChange: (reason: NotSentReason | null) => void;
}) {
  const who = q.customer_company || q.customer_name || "Unknown";
  const hue = hueFor(who);
  const priority = q.is_priority_customer || q.is_priority_product;

  return (
    <tr
      className={`border-b border-rule align-top last:border-0 ${
        selected ? "bg-brand-wash" : priority ? "bg-attention-wash/30 hover:bg-attention-wash/50" : "hover:bg-ground"
      }`}
    >
      {rowSpan !== null && (
        <td
          rowSpan={rowSpan}
          onClick={onOpen}
          className={`relative cursor-pointer border-r border-rule py-2.5 pl-3 pr-3 align-top ${
            priority ? "bg-attention-wash/20" : ""
          }`}
        >
          {priority && (
            <span
              className="absolute inset-y-0 left-0 w-1 bg-attention"
              aria-hidden
              title="Priority"
            />
          )}
          <div className="flex items-start gap-2.5">
            <span
              className="mt-0.5 grid size-6 shrink-0 place-items-center rounded-full text-[10px] font-semibold text-white"
              style={{ background: `hsl(${hue} 62% 45%)` }}
            >
              {initials(who)}
            </span>
            <span className="min-w-0">
              <span className="flex items-center gap-1.5">
                <span className="truncate text-[13.5px] font-semibold text-ink">{who}</span>
                {priority && <span className="shrink-0 text-attention" title="Priority">★</span>}
                {q.requires_manual_review && (
                  <span
                    className="size-1.5 shrink-0 rounded-full bg-attention"
                    title="Flagged for review"
                  />
                )}
              </span>
              <span className="block truncate text-[11.5px] text-ink-faint">
                {q.customer_email ?? "no address on file"}
              </span>
            </span>
          </div>
        </td>
      )}

      <td className="cursor-pointer px-3 py-2 text-[13px] text-ink" onClick={onOpen}>
        {item.grade ?? "—"}
      </td>
      <td className="cursor-pointer px-3 py-2 text-[13px] text-ink-soft" onClick={onOpen}>
        {item.product_type ?? "—"}
      </td>
      <td className="cursor-pointer px-3 py-2 text-[13px] text-ink-soft" onClick={onOpen}>
        {sizeText(item)}
      </td>
      <td className="tabular cursor-pointer px-3 py-2 text-right text-[13px] text-ink" onClick={onOpen}>
        {item.quantity_mt ? num(item.quantity_mt) : "—"}
      </td>
      <td className="tabular cursor-pointer px-3 py-2 text-right text-[13px] text-ink-soft" onClick={onOpen}>
        {pcsText(item)}
      </td>
      <td className="cursor-pointer px-3 py-2 text-[13px] text-ink-soft" onClick={onOpen}>
        {item.matched_stock_item_make ?? "—"}
      </td>

      {rowSpan !== null && (
        <td
          rowSpan={rowSpan}
          className="cursor-pointer border-l border-rule px-3 py-2 text-right align-top"
          onClick={onOpen}
        >
          {(q.total_suggested_value ?? 0) as number > 0 ? (
            <span className="whitespace-nowrap text-[13px] font-semibold text-ink">
              {inrShort(q.total_suggested_value)}
            </span>
          ) : (
            <span className="text-ink-faint">—</span>
          )}
        </td>
      )}

      {rowSpan !== null && (
        <td rowSpan={rowSpan} className="border-l border-rule px-3 py-2 align-top">
          <select
            value={stage ?? ""}
            onClick={(e) => e.stopPropagation()}
            onChange={(e) => onStageChange(e.target.value as QuotationStage)}
            className={`rounded-md border border-rule bg-surface px-1.5 py-1 text-[11.5px] font-medium focus:border-brand focus:outline-none ${
              stage ? STAGE_COLOR[stage] : "text-ink"
            }`}
          >
            {!stage && <option value="">—</option>}
            {STAGES.map((s) => (
              <option key={s.key} value={s.key}>
                {s.label}
              </option>
            ))}
          </select>
          {stage === "received" && (
            <select
              value={q.not_sent_reason ?? ""}
              onClick={(e) => e.stopPropagation()}
              onChange={(e) =>
                onReasonChange((e.target.value || null) as NotSentReason | null)
              }
              className="mt-1 block rounded-md border border-rule bg-surface px-1.5 py-1 text-[11px] text-ink-soft focus:border-brand focus:outline-none"
            >
              <option value="">Why not sent…</option>
              {REASONS.map((r) => (
                <option key={r.key} value={r.key}>
                  {r.label}
                </option>
              ))}
            </select>
          )}
        </td>
      )}

      {rowSpan !== null && (
        <td rowSpan={rowSpan} className="px-3 py-2 pr-4 text-right align-top">
          <span
            className="block whitespace-nowrap text-[12.5px] tabular-nums text-ink-soft"
            title={when(q.sent_at ?? q.created_at)}
          >
            {ago(q.sent_at ?? q.created_at)}
          </span>
        </td>
      )}
    </tr>
  );
}

export default function Quotations() {
  const { id } = useParams();
  const navigate = useNavigate();

  const [stage, setStage] = useState<QuotationStage | "all">("all");
  // Remembered so a reason card can force the filter to "received" and hand
  // it back on deselect, instead of leaving the list stuck there.
  const [stageBeforeReason, setStageBeforeReason] = useState<QuotationStage | "all">("all");
  // "pending" is every received quotation regardless of reason (or with none
  // set yet); a specific reason key narrows further, within that same group.
  const [reasonFilter, setReasonFilter] = useState<NotSentReason | "pending" | null>(null);
  const [days, setDays] = useState("30");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const { data, error, loading, reload } = useApi<Page<Quotation>>(
    `/quotations${query({ search, limit: 200 })}`,
    30_000,
  );

  // Newest received first, regardless of what order the API happens to
  // return - the list is refetched and refiltered client-side often enough
  // (stage moves, reason changes) that this must not depend on the fetch.
  const all = useMemo(() => {
    const rows = data?.items ?? [];
    return [...rows].sort(
      (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
    );
  }, [data]);

  const periodFiltered = useMemo(() => {
    if (days === "all") return all;
    const cutoff = Date.now() - Number(days) * 24 * 60 * 60 * 1000;
    return all.filter((q) => new Date(q.created_at).getTime() >= cutoff);
  }, [all, days]);

  const countFor = (key: QuotationStage | "all") =>
    key === "all" ? periodFiltered.length : periodFiltered.filter((q) => q.stage === key).length;

  const stageFiltered = useMemo(
    () => (stage === "all" ? periodFiltered : periodFiltered.filter((q) => q.stage === stage)),
    [periodFiltered, stage],
  );

  const tonnesOf = (q: Quotation) =>
    q.line_items.reduce((sum, item) => sum + Number(item.quantity_mt ?? 0), 0);

  /** Count and tonnage for "everything still pending" and for each named
   *  reason, all scoped to the received stage - the group the cards act on. */
  const pending = useMemo(() => {
    const received = periodFiltered.filter((q) => q.stage === "received");
    const totals = (rows: Quotation[]) => ({
      count: rows.length,
      tonnes: rows.reduce((sum, q) => sum + tonnesOf(q), 0),
    });
    const byReason: Record<string, { count: number; tonnes: number }> = {};
    for (const r of REASONS) {
      byReason[r.key] = totals(received.filter((q) => q.not_sent_reason === r.key));
    }
    return { all: totals(received), byReason };
  }, [periodFiltered]);

  const filtered = useMemo(() => {
    if (reasonFilter === "pending") return stageFiltered.filter((q) => q.stage === "received");
    if (reasonFilter) return stageFiltered.filter((q) => q.not_sent_reason === reasonFilter);
    return stageFiltered;
  }, [stageFiltered, reasonFilter]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const pageRows = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const selectedId = id ? Number(id) : null;

  // Escape closes the drawer, matching every other overlay in the app.
  useEffect(() => {
    if (selectedId === null) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") navigate("/quotations");
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selectedId, navigate]);

  useEffect(() => setPage(1), [stage, reasonFilter, search, days]);

  async function exportXlsx() {
    setExporting(true);
    setExportError(null);
    try {
      // Exports what you are looking at, not the whole table: a filtered view
      // that silently exports everything is worse than no export.
      await api.download(
        `/quotations/export${query({
          search,
          stage: stage === "all" ? undefined : stage,
          days: days === "all" ? undefined : days,
        })}`,
        "quotations.xlsx",
      );
    } catch (e) {
      setExportError((e as Error).message);
    } finally {
      setExporting(false);
    }
  }

  async function moveStage(quotationId: number, next: QuotationStage) {
    await api.post(`/quotations/${quotationId}/stage`, { stage: next });
    reload();
  }

  async function setReason(quotationId: number, next: NotSentReason | null) {
    await api.post(`/quotations/${quotationId}/not-sent-reason`, { not_sent_reason: next });
    reload();
  }

  /** A reason card forces the stage filter to "received" so its count is
   *  what the table then shows; deselecting it must hand that filter back
   *  to whatever it was before, not leave the list stuck on "received". */
  function toggleReasonCard(key: NotSentReason | "pending") {
    setReasonFilter((cur) => {
      if (cur === key) {
        setStage(stageBeforeReason);
        return null;
      }
      if (cur === null) setStageBeforeReason(stage);
      setStage("received");
      return key;
    });
  }

  return (
    <div className="flex flex-col gap-3 p-5">
      <header className="flex flex-wrap items-center gap-2">
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder="Search by customer, material or number…"
          className="w-full sm:w-72"
        />
        <div className="ml-auto flex items-center gap-2">
          <Select value={days} onChange={setDays} options={PERIODS} className="py-1.5" />
          <Select
            value={stage}
            onChange={(v) => setStage(v as QuotationStage | "all")}
            options={[
              { value: "all", label: `All (${countFor("all")})` },
              ...STAGES.map((s) => ({
                value: s.key,
                label: `${s.label} (${countFor(s.key)})`,
              })),
            ]}
            className="py-1.5"
          />
          <Button onClick={exportXlsx} disabled={exporting}>
            {exporting ? "Preparing…" : "Export to Excel"}
          </Button>
        </div>
      </header>

      {/* --- Why a quotation hasn't gone out yet --------------------------- */}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <button
          type="button"
          onClick={() => toggleReasonCard("pending")}
          className={`rounded-card border px-3 py-2.5 text-left transition-colors ${
            reasonFilter === "pending"
              ? "border-brand bg-brand-wash"
              : "border-rule bg-surface hover:border-brand/50"
          }`}
        >
          <p className="truncate text-[11px] font-medium uppercase tracking-wide text-ink-faint">
            Quotation pending
          </p>
          <p className="tabular mt-0.5 text-xl font-semibold text-ink">{pending.all.count}</p>
          <p className="tabular text-[11px] text-ink-faint">{num(pending.all.tonnes)} MT</p>
        </button>
        {REASONS.map((r) => (
          <button
            key={r.key}
            type="button"
            onClick={() => toggleReasonCard(r.key)}
            className={`rounded-card border px-3 py-2.5 text-left transition-colors ${
              reasonFilter === r.key
                ? "border-brand bg-brand-wash"
                : "border-rule bg-surface hover:border-brand/50"
            }`}
          >
            <p className="truncate text-[11px] font-medium uppercase tracking-wide text-ink-faint">
              {r.label}
            </p>
            <p className="tabular mt-0.5 text-xl font-semibold text-ink">
              {pending.byReason[r.key]?.count ?? 0}
            </p>
            <p className="tabular text-[11px] text-ink-faint">
              {num(pending.byReason[r.key]?.tonnes ?? 0)} MT
            </p>
          </button>
        ))}
      </div>

      {exportError && <ErrorNote message={exportError} />}
      {error && <ErrorNote message={error} />}

      <div className="overflow-hidden rounded-card border border-rule bg-surface shadow-card">
        {loading && !data ? (
          <Loading label="Loading quotations" />
        ) : pageRows.length === 0 ? (
          <Empty message="Nothing here. New enquiries appear once processed." />
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[64rem] border-collapse">
                <thead>
                  <tr className="border-b border-rule">
                    {[
                      ["Customer", "pl-4 pr-3 text-left"],
                      ["Grade", "px-3 text-left"],
                      ["Type", "px-3 text-left"],
                      ["Size", "px-3 text-left"],
                      ["Weight (MT)", "px-3 text-right"],
                      ["PCS", "px-3 text-right"],
                      ["Make", "px-3 text-left"],
                      ["Price", "px-3 text-right"],
                      ["Status", "px-3 text-left"],
                      ["Raised", "px-3 pr-4 text-right"],
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
                  {pageRows.map((q) => {
                    const items = q.line_items.length > 0 ? q.line_items : [null];
                    return items.map((item, i) => (
                      <LineRow
                        key={item ? item.id : `${q.id}-empty`}
                        q={q}
                        item={
                          item ?? {
                            id: -1,
                            line_no: 0,
                            raw_text: null,
                            product_type: null,
                            grade: null,
                            standard: null,
                            thickness_mm: null,
                            width_mm: null,
                            length_mm: null,
                            diameter_mm: null,
                            quantity: null,
                            quantity_unit: "UNKNOWN",
                            quantity_mt: null,
                            conversion_basis: null,
                            remarks: null,
                            match_status: "PENDING",
                            match_score: null,
                            matched_stock_item_id: null,
                            matched_stock_item_name: null,
                            matched_stock_item_make: null,
                            match_candidates: [],
                            stock_availability: null,
                            pricing: null,
                            pricing_option_count: 1,
                          }
                        }
                        rowSpan={i === 0 ? items.length : null}
                        selected={q.id === selectedId}
                        onOpen={() => navigate(`/quotations/${q.id}`)}
                        stage={q.stage}
                        onStageChange={(next) => moveStage(q.id, next)}
                        onReasonChange={(next) => setReason(q.id, next)}
                      />
                    ));
                  })}
                </tbody>
              </table>
            </div>
            <div className="border-t border-rule">
              <Pagination
                page={page}
                pageCount={pageCount}
                onChange={setPage}
                summary={`Showing ${pageRows.length} of ${filtered.length} quotations`}
              />
            </div>
          </>
        )}
      </div>

      {/* --- Detail, as a drawer over the table ----------------------------- */}
      {selectedId !== null && (
        <>
          <div
            className="fixed inset-0 z-40 bg-ink/30 backdrop-blur-[1px]"
            onClick={() => navigate("/quotations")}
            aria-hidden
          />
          <aside
            role="dialog"
            aria-modal="true"
            aria-label="Quotation details"
            className="fixed inset-y-0 right-0 z-50 flex w-full flex-col overflow-y-auto border-l border-rule bg-ground shadow-raised md:w-[min(56rem,64vw)]"
          >
            <QuotationDetailPanel
              id={selectedId}
              onChanged={reload}
              onBack={() => navigate("/quotations")}
              asDrawer
            />
          </aside>
        </>
      )}
    </div>
  );
}
