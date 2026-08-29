import { useState } from "react";

import { api, useApi } from "../api/client";
import type { EmailTemplates, NotificationRule, PushDevice } from "../api/types";
import { playChime } from "../lib/chime";
import { enablePush, type PushStatus } from "../lib/push";
import { setSoundEnabled, soundEnabled } from "../lib/sound-preference";
import {
  ago,
  Banner,
  Button,
  Card,
  Empty,
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

/** Whether notifications chime on this device.
 *
 *  Per-device rather than per-account, and deliberately so: the same trader
 *  wants sound on their phone and silence on a shared desk machine. Playing
 *  the chime as you switch it on is the only honest preview - "mild" is not
 *  something a label can settle, and someone deciding whether to keep it on
 *  should hear exactly what they are agreeing to.
 */
function SoundToggle() {
  const [on, setOn] = useState(soundEnabled);

  function toggle() {
    const next = !on;
    setOn(next);
    setSoundEnabled(next);
    if (next) playChime("info");
  }

  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-rule bg-sunk px-3 py-2">
      <span className="min-w-0">
        <span className="block text-sm font-medium text-ink">Notification sound</span>
        <span className="block text-[11.5px] text-ink-faint">
          {on
            ? "A short chime plays when a notification arrives on this device."
            : "Notifications appear silently on this device."}
        </span>
      </span>
      <Button compact variant={on ? "secondary" : "ghost"} onClick={toggle}>
        {on ? "Turn sound off" : "Turn sound on"}
      </Button>
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
  /* One flag per button rather than one for the section: sharing it meant
     clicking either control put *both* into "Working…", which reads as the
     page having hung rather than one action being in flight. */
  const [busy, setBusy] = useState<"turnOn" | "test" | null>(null);
  const [note, setNote] = useState<{ text: string; bad?: boolean } | null>(null);

  const permission =
    typeof Notification === "undefined" ? "unsupported" : Notification.permission;

  async function turnOn() {
    setBusy("turnOn");
    setNote(null);
    try {
      const result = await enablePush();
      setNote(
        result.ok
          ? { text: "This device will now receive notifications." }
          : { text: result.reason, bad: true },
      );
      status.reload();
      devices.reload();
    } catch (e) {
      /* `enablePush` is written to return a reason rather than throw, but a
         service worker or Firebase failure can still escape it. Without this
         the rejection went to the console and the button simply went quiet -
         which is indistinguishable, to the person clicking it, from nothing
         being wired up at all. */
      setNote({ text: (e as Error).message || "Could not turn on notifications.", bad: true });
    } finally {
      setBusy(null);
    }
  }

  async function test() {
    setBusy("test");
    setNote(null);
    try {
      const r = await api.post<{ ok: boolean; detail: string }>("/push/test");
      setNote({ text: r.detail, bad: !r.ok });
      // A test that reported dead devices has just deactivated them.
      devices.reload();
      status.reload();
    } catch (e) {
      setNote({ text: (e as Error).message, bad: true });
    } finally {
      setBusy(null);
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
            <Button compact disabled={busy !== null} onClick={test}>
              {busy === "test" ? "Sending…" : "Send test"}
            </Button>
          )}
          <Button compact variant="primary" disabled={busy !== null} onClick={turnOn}>
            {busy === "turnOn" ? "Working…" : "Turn on here"}
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

        <SoundToggle />

        {devices.loading && !devices.data ? (
          <Loading label="Loading your devices" />
        ) : active.length === 0 ? (
          <p className="text-sm text-ink-soft">
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


/* ---------------------------------------------------------------------------
   Follow-up wording.

   A follow-up says the same thing every time; only the reference and the money
   change. So it is a template filled in code rather than a writing task for a
   model - no API call, no variation the desk did not ask for, and the figures
   come from the same place the quotation itself is rendered from.
   --------------------------------------------------------------------------- */

function TemplatesSection() {
  const templates = useApi<EmailTemplates>("/organisation/email-templates");
  const [subject, setSubject] = useState<string | null>(null);
  const [body, setBody] = useState<string | null>(null);
  /* Which of Save / Restore is running, so one does not label the other. */
  const [busy, setBusy] = useState<"save" | "restore" | null>(null);
  const [note, setNote] = useState<{ text: string; bad?: boolean } | null>(null);

  const t = templates.data;

  /* An unedited desk shows the default rather than an empty box, so what is
     on screen is always what would actually be sent. */
  const currentSubject =
    subject ?? t?.followup_subject_template ?? t?.default_followup_subject ?? "";
  const currentBody =
    body ?? t?.followup_body_template ?? t?.default_followup_body ?? "";

  const dirty = subject !== null || body !== null;
  const usingDefault =
    !t?.followup_subject_template && !t?.followup_body_template && !dirty;

  async function save() {
    setBusy("save");
    setNote(null);
    try {
      await api.patch("/organisation", {
        followup_subject_template: currentSubject,
        followup_body_template: currentBody,
      });
      setSubject(null);
      setBody(null);
      templates.reload();
      setNote({ text: "Saved. New follow-ups will use this wording." });
    } catch (e) {
      setNote({ text: (e as Error).message, bad: true });
    } finally {
      setBusy(null);
    }
  }

  async function restore() {
    setBusy("restore");
    setNote(null);
    try {
      /* Empty clears the override on the server, so the built-in wording is
         read at send time rather than being copied into the desk's row. */
      await api.patch("/organisation", {
        followup_subject_template: "",
        followup_body_template: "",
      });
      setSubject(null);
      setBody(null);
      templates.reload();
      setNote({ text: "Restored the built-in wording." });
    } catch (e) {
      setNote({ text: (e as Error).message, bad: true });
    } finally {
      setBusy(null);
    }
  }

  if (templates.loading && !t) return <Loading label="Loading templates" />;

  return (
    <Card
      title="Follow-up email"
      subtitle="Sent when chasing a quotation. Filled in from the quotation itself — no AI is used, so the figures always match."
      action={
        <div className="flex gap-2">
          {!usingDefault && (
            <Button compact variant="secondary" disabled={busy !== null} onClick={restore}>
              {busy === "restore" ? "Restoring…" : "Restore default"}
            </Button>
          )}
          <Button compact disabled={busy !== null || !dirty} onClick={save}>
            {busy === "save" ? "Saving…" : "Save"}
          </Button>
        </div>
      }
    >
      {note && (
        <Banner tone={note.bad ? "danger" : "settled"}>{note.text}</Banner>
      )}

      <div className="flex flex-col gap-3">
        <label className="flex flex-col gap-1">
          <span className="text-[11px] font-medium text-ink-faint">Subject</span>
          <Input value={currentSubject} onChange={setSubject} />
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-[11px] font-medium text-ink-faint">Message</span>
          <textarea
            value={currentBody}
            onChange={(e) => setBody(e.target.value)}
            rows={12}
            spellCheck
            className="w-full resize-y rounded-lg border border-rule bg-surface px-3 py-2 font-sans text-sm leading-relaxed text-ink outline-none focus:border-brand"
          />
        </label>

        <div>
          <p className="text-[11px] font-medium text-ink-faint">
            Available placeholders — these are replaced with the real values
          </p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {t?.placeholders.map((p) => (
              <span
                key={p.name}
                title={p.description}
                className="rounded border border-rule bg-sunk px-1.5 py-0.5 font-mono text-[11px] text-ink-soft"
              >
                {`{{${p.name}}}`}
              </span>
            ))}
          </div>
        </div>
      </div>
    </Card>
  );
}

export default function Settings() {
  const rules = useApi<NotificationRule[]>("/notification-rules");

  if (rules.loading && !rules.data) return <Loading label="Loading settings" />;

  return (
    <div className="flex flex-col gap-4 p-5">
      <SectionLabel>Email templates</SectionLabel>
      <TemplatesSection />

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
