import { useState } from "react";
import { Link } from "react-router-dom";

import { api, useApi } from "../api/client";
import type { DashboardMetrics } from "../api/types";
import { HBarChart, type BarDatum } from "../components/charts";
import { Button, Card, ErrorNote, Kpi, Loading, inr, when } from "../components/ui";

export default function Dashboard() {
  const { data, error, loading, reload } = useApi<DashboardMetrics>("/dashboard/metrics", 10_000);
  const [running, setRunning] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  async function runPipeline() {
    setRunning(true);
    setNote(null);
    try {
      const ingest = await api.post<{ created: number; duplicates: number; fetched: number }>(
        "/pipeline/ingest",
      );
      const processed = await api.post<{
        processed: number;
        ready_for_review: number;
        skipped: number;
        failed: number;
      }>("/pipeline/process");
      setNote(
        `Ingested ${ingest.created} new of ${ingest.fetched} fetched · ` +
          `processed ${processed.processed} (${processed.ready_for_review} for review, ` +
          `${processed.skipped} skipped, ${processed.failed} failed)`,
      );
      reload();
    } catch (err) {
      setNote((err as Error).message);
    } finally {
      setRunning(false);
    }
  }

  if (loading && !data) return <Loading label="Loading metrics" />;
  if (error) return <div className="p-6"><ErrorNote message={error} /></div>;
  if (!data) return null;

  const { emails, quotations, approvals } = data;

  const emailPipeline: BarDatum[] = [
    { label: "Processed", value: emails.processed, tone: "good" },
    { label: "Pending", value: emails.pending, tone: "warn" },
    { label: "Skipped", value: emails.skipped, tone: "neutral" },
    { label: "Failed", value: emails.failed, tone: "bad" },
  ];

  const byStatus = quotations.by_status;
  const inProgress =
    (byStatus.NEW ?? 0) +
    (byStatus.PROCESSING ?? 0) +
    (byStatus.NEEDS_INFORMATION ?? 0) +
    (byStatus.READY_FOR_REVIEW ?? 0) +
    (byStatus.EDITED ?? 0) +
    (byStatus.APPROVED ?? 0);
  const quotationOutcomes: BarDatum[] = [
    { label: "In progress", value: inProgress, tone: "neutral" },
    { label: "Sent, awaiting reply", value: byStatus.SENT ?? 0, tone: "warn" },
    { label: "Deal won", value: byStatus.CUSTOMER_ACCEPTED ?? 0, tone: "good" },
    { label: "Declined", value: byStatus.CUSTOMER_DECLINED ?? 0, tone: "neutral" },
    { label: "Rejected / failed", value: (byStatus.REJECTED ?? 0) + (byStatus.FAILED ?? 0), tone: "bad" },
  ];

  return (
    <div className="space-y-6 p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink-900">Dashboard</h1>
          <p className="text-sm text-ink-500">Updated {when(data.generated_at)}</p>
        </div>
        <div className="flex items-center gap-2">
          <Button onClick={reload}>Refresh</Button>
          <Button variant="primary" onClick={runPipeline} disabled={running}>
            {running ? "Running…" : "Fetch & process email"}
          </Button>
        </div>
      </header>

      {note && (
        <div className="rounded-lg border border-ink-200 bg-white px-4 py-3 text-sm text-ink-700">
          {note}
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <Kpi label="Emails received" value={emails.total} hint={`${emails.pending} awaiting processing`} />
        <Kpi label="Quotation requests" value={emails.quotation_requests} hint={`${emails.skipped} other categories`} />
        <Kpi
          label="Pending approval"
          value={quotations.pending_approval}
          tone={quotations.pending_approval > 0 ? "warn" : "default"}
          hint={`${quotations.needs_information} need information`}
        />
        <Kpi label="Sent" value={quotations.sent} tone="good" hint={`${quotations.rejected} rejected`} />
        <Link to="/quotations?status=CUSTOMER_ACCEPTED" className="block">
          <Kpi
            label="Ready to close"
            value={quotations.by_status.CUSTOMER_ACCEPTED ?? 0}
            tone={(quotations.by_status.CUSTOMER_ACCEPTED ?? 0) > 0 ? "good" : "default"}
            hint="customer said yes"
          />
        </Link>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Quotations by status">
          <dl className="space-y-1.5">
            {Object.entries(quotations.by_status).length === 0 && (
              <p className="text-sm text-ink-500">No quotations yet.</p>
            )}
            {Object.entries(quotations.by_status).map(([status, count]) => (
              <div key={status} className="flex items-center justify-between text-sm">
                <Link
                  to={`/quotations?status=${status}`}
                  className="text-ink-700 hover:text-ink-900 hover:underline"
                >
                  {status.replace(/_/g, " ")}
                </Link>
                <span className="tabular font-medium">{count}</span>
              </div>
            ))}
            <div className="mt-3 border-t border-ink-200 pt-2 text-sm">
              <div className="flex items-center justify-between">
                <span className="text-ink-500">Indicative value awaiting approval</span>
                <span className="tabular font-semibold">
                  {inr(quotations.total_suggested_value)}
                </span>
              </div>
            </div>
          </dl>
        </Card>

        <Card title="Review quality">
          <dl className="space-y-1.5 text-sm">
            <div className="flex justify-between">
              <span className="text-ink-500">Decisions recorded</span>
              <span className="tabular font-medium">{approvals.decisions}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-ink-500">Approval rate</span>
              <span className="tabular font-medium">
                {approvals.approval_rate === null ? "—" : `${(approvals.approval_rate * 100).toFixed(0)}%`}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-ink-500">Edit rate</span>
              <span className="tabular font-medium">
                {approvals.edit_rate === null ? "—" : `${(approvals.edit_rate * 100).toFixed(0)}%`}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-ink-500">Avg processing time</span>
              <span className="tabular font-medium">
                {emails.avg_processing_ms ? `${(emails.avg_processing_ms / 1000).toFixed(1)}s` : "—"}
              </span>
            </div>
          </dl>
          <p className="mt-3 border-t border-ink-200 pt-2 text-xs text-ink-500">
            Edit rate is how often a reviewer changed the draft before sending — the clearest
            signal of how well the system is actually writing.
          </p>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Emails by status">
          <HBarChart data={emailPipeline} />
        </Card>

        <Card
          title="Quotation outcomes"
          action={
            <span className="text-xs text-ink-500">
              {quotations.replied} replied of {quotations.sent + quotations.replied}
            </span>
          }
        >
          <HBarChart data={quotationOutcomes} />
        </Card>
      </div>
    </div>
  );
}
