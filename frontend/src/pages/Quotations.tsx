import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { api, query, useApi } from "../api/client";
import type { Page, Quotation } from "../api/types";
import QuotationDetailPanel from "../components/QuotationDetailPanel";
import {
  ago,
  Button,
  Empty,
  ErrorNote,
  inrShort,
  Loading,
  Pagination,
  SearchInput,
  when,
} from "../components/ui";

/* ---------------------------------------------------------------------------
   Quotations: a full-width table, with the open one in a drawer over it.

   Same shape as the chase board, deliberately. A trader moves between the two
   screens all day; two layouts over the same objects cost a beat every time.
   The list gets the whole width because a quotation has more attributes worth
   comparing across rows - value, status, age, material - than fit in a rail,
   and comparison is the reason to be on a list screen at all.

   Selecting a row still changes the URL, so an individual quotation stays
   linkable and the back button behaves.
   --------------------------------------------------------------------------- */

const PAGE_SIZE = 14;

const TABS = [
  { key: "all", label: "All", statuses: [] as string[] },
  {
    key: "draft",
    label: "Draft",
    statuses: ["READY_FOR_REVIEW", "NEEDS_INFORMATION", "EDITED", "NEW", "PROCESSING"],
  },
  { key: "sent", label: "Sent", statuses: ["SENT", "APPROVED"] },
  { key: "replied", label: "Replied", statuses: ["CUSTOMER_ACCEPTED", "CUSTOMER_DECLINED"] },
  { key: "closed", label: "Closed", statuses: ["REJECTED", "FAILED"] },
];

/** Where a quotation stands, in the words the rest of the app uses. The stripe
 *  carries it in form as well as colour, so state reads before any word does. */
const STATE: Record<string, { label: string; stripe: string; chip: string }> = {
  NEW: { label: "New", stripe: "bg-rule-firm", chip: "bg-sunk text-ink-soft" },
  PROCESSING: { label: "Reading", stripe: "bg-rule-firm", chip: "bg-sunk text-ink-soft" },
  READY_FOR_REVIEW: {
    label: "Needs review",
    stripe: "bg-attention",
    chip: "bg-attention-wash text-attention-ink",
  },
  NEEDS_INFORMATION: {
    label: "Missing details",
    stripe: "bg-attention",
    chip: "bg-attention-wash text-attention-ink",
  },
  EDITED: { label: "Edited", stripe: "bg-info", chip: "bg-info-wash text-info-ink" },
  APPROVED: { label: "Approved", stripe: "bg-brand-soft", chip: "bg-brand-wash text-brand-ink" },
  SENT: { label: "Sent", stripe: "bg-brand-soft", chip: "bg-brand-wash text-brand-ink" },
  CUSTOMER_ACCEPTED: {
    label: "Won",
    stripe: "bg-settled",
    chip: "bg-settled-wash text-settled-ink",
  },
  CUSTOMER_DECLINED: { label: "Lost", stripe: "bg-rule-firm", chip: "bg-sunk text-ink-soft" },
  REJECTED: { label: "Rejected", stripe: "bg-rule-firm", chip: "bg-sunk text-ink-soft" },
  FAILED: { label: "Could not read", stripe: "bg-danger", chip: "bg-danger-wash text-danger-ink" },
};

const FALLBACK = { label: "—", stripe: "bg-rule-firm", chip: "bg-sunk text-ink-soft" };

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

/** A figure that is also its own filter: the number you noticed is the one you
 *  want to see, so it is the control rather than a label beside one. */
function Stat({
  label,
  value,
  tone = "",
  active,
  onClick,
}: {
  label: string;
  value: number;
  tone?: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`flex items-baseline gap-1.5 rounded-lg px-2.5 py-1 transition-colors ${
        active ? "bg-brand-wash" : "hover:bg-sunk"
      }`}
    >
      <span className={`text-[15px] font-semibold tabular-nums ${tone || "text-ink"}`}>
        {value}
      </span>
      <span className="text-[12px] text-ink-faint">{label}</span>
    </button>
  );
}

function Row({
  q,
  selected,
  onOpen,
}: {
  q: Quotation;
  selected: boolean;
  onOpen: () => void;
}) {
  const state = STATE[q.status] ?? FALLBACK;
  const who = q.customer_company || q.customer_name || "Unknown";
  const hue = hueFor(who);
  const value = Number(q.total_suggested_value ?? 0);

  return (
    <tr
      onClick={onOpen}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen();
        }
      }}
      tabIndex={0}
      aria-selected={selected}
      className={`cursor-pointer border-b border-rule align-top outline-none last:border-0 focus-visible:bg-sunk ${
        selected ? "bg-brand-wash" : "hover:bg-ground"
      }`}
    >
      <td className="relative py-2.5 pl-3 pr-3">
        <span className={`absolute inset-y-0 left-0 w-1 ${state.stripe}`} aria-hidden />
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

      <td className="px-3 py-2.5">
        <span className="block text-[13px] leading-tight text-ink">
          {q.headline_product ?? "—"}
        </span>
        <span className="block text-[11.5px] text-ink-faint">
          {q.line_count} {q.line_count === 1 ? "line" : "lines"}
          {q.delivery_location ? ` · ${q.delivery_location}` : ""}
        </span>
      </td>

      <td className="px-3 py-2.5">
        <span
          className={`inline-block whitespace-nowrap rounded-full px-2 py-0.5 text-[10.5px] font-medium ${state.chip}`}
        >
          {state.label}
        </span>
        {q.headline_availability && (
          <span className="mt-1 block text-[11px] text-ink-faint">
            {q.headline_availability}
          </span>
        )}
      </td>

      <td className="px-3 py-2.5 text-right">
        <span className="block whitespace-nowrap text-[14px] font-semibold tabular-nums text-ink">
          {value > 0 ? inrShort(value) : "—"}
        </span>
      </td>

      <td className="px-3 py-2.5 pr-4 text-right">
        <span
          className="block whitespace-nowrap text-[12.5px] tabular-nums text-ink-soft"
          title={when(q.sent_at ?? q.created_at)}
        >
          {ago(q.sent_at ?? q.created_at)}
        </span>
        <span className="block whitespace-nowrap text-[11px] text-ink-faint">
          {q.sent_at ? "sent" : "raised"} · {q.quotation_number}
        </span>
      </td>
    </tr>
  );
}

export default function Quotations() {
  const { id } = useParams();
  const navigate = useNavigate();

  const [tab, setTab] = useState("all");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const { data, error, loading, reload } = useApi<Page<Quotation>>(
    `/quotations${query({ search, limit: 200 })}`,
    30_000,
  );

  const all = useMemo(() => data?.items ?? [], [data]);

  const countFor = (key: string) => {
    const t = TABS.find((x) => x.key === key)!;
    return t.statuses.length === 0
      ? all.length
      : all.filter((q) => t.statuses.includes(q.status)).length;
  };

  const active = TABS.find((t) => t.key === tab)!;
  const filtered = useMemo(
    () =>
      active.statuses.length === 0
        ? all
        : all.filter((q) => active.statuses.includes(q.status)),
    [all, active],
  );

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const rows = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

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

  useEffect(() => setPage(1), [tab, search]);

  const totalValue = filtered.reduce(
    (sum, q) => sum + Number(q.total_suggested_value ?? 0),
    0,
  );

  async function exportXlsx() {
    setExporting(true);
    setExportError(null);
    try {
      // Exports what you are looking at, not the whole table: a filtered view
      // that silently exports everything is worse than no export.
      await api.download(
        `/quotations/export${query({ search })}`,
        "quotations.xlsx",
      );
    } catch (e) {
      setExportError((e as Error).message);
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="flex flex-col gap-3 p-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-ink">Quotations</h1>
          <p className="mt-0.5 text-sm text-ink-soft">
            <span className="font-semibold tabular-nums text-ink">
              {inrShort(totalValue)}
            </span>{" "}
            across {filtered.length} quotation{filtered.length === 1 ? "" : "s"}.
          </p>
        </div>
        <Button onClick={exportXlsx} disabled={exporting}>
          {exporting ? "Preparing…" : "Export to Excel"}
        </Button>
      </header>

      {exportError && <ErrorNote message={exportError} />}

      <div className="flex flex-wrap items-center gap-2">
        <div className="flex flex-wrap items-center gap-0.5">
          <Stat
            label="All"
            value={countFor("all")}
            active={tab === "all"}
            onClick={() => setTab("all")}
          />
          <Stat
            label="Draft"
            value={countFor("draft")}
            tone="text-attention"
            active={tab === "draft"}
            onClick={() => setTab("draft")}
          />
          <Stat
            label="Sent"
            value={countFor("sent")}
            tone="text-brand-soft-ink"
            active={tab === "sent"}
            onClick={() => setTab("sent")}
          />
          <Stat
            label="Replied"
            value={countFor("replied")}
            tone="text-settled"
            active={tab === "replied"}
            onClick={() => setTab("replied")}
          />
          <Stat
            label="Closed"
            value={countFor("closed")}
            active={tab === "closed"}
            onClick={() => setTab("closed")}
          />
        </div>
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder="Search by customer, material or number…"
          className="ml-auto w-full sm:w-72"
        />
      </div>

      {error && <ErrorNote message={error} />}

      <div className="overflow-hidden rounded-card border border-rule bg-surface shadow-card">
        {loading && !data ? (
          <Loading label="Loading quotations" />
        ) : rows.length === 0 ? (
          <Empty message="Nothing here. New enquiries appear once processed." />
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[52rem] border-collapse">
                <thead>
                  <tr className="border-b border-rule">
                    {[
                      ["Customer", "pl-4 pr-3 text-left"],
                      ["Material", "px-3 text-left"],
                      ["Status", "px-3 text-left"],
                      ["Value", "px-3 text-right"],
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
                  {rows.map((q) => (
                    <Row
                      key={q.id}
                      q={q}
                      selected={q.id === selectedId}
                      onOpen={() => navigate(`/quotations/${q.id}`)}
                    />
                  ))}
                </tbody>
              </table>
            </div>
            <div className="border-t border-rule">
              <Pagination
                page={page}
                pageCount={pageCount}
                onChange={setPage}
                summary={`Showing ${rows.length} of ${filtered.length} quotations`}
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
