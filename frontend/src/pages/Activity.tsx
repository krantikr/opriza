import { useState } from "react";

import { query, useApi } from "../api/client";
import type { AuditEntry, Page } from "../api/types";
import { Card, Empty, ErrorNote, Loading, when } from "../components/ui";

const ENTITY_TYPES = ["", "email", "quotation_request", "quotation_draft"];

export default function Activity() {
  const [entityType, setEntityType] = useState("");
  const { data, error, loading } = useApi<Page<AuditEntry>>(
    `/audit-logs${query({ entity_type: entityType, limit: 200 })}`,
    20_000,
  );

  return (
    <div className="space-y-4 p-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink-900">Activity</h1>
          <p className="text-sm text-ink-500">
            Every state change, in order. {data ? `${data.total} entries.` : ""}
          </p>
        </div>
        <select
          value={entityType}
          onChange={(event) => setEntityType(event.target.value)}
          className="rounded-lg border border-ink-300 bg-white px-3 py-1.5 text-sm"
        >
          {ENTITY_TYPES.map((value) => (
            <option key={value} value={value}>
              {value ? value.replace(/_/g, " ") : "Everything"}
            </option>
          ))}
        </select>
      </header>

      {error && <ErrorNote message={error} />}

      <Card className="overflow-hidden">
        {loading && !data ? (
          <Loading />
        ) : !data || data.items.length === 0 ? (
          <Empty message="No activity recorded yet." />
        ) : (
          <ul className="-m-4 max-h-[75vh] divide-y divide-ink-100 overflow-auto">
            {data.items.map((entry) => (
              <li key={entry.id} className="px-4 py-2.5 text-sm hover:bg-ink-50">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="font-medium text-ink-900">
                    {entry.action.replace(/_/g, " ")}
                  </span>
                  <span className="shrink-0 text-xs text-ink-500">{when(entry.created_at)}</span>
                </div>
                <p className="text-xs text-ink-500">
                  {entry.entity_type}
                  {entry.entity_id !== null && ` #${entry.entity_id}`}
                </p>
                {entry.details && Object.keys(entry.details).length > 0 && (
                  <pre className="mt-1 overflow-x-auto rounded bg-ink-50 p-2 text-[11px] text-ink-700">
                    {JSON.stringify(entry.details, null, 2)}
                  </pre>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
