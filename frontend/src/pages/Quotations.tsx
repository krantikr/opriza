import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { query, useApi } from "../api/client";
import type { Page, Quotation } from "../api/types";
import QuotationDetailPanel from "../components/QuotationDetailPanel";
import {
  Badge,
  Empty,
  ErrorNote,
  FilterButton,
  inr,
  Loading,
  Pagination,
  SearchInput,
  StatCard,
  Tabs,
} from "../components/ui";

/* ---------------------------------------------------------------------------
   Quotations: the list and the open one, side by side.

   A trader works a queue - open, judge, act, next - so the list stays on
   screen while a quotation is being read. Selecting a row changes the URL, so
   an individual quotation is still linkable and the back button behaves.
   --------------------------------------------------------------------------- */

const PAGE_SIZE = 8;

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

export default function Quotations() {
  const { id } = useParams();
  const navigate = useNavigate();

  const [tab, setTab] = useState("all");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);

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

  // Keep a quotation open: the first on arrival, and a valid one after
  // filtering, so the detail pane is never left showing something hidden.
  const selectedId = id ? Number(id) : null;
  useEffect(() => {
    if (!rows.length) return;
    // Only auto-open where both panes are visible. On a phone the detail
    // replaces the list, so opening one uninvited hides everything else.
    if (!window.matchMedia("(min-width: 1280px)").matches) return;
    if (selectedId === null || !filtered.some((q) => q.id === selectedId)) {
      navigate(`/quotations/${rows[0].id}`, { replace: true });
    }
  }, [rows, filtered, selectedId, navigate]);

  useEffect(() => setPage(1), [tab, search]);

  const stats = {
    total: all.length,
    draft: countFor("draft"),
    sent: countFor("sent"),
    replied: countFor("replied"),
  };

  return (
    <div className="grid h-[calc(100vh-7rem)] grid-cols-1 md:h-[calc(100vh-3.25rem)] xl:grid-cols-[minmax(0,32rem)_1fr]">
      {/* --- List ---------------------------------------------------------- */}
      <section
        className={`flex min-h-0 flex-col border-r border-rule ${
          selectedId ? "hidden xl:flex" : "flex"
        }`}
      >
        <header className="px-4 pb-3 pt-4 sm:px-5">
          <h1 className="text-lg font-semibold text-ink">Quotations</h1>
          <p className="text-sm text-ink-faint">All generated replies and pricing</p>
        </header>

        <div className="grid grid-cols-2 gap-2 px-4 sm:grid-cols-4 sm:gap-2.5 sm:px-5">
          <StatCard label="Total" value={stats.total} />
          <StatCard label="Draft" value={stats.draft} tone="attention" />
          <StatCard label="Sent" value={stats.sent} tone="settled" />
          <StatCard label="Replied" value={stats.replied} tone="info" />
        </div>

        <div className="flex items-center gap-2 px-4 py-3 sm:px-5">
          <SearchInput
            value={search}
            onChange={setSearch}
            placeholder="Search quotations…"
            className="flex-1"
          />
          <FilterButton />
        </div>

        <div className="overflow-x-auto px-4 sm:px-5">
          <Tabs
            tabs={TABS.map((t) => ({ key: t.key, label: t.label, count: countFor(t.key) }))}
            value={tab}
            onChange={setTab}
          />
        </div>

        {error && <div className="p-4"><ErrorNote message={error} /></div>}

        <div className="min-h-0 flex-1 overflow-y-auto">
          {loading && !data ? (
            <Loading label="Loading quotations" />
          ) : rows.length === 0 ? (
            <Empty message="Nothing here. New enquiries appear once processed." />
          ) : (
            <ul>
              {rows.map((q) => {
                const open = q.id === selectedId;
                return (
                  <li key={q.id}>
                    <button
                      type="button"
                      onClick={() => navigate(`/quotations/${q.id}`)}
                      className={`flex w-full items-start justify-between gap-2 border-b border-l-2 border-rule px-4 py-3 text-left transition-colors sm:gap-3 sm:px-5 ${
                        open
                          ? "border-l-brand-soft bg-brand-wash"
                          : "border-l-transparent hover:bg-sunk"
                      }`}
                    >
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-brand">{q.quotation_number}</span>
                          {q.requires_manual_review && (
                            <span
                              className="size-1.5 shrink-0 rounded-full bg-attention"
                              title="Flagged for review"
                            />
                          )}
                        </div>
                        <p className="mt-0.5 truncate text-xs text-ink-faint">
                          {q.headline_product ?? "—"}
                          {q.line_count > 1 && ` +${q.line_count - 1} more`}
                        </p>
                        <p className="mt-1 truncate text-xs text-ink-soft">
                          {q.customer_company || q.customer_name || "—"}
                          <span className="text-ink-faint">
                            {" · "}
                            {new Date(q.created_at).toLocaleDateString("en-IN", {
                              day: "2-digit",
                              month: "short",
                            })}
                          </span>
                        </p>
                      </div>

                      <div className="flex shrink-0 flex-col items-end gap-1.5">
                        <span className="tabular whitespace-nowrap text-sm font-semibold text-ink">
                          {q.total_suggested_value && Number(q.total_suggested_value) > 0
                            ? inr(q.total_suggested_value)
                            : "—"}
                        </span>
                        <Badge value={q.status} dot={false} />
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>

        <div className="border-t border-rule">
          <Pagination
            page={page}
            pageCount={pageCount}
            onChange={setPage}
            summary={`Showing ${rows.length} of ${filtered.length} quotations`}
          />
        </div>
      </section>

      {/* --- Detail --------------------------------------------------------- */}
      <section
        className={`min-h-0 overflow-y-auto overflow-x-hidden bg-ground ${
          selectedId ? "block" : "hidden xl:block"
        }`}
      >
        {selectedId ? (
          <QuotationDetailPanel
            id={selectedId}
            onChanged={reload}
            onBack={() => navigate("/quotations")}
          />
        ) : (
          <Empty message="Select a quotation to open it." />
        )}
      </section>
    </div>
  );
}
