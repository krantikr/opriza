import { useState } from "react";
import { Link } from "react-router-dom";

import { api, useApi } from "../api/client";
import type { FollowUpRule, FollowUpSchedule } from "../api/types";
import {
  Badge,
  Banner,
  Button,
  Card,
  Empty,
  Input,
  Loading,
  SectionLabel,
  Toggle,
  when,
} from "../components/ui";

/* ---------------------------------------------------------------------------
   Chasing quotations that have gone quiet.

   The queue is the screen that matters: the rules work out *when* a nudge is
   owed and draft it, and a person presses send. That division is the whole
   design, so the UI states it rather than hiding it.
   --------------------------------------------------------------------------- */

function QueueItem({ item, onDone }: { item: FollowUpSchedule; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function act(action: "send" | "skip") {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/follow-ups/${item.id}/${action}`);
      onDone();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="border-b border-rule px-4 py-3 last:border-0">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <Link
              to={`/quotations/${item.quotation_request_id}`}
              className="text-sm font-medium text-brand hover:underline"
            >
              {item.subject ?? `Quotation #${item.quotation_request_id}`}
            </Link>
            <Badge value={`ATTEMPT ${item.attempt_no}`} dot={false} />
          </div>
          <p className="mt-0.5 text-xs text-ink-faint">Due {when(item.due_at)}</p>
          {expanded && item.body && (
            <pre className="mt-2 whitespace-pre-wrap rounded-lg border border-rule bg-sunk p-2.5 text-xs leading-relaxed text-ink-soft">
              {item.body}
            </pre>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-1.5">
          <Button compact variant="ghost" onClick={() => setExpanded((v) => !v)}>
            {expanded ? "Hide" : "Preview"}
          </Button>
          <Button compact variant="secondary" disabled={busy} onClick={() => act("skip")}>
            Skip
          </Button>
          <Button compact variant="primary" disabled={busy} onClick={() => act("send")}>
            Send
          </Button>
        </div>
      </div>
      {error && <p className="mt-2 text-xs text-danger">{error}</p>}
    </div>
  );
}

function RuleEditor({ rule, onSaved }: { rule: FollowUpRule; onSaved: () => void }) {
  const [draft, setDraft] = useState(rule);
  const [busy, setBusy] = useState(false);

  const dirty = JSON.stringify(draft) !== JSON.stringify(rule);

  async function save() {
    setBusy(true);
    try {
      await api.put(`/follow-up-rules/${rule.id}`, draft);
      onSaved();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3 border-b border-rule p-4 last:border-0">
      <div className="flex items-center justify-between gap-3">
        <Input
          value={draft.label}
          onChange={(label) => setDraft({ ...draft, label })}
          className="max-w-xs"
        />
        <div className="flex items-center gap-3">
          <Toggle
            checked={draft.is_active}
            onChange={(is_active) => setDraft({ ...draft, is_active })}
            label="Active"
          />
          <Button variant="primary" compact disabled={!dirty || busy} onClick={save}>
            Save
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <label className="flex flex-col gap-1">
          <span className="text-[11px] uppercase tracking-wider text-ink-faint">First after</span>
          <div className="flex items-center gap-1">
            <Input
              type="number"
              value={String(draft.first_after_days)}
              onChange={(v) => setDraft({ ...draft, first_after_days: Number(v) })}
              className="w-16"
            />
            <span className="text-xs text-ink-faint">days</span>
          </div>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-[11px] uppercase tracking-wider text-ink-faint">Then every</span>
          <div className="flex items-center gap-1">
            <Input
              type="number"
              value={String(draft.interval_days)}
              onChange={(v) => setDraft({ ...draft, interval_days: Number(v) })}
              className="w-16"
            />
            <span className="text-xs text-ink-faint">days</span>
          </div>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-[11px] uppercase tracking-wider text-ink-faint">At most</span>
          <div className="flex items-center gap-1">
            <Input
              type="number"
              value={String(draft.max_attempts)}
              onChange={(v) => setDraft({ ...draft, max_attempts: Number(v) })}
              className="w-16"
            />
            <span className="text-xs text-ink-faint">times</span>
          </div>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-[11px] uppercase tracking-wider text-ink-faint">Give up after</span>
          <div className="flex items-center gap-1">
            <Input
              type="number"
              value={String(draft.stop_after_days ?? "")}
              onChange={(v) => setDraft({ ...draft, stop_after_days: v ? Number(v) : null })}
              className="w-16"
            />
            <span className="text-xs text-ink-faint">days</span>
          </div>
        </label>
      </div>

      <p className="text-xs text-ink-faint">
        Chases {draft.max_attempts} time{draft.max_attempts === 1 ? "" : "s"}, first{" "}
        {draft.first_after_days} days after sending, then every {draft.interval_days} days.
        {draft.mark_cold_when_exhausted && " Marked cold when the attempts are spent."}
      </p>

      {draft.auto_send && (
        <Banner tone="attention">
          This rule sends without asking. Every other rule queues its nudge for a person.
        </Banner>
      )}
    </div>
  );
}

export default function FollowUps() {
  const queue = useApi<FollowUpSchedule[]>("/follow-ups/queue", 60_000);
  const rules = useApi<FollowUpRule[]>("/follow-up-rules");
  const [running, setRunning] = useState(false);

  async function runNow() {
    setRunning(true);
    try {
      await api.post("/follow-ups/run");
      queue.reload();
    } finally {
      setRunning(false);
    }
  }

  if (queue.loading && !queue.data) return <Loading label="Loading follow-ups" />;

  return (
    <div className="flex flex-col gap-4 p-5">
      <header className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-ink">Follow-ups</h1>
          <p className="text-sm text-ink-faint">
            The rules decide when a quotation is owed a nudge. You decide whether it goes.
          </p>
        </div>
        <Button onClick={runNow} disabled={running}>
          {running ? "Checking…" : "Check now"}
        </Button>
      </header>

      <Card
        title="Waiting to be sent"
        subtitle={`${queue.data?.length ?? 0} due`}
        padded={false}
      >
        {queue.data?.length ? (
          queue.data.map((item) => (
            <QueueItem key={item.id} item={item} onDone={queue.reload} />
          ))
        ) : (
          <Empty message="Nothing is due. Quotations are chased only after they have been sent and have gone quiet." />
        )}
      </Card>

      <SectionLabel>Rules</SectionLabel>
      <Card padded={false}>
        {rules.data?.length ? (
          rules.data.map((rule) => (
            <RuleEditor key={rule.id} rule={rule} onSaved={rules.reload} />
          ))
        ) : (
          <Empty message="No follow-up rules configured, so nothing is chased." />
        )}
      </Card>
    </div>
  );
}
