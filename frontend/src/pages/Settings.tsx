import { useState } from "react";

import { api, useApi } from "../api/client";
import type { NotificationRule, PushDevice, SystemStatus } from "../api/types";
import { enablePush, type PushStatus } from "../lib/push";
import {
  ago,
  Badge,
  Banner,
  Button,
  Card,
  Empty,
  Field,
  Input,
  Loading,
  SectionLabel,
  Select,
  Toggle,
} from "../components/ui";

/* ---------------------------------------------------------------------------
   Who gets told what, and what the system is currently configured to do.
   --------------------------------------------------------------------------- */

const KINDS = [
  { value: "QUOTATION_READY", label: "Quotation ready for review" },
  { value: "NEW_ENQUIRY", label: "New enquiry arrived" },
  { value: "CUSTOMER_REPLIED", label: "Customer replied" },
  { value: "FOLLOW_UP_DUE", label: "Follow-up due" },
  { value: "NEEDS_REVIEW", label: "Needs review" },
];

const CHANNELS = [
  { value: "IN_APP", label: "Dashboard" },
  { value: "EMAIL", label: "Email" },
  { value: "WHATSAPP", label: "WhatsApp" },
  { value: "SMS", label: "SMS" },
];

function RuleRow({ rule, onChanged }: { rule: NotificationRule; onChanged: () => void }) {
  const [draft, setDraft] = useState(rule);
  const [busy, setBusy] = useState(false);
  const dirty = JSON.stringify(draft) !== JSON.stringify(rule);

  const destinations =
    draft.channel === "EMAIL"
      ? (draft.recipient_emails ?? []).join(", ")
      : draft.channel === "WHATSAPP" || draft.channel === "SMS"
        ? (draft.recipient_phones ?? []).join(", ")
        : "";

  function setDestinations(value: string) {
    const list = value
      .split(",")
      .map((v) => v.trim())
      .filter(Boolean);
    if (draft.channel === "EMAIL") setDraft({ ...draft, recipient_emails: list });
    else setDraft({ ...draft, recipient_phones: list });
  }

  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-rule px-3 py-2.5 last:border-0">
      <Input
        value={draft.label}
        onChange={(label) => setDraft({ ...draft, label })}
        className="w-48"
      />
      <Select
        value={draft.kind}
        onChange={(kind) => setDraft({ ...draft, kind })}
        options={KINDS}
        className="w-56"
      />
      <Select
        value={draft.channel}
        onChange={(channel) => setDraft({ ...draft, channel })}
        options={CHANNELS}
        className="w-32"
      />
      {draft.channel !== "IN_APP" && (
        <Input
          value={destinations}
          onChange={setDestinations}
          placeholder={draft.channel === "EMAIL" ? "team@company.com" : "+9199..."}
          className="w-56"
        />
      )}
      <Toggle
        checked={draft.is_active}
        onChange={(is_active) => setDraft({ ...draft, is_active })}
      />
      <div className="ml-auto flex items-center gap-1.5">
        <Button
          compact
          variant="primary"
          disabled={!dirty || busy}
          onClick={async () => {
            setBusy(true);
            try {
              await api.put(`/notification-rules/${rule.id}`, draft);
              onChanged();
            } finally {
              setBusy(false);
            }
          }}
        >
          Save
        </Button>
        <Button
          compact
          variant="ghost"
          onClick={async () => {
            await api.del(`/notification-rules/${rule.id}`);
            onChanged();
          }}
        >
          Remove
        </Button>
      </div>
    </div>
  );
}

/** Turning system push on for this device, and seeing the others.
 *
 *  Separate from the rule table below because it answers a different
 *  question: the rules decide *who is told what*, this decides whether this
 *  particular browser buzzes when the site is closed. */
function PushSection() {
  const status = useApi<PushStatus>("/push/status");
  const devices = useApi<PushDevice[]>("/push/devices");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ text: string; bad?: boolean } | null>(null);

  const permission =
    typeof Notification === "undefined" ? "unsupported" : Notification.permission;

  async function turnOn() {
    setBusy(true);
    setNote(null);
    const result = await enablePush();
    setNote(
      result.ok
        ? { text: "This device will now receive notifications." }
        : { text: result.reason, bad: true },
    );
    status.reload();
    devices.reload();
    setBusy(false);
  }

  async function test() {
    setBusy(true);
    setNote(null);
    try {
      const r = await api.post<{ ok: boolean; detail: string }>("/push/test");
      setNote({ text: r.detail, bad: !r.ok });
    } catch (e) {
      setNote({ text: (e as Error).message, bad: true });
    } finally {
      setBusy(false);
    }
  }

  async function revoke(id: number) {
    await api.del(`/push/devices/${id}`);
    devices.reload();
    status.reload();
  }

  const active = devices.data?.filter((d) => d.is_active) ?? [];

  return (
    <Card
      title="Notifications when the site is closed"
      subtitle="The dashboard bell only works while a tab is open. Push reaches your phone either way."
      padded={false}
      action={
        <div className="flex gap-2">
          {active.length > 0 && (
            <Button compact disabled={busy} onClick={test}>
              Send test
            </Button>
          )}
          <Button compact variant="primary" disabled={busy} onClick={turnOn}>
            {busy ? "Working…" : "Turn on here"}
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-3 p-4">
        {/* Whether the *desk* can send at all is separate from whether this
            browser has agreed to receive. Saying which is missing stops a
            trader granting a permission that could never deliver anything. */}
        {status.data && !status.data.configured && (
          <Banner tone="attention">
            Firebase is not configured for this desk yet, so nothing can be delivered.
            Ask your administrator to set the Firebase keys.
          </Banner>
        )}
        {permission === "denied" && (
          <Banner tone="danger">
            Notifications are blocked for this site in your browser settings. Turning
            them on here cannot override that — change it in the browser first.
          </Banner>
        )}
        {note && <Banner tone={note.bad ? "danger" : "settled"}>{note.text}</Banner>}

        {devices.loading && !devices.data ? (
          <Loading label="Loading your devices" />
        ) : active.length === 0 ? (
          <p className="text-sm text-ink-faint">
            No devices registered yet. Turn it on to receive notifications on this one.
          </p>
        ) : (
          <ul className="flex flex-col gap-2">
            {active.map((device) => (
              <li
                key={device.id}
                className="flex items-center justify-between gap-3 rounded-lg border border-rule bg-sunk px-3 py-2"
              >
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium text-ink">
                    {device.label ?? "Unknown device"}
                  </span>
                  <span className="block text-[11.5px] text-ink-faint">
                    Last seen {device.last_seen_at ? ago(device.last_seen_at) : "—"}
                  </span>
                </span>
                <Button compact variant="ghost" onClick={() => revoke(device.id)}>
                  Turn off
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}

export default function Settings() {
  const status = useApi<SystemStatus>("/system/status");
  const rules = useApi<NotificationRule[]>("/notification-rules");

  if (status.loading && !status.data) return <Loading label="Loading settings" />;

  const s = status.data;

  return (
    <div className="flex flex-col gap-4 p-5">
      <header>
        <h1 className="text-lg font-semibold text-ink">Settings</h1>
        <p className="text-sm text-ink-faint">
          What the system is configured to do, and who it tells.
        </p>
      </header>

      {s && !s.auto_send_enabled && (
        <Banner tone="settled">
          Nothing is sent to a customer without a person approving it first.
        </Banner>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="System">
          <dl className="divide-y divide-rule">
            <Field label="Environment">{s?.environment}</Field>
            <Field label="Email source">
              <span className="inline-flex items-center gap-2">
                {s?.email_source}
                <Badge value={s?.email_source_available ? "CONNECTED" : "UNAVAILABLE"} />
              </span>
            </Field>
            <Field label="Language model">
              <Badge value={s?.llm_configured ? "CONFIGURED" : "NO API KEY"} />
            </Field>
            <Field label="Pricing rules">v{s?.rules_version}</Field>
            <Field label="Stock lots">{s?.stock_lots}</Field>
            <Field label="Customers">{s?.customers}</Field>
          </dl>
        </Card>

        <Card title="Models">
          <dl className="divide-y divide-rule">
            {s?.llm_models &&
              Object.entries(s.llm_models).map(([task, model]) => (
                <Field key={task} label={task}>
                  <span className="font-mono text-xs">{model}</span>
                </Field>
              ))}
          </dl>
          <p className="mt-3 text-xs text-ink-faint">
            Routed per task: classification runs on every email, extraction and drafting only on
            the enquiries.
          </p>
        </Card>
      </div>

      <SectionLabel>Push notifications</SectionLabel>
      <PushSection />

      <SectionLabel>Notifications</SectionLabel>
      <Card
        padded={false}
        action={
          <Button
            compact
            onClick={async () => {
              await api.post("/notification-rules", {
                label: "New rule",
                kind: "QUOTATION_READY",
                channel: "IN_APP",
                is_active: true,
              });
              rules.reload();
            }}
          >
            Add rule
          </Button>
        }
        title="Who gets told what"
        subtitle="WhatsApp and SMS write to data/notifications/ until Twilio is configured."
      >
        {rules.data?.length ? (
          rules.data.map((rule) => (
            <RuleRow key={rule.id} rule={rule} onChanged={rules.reload} />
          ))
        ) : (
          <Empty message="No rules yet. The dashboard bell still works without one." />
        )}
      </Card>
    </div>
  );
}
