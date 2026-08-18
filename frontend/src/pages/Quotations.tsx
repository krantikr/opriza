import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { query, useApi } from "../api/client";
import type { Page, Quotation, QuotationStatus } from "../api/types";
import { Badge, Card, Empty, ErrorNote, Loading, inr, when } from "../components/ui";

function AvailabilityBadge({ value }: { value: string | null }) {
  if (!value) return <span className="text-ink-500">—</span>;
  const style = value.startsWith("Partial")
    ? "bg-amber-100 text-amber-800 ring-amber-200"
    : value === "Not available"
      ? "bg-rose-100 text-rose-800 ring-rose-200"
      : "bg-emerald-100 text-emerald-800 ring-emerald-200";
  return (
    <span
      className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${style}`}
    >
      {value}
    </span>
  );
}

const STATUSES: (QuotationStatus | "")[] = [
  "",
  "READY_FOR_REVIEW",
  "NEEDS_INFORMATION",
  "EDITED",
  "APPROVED",
  "SENT",
  "CUSTOMER_ACCEPTED",
  "CUSTOMER_DECLINED",
  "REJECTED",
  "FAILED",
];

export default function Quotations() {
  const [params, setParams] = useSearchParams();
  const [search, setSearch] = useState(params.get("search") ?? "");
  const status = params.get("status") ?? "";

  const { data, error, loading } = useApi<Page<Quotation>>(
    `/quotations${query({ status, search, limit: 100 })}`,
  );

  function apply(next: Record<string, string>) {
    const merged = new URLSearchParams(params);
    for (const [key, value] of Object.entries(next)) {
      if (value) merged.set(key, value);
      else merged.delete(key);
    }
    setParams(merged);
  }

  return (
    <div className="space-y-4 p-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink-900">Quotations</h1>
          <p className="text-sm text-ink-500">
            {data ? `${data.total} total` : "…"}
            {status && ` · filtered by ${status.replace(/_/g, " ")}`}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <select
            value={status}
            onChange={(event) => apply({ status: event.target.value })}
            className="rounded-lg border border-ink-300 bg-white px-3 py-1.5 text-sm"
          >
            {STATUSES.map((value) => (
              <option key={value} value={value}>
                {value ? value.replace(/_/g, " ") : "All statuses"}
              </option>
            ))}
          </select>

          <form
            onSubmit={(event) => {
              event.preventDefault();
              apply({ search });
            }}
          >
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search number or customer"
              className="w-64 rounded-lg border border-ink-300 bg-white px-3 py-1.5 text-sm"
            />
          </form>
        </div>
      </header>

      {error && <ErrorNote message={error} />}

      <Card className="overflow-hidden">
        {loading && !data ? (
          <Loading />
        ) : !data || data.items.length === 0 ? (
          <Empty message="No quotations match this view." />
        ) : (
          <div className="-m-4 overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-ink-200 bg-ink-50 text-left text-xs uppercase tracking-wide text-ink-500">
                <tr>
                  <th className="px-4 py-2 font-medium">Number</th>
                  <th className="px-4 py-2 font-medium">Customer</th>
                  <th className="px-4 py-2 font-medium">Material</th>
                  <th className="px-4 py-2 font-medium">Availability</th>
                  <th className="px-4 py-2 text-right font-medium">Indicative value</th>
                  <th className="px-4 py-2 font-medium">Confidence</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">Received</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-ink-100">
                {data.items.map((quotation) => (
                  <tr key={quotation.id} className="hover:bg-ink-50">
                    <td className="px-4 py-2.5 font-medium">
                      <Link
                        to={`/quotations/${quotation.id}`}
                        className="text-ink-900 hover:underline"
                      >
                        {quotation.quotation_number}
                      </Link>
                      {quotation.requires_manual_review && (
                        <span
                          className="ml-1.5 text-amber-600"
                          title="Flagged for manual review"
                        >
                          ●
                        </span>
                      )}
                    </td>
                    <td className="max-w-48 truncate px-4 py-2.5">
                      {quotation.customer_company || quotation.customer_name || "—"}
                      {!quotation.customer_id && (
                        <span className="ml-1 text-xs text-amber-600" title="Not in customer master">
                          new
                        </span>
                      )}
                    </td>
                    <td className="max-w-64 truncate px-4 py-2.5 text-ink-700">
                      {quotation.headline_product ?? "—"}
                      {quotation.line_count > 1 && (
                        <span className="text-ink-500"> +{quotation.line_count - 1} more</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5">
                      <AvailabilityBadge value={quotation.headline_availability} />
                    </td>
                    <td className="tabular px-4 py-2.5 text-right">
                      {inr(quotation.total_suggested_value)}
                    </td>
                    <td className="px-4 py-2.5">
                      <Badge value={quotation.confidence} />
                    </td>
                    <td className="px-4 py-2.5">
                      <Badge value={quotation.status} />
                    </td>
                    <td className="px-4 py-2.5 text-xs text-ink-500">{when(quotation.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
