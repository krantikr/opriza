/* ---------------------------------------------------------------------------
   When Steel Desk checks the mailbox.

   The one number that matters to a trader is "when will the next check
   happen", so the current state is stated in a sentence at the top rather
   than left to be inferred from four form fields.
   --------------------------------------------------------------------------- */

import { useCallback, useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import { Button, Card, Loading, Select } from "../components/ui";
import { useToast } from "../components/Toasts";
import { useAuth, type Organisation } from "../lib/auth";

interface CrawlStatus {
  enabled: boolean;
  active_now: boolean;
  interval_minutes: number;
  reason: string;
  local_time: string;
  last_polled_at: string | null;
  /** The server-wide poller switch. Off means no desk is checked on a timer. */
  poller_running: boolean;
  /** Whether this desk has a mailbox to poll at all. */
  mailbox_connected: boolean;
}

interface MailboxSetup {
  ready: boolean;
  redirect_uri: string;
  problem: string | null;
}

interface Mailbox {
  id: number;
  provider: string;
  email_address: string;
  status: string;
  last_error: string | null;
  last_polled_at: string | null;
}

/** Zones a desk trading from India is plausibly in. Not the full IANA list,
 *  which is 600 entries and helps nobody scroll. */
const ZONES = [
  "Asia/Kolkata",
  "Asia/Dubai",
  "Asia/Singapore",
  "Asia/Shanghai",
  "Europe/London",
  "Europe/Amsterdam",
  "America/New_York",
  "UTC",
].map((z) => ({ value: z, label: z.replace("_", " ") }));

const MINUTES = [5, 10, 15, 30, 60, 120, 240].map((m) => ({
  value: String(m),
  label: m < 60 ? `every ${m} minutes` : `every ${m / 60} hour${m > 60 ? "s" : ""}`,
}));

/** 00:00 - 23:30 in half hours. */
const TIMES = Array.from({ length: 48 }, (_, i) => {
  const value = `${String(Math.floor(i / 2)).padStart(2, "0")}:${i % 2 ? "30" : "00"}`;
  return { value, label: value };
});

export default function MailSchedule() {
  const { organisation, setOrganisation, canAdminister } = useAuth();
  const toast = useToast();

  const [status, setStatus] = useState<CrawlStatus | null>(null);
  const [mailboxes, setMailboxes] = useState<Mailbox[]>([]);
  const [draft, setDraft] = useState<Partial<Organisation>>({});
  const [busy, setBusy] = useState(false);
  const [setup, setSetup] = useState<MailboxSetup | null>(null);

  const load = useCallback(async () => {
    const [crawl, boxes, google] = await Promise.all([
      api.get<CrawlStatus>("/organisation/crawl-status"),
      api.get<Mailbox[]>("/organisation/mailboxes"),
      // Owner-only; a member simply does not see the setup notice.
      api.get<MailboxSetup>("/organisation/mailbox/setup").catch(() => null),
    ]);
    setStatus(crawl);
    setMailboxes(boxes);
    setSetup(google);
  }, []);

  useEffect(() => {
    load().catch(() => setStatus(null));
  }, [load]);

  // Google returns the browser to this page after consent, carrying the
  // outcome in the query string. Reported here rather than left silent, and
  // the parameters are removed so a refresh does not repeat the message.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const connected = params.get("connected");
    const failed = params.get("error");
    if (!connected && !failed) return;

    if (connected) toast.success(`${connected} is connected.`);
    if (failed) toast.error(failed);
    window.history.replaceState({}, "", window.location.pathname);
    load().catch(() => undefined);
  }, [load, toast]);

  const value = <K extends keyof Organisation>(key: K): Organisation[K] | undefined =>
    (draft[key] ?? organisation?.[key]) as Organisation[K] | undefined;

  const dirty = Object.keys(draft).length > 0;

  async function save() {
    setBusy(true);
    try {
      const updated = await api.patch<Organisation>("/organisation", draft);
      setOrganisation(updated);
      setDraft({});
      await load();
      toast.success("Schedule updated.");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "That could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  async function connectGmail() {
    setBusy(true);
    try {
      const { url } = await api.get<{ url: string }>(
        "/organisation/mailbox/connect-url",
      );
      // A full navigation rather than a popup: Google blocks its consent
      // screen in an iframe, and popup blockers eat the rest.
      window.location.href = url;
    } catch (err) {
      toast.error(
        err instanceof ApiError ? err.message : "Connecting is not available yet.",
      );
      setBusy(false);
    }
  }

  async function connectSample() {
    setBusy(true);
    try {
      await api.post("/organisation/mailbox/sample");
      await load();
      toast.success("Sample enquiries connected. Check for mail to load them.");
    } finally {
      setBusy(false);
    }
  }

  async function disconnect(box: Mailbox) {
    setBusy(true);
    try {
      await api.del(`/organisation/mailbox/${box.id}`);
      await load();
      toast.success("Disconnected. Mail already received is kept.");
    } finally {
      setBusy(false);
    }
  }

  async function checkNow() {
    setBusy(true);
    try {
      const result = await api.post<{ ingested: number; failures: string[] }>(
        "/organisation/mailbox/check-now",
      );
      await load();
      if (result.failures.length > 0) {
        toast.error(result.failures[0]);
      } else {
        toast.success(
          result.ingested > 0
            ? `${result.ingested} new ${result.ingested === 1 ? "message" : "messages"}.`
            : "No new mail.",
        );
      }
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "The check did not run.");
    } finally {
      setBusy(false);
    }
  }

  if (!organisation) return <Loading />;

  return (
    <div className="mx-auto max-w-3xl space-y-5 p-5">
      <p className="text-sm text-ink-soft">
        How often Steel Desk looks for new enquiries.
      </p>

      {status &&
        (() => {
          /* Three things stop mail arriving, and the schedule below is only
             the last of them. Stated in the order they take effect, because
             a card that reads "checking every 10 minutes" while nothing is
             connected describes an intention, not what is happening - and
             leaves the trader with no way to find out why. */
          const halt = !status.poller_running
            ? {
                headline: "Mail checking is switched off on the server.",
                detail:
                  "This schedule is saved but nothing is being fetched. An administrator " +
                  "needs to enable the poller (POLLING_ENABLED).",
              }
            : !status.mailbox_connected
              ? {
                  headline: "No mailbox is connected, so nothing is being fetched.",
                  detail: "Connect the enquiry mailbox below and this schedule takes effect.",
                }
              : !status.enabled
                ? {
                    headline: "Mail checking is paused for this desk.",
                    detail: "Resume it below to start checking again.",
                  }
                : null;

          return (
            <div
              className={`rounded-xl border px-4 py-3 ${
                halt
                  ? "border-attention-line bg-attention-wash"
                  : status.active_now
                    ? "border-good-line bg-good-wash"
                    : "border-rule bg-sunk"
              }`}
            >
              <p className="text-sm font-medium text-ink">
                {halt ? halt.headline : status.reason}
              </p>
              <p className="mt-0.5 text-xs text-ink-faint">
                {halt ? (
                  halt.detail
                ) : (
                  <>
                    It is {status.local_time} at your desk
                    {status.last_polled_at
                      ? ` · last checked ${new Date(status.last_polled_at).toLocaleTimeString()}`
                      : " · not checked yet"}
                  </>
                )}
              </p>
            </div>
          );
        })()}

      <Card
        title="Working hours"
        subtitle="Checked often during the day, sparingly overnight."
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <label>
            <span className="mb-1.5 block text-sm font-medium text-ink">Your timezone</span>
            <Select
              value={value("timezone") ?? "Asia/Kolkata"}
              onChange={(v) => setDraft({ ...draft, timezone: v })}
              options={ZONES}
              className="w-full"
              disabled={!canAdminister}
            />
            <span className="mt-1 block text-xs text-ink-faint">
              The hours below are read on this clock.
            </span>
          </label>

          <div className="grid grid-cols-2 gap-3">
            <label>
              <span className="mb-1.5 block text-sm font-medium text-ink">Day starts</span>
              <Select
                value={(value("crawl_active_from") ?? "08:00").slice(0, 5)}
                onChange={(v) => setDraft({ ...draft, crawl_active_from: v })}
                options={TIMES}
                className="w-full"
                disabled={!canAdminister}
              />
            </label>
            <label>
              <span className="mb-1.5 block text-sm font-medium text-ink">Day ends</span>
              <Select
                value={(value("crawl_active_to") ?? "22:00").slice(0, 5)}
                onChange={(v) => setDraft({ ...draft, crawl_active_to: v })}
                options={TIMES}
                className="w-full"
                disabled={!canAdminister}
              />
            </label>
          </div>

          <label>
            <span className="mb-1.5 block text-sm font-medium text-ink">
              During working hours
            </span>
            <Select
              value={String(value("crawl_active_minutes") ?? 10)}
              onChange={(v) => setDraft({ ...draft, crawl_active_minutes: Number(v) })}
              options={MINUTES}
              className="w-full"
              disabled={!canAdminister}
            />
          </label>

          <label>
            <span className="mb-1.5 block text-sm font-medium text-ink">Outside them</span>
            <Select
              value={String(value("crawl_quiet_minutes") ?? 60)}
              onChange={(v) => setDraft({ ...draft, crawl_quiet_minutes: Number(v) })}
              options={MINUTES}
              className="w-full"
              disabled={!canAdminister}
            />
          </label>
        </div>

        {canAdminister && (
          <div className="mt-5 flex items-center gap-2 border-t border-rule pt-4">
            <Button variant="primary" onClick={save} disabled={!dirty || busy}>
              {busy ? "Saving…" : "Save schedule"}
            </Button>
            {dirty && (
              <Button onClick={() => setDraft({})} disabled={busy}>
                Discard
              </Button>
            )}
            <span className="ml-auto">
              <Button
                compact
                onClick={() =>
                  setDraft({ ...draft, crawl_enabled: !(value("crawl_enabled") ?? true) })
                }
              >
                {value("crawl_enabled") ?? true ? "Pause checking" : "Resume checking"}
              </Button>
            </span>
          </div>
        )}
      </Card>

      <Card
        title="Enquiry mailbox"
        subtitle="The address your customers send enquiries to."
      >
        {mailboxes.length === 0 ? (
          <div>
            <p className="mb-1 text-sm font-medium text-ink">
              Nothing is connected yet, so no enquiries are arriving.
            </p>
            <p className="mb-4 text-sm text-ink-soft">
              Connect the mailbox your customers write to. Steel Desk asks
              Google for permission to <span className="font-medium">read</span>{" "}
              mail and <span className="font-medium">send</span> replies — never
              to change or delete anything.
            </p>
            {canAdminister && (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    variant="primary"
                    onClick={connectGmail}
                    disabled={busy || setup?.ready === false}
                  >
                    Connect your Google account
                  </Button>
                  <Button onClick={connectSample} disabled={busy}>
                    Use sample enquiries instead
                  </Button>
                </div>

                {/* A one-time deployment step, not something a trader did
                    wrong. Said here rather than after they have already left
                    for Google and hit its error page. */}
                {setup && !setup.ready && (
                  <div className="mt-3 rounded-lg border border-attention-line bg-attention-wash p-3">
                    <p className="text-sm font-medium text-attention-ink">
                      Google sign-in is not finished being set up.
                    </p>
                    <p className="mt-1 text-sm text-attention-ink">{setup.problem}</p>
                    <code className="mt-2 block overflow-x-auto rounded bg-surface px-2 py-1.5 text-xs text-ink">
                      {setup.redirect_uri}
                    </code>
                  </div>
                )}
              </>
            )}
            <p className="mt-2 text-xs text-ink-faint">
              The sample option loads example enquiries so you can see how Steel
              Desk works before granting access to a real inbox.
            </p>
          </div>
        ) : (
          <>
            <div className="divide-y divide-rule">
              {mailboxes.map((box) => (
                <div key={box.id} className="flex flex-wrap items-center gap-3 py-2.5">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-ink">
                      {box.email_address}
                      {box.provider === "LOCAL" && (
                        <span className="ml-1.5 text-xs font-normal text-ink-faint">
                          (sample data)
                        </span>
                      )}
                    </p>
                    {box.last_error ? (
                      <p className="text-xs text-danger-ink">{box.last_error}</p>
                    ) : (
                      box.last_polled_at && (
                        <p className="text-xs text-ink-faint">
                          last checked {new Date(box.last_polled_at).toLocaleString()}
                        </p>
                      )
                    )}
                  </div>
                  <span
                    className={`rounded-full px-2 py-0.5 text-[11px] font-medium ${
                      box.status === "CONNECTED"
                        ? "bg-good-wash text-good-ink"
                        : "bg-attention-wash text-attention-ink"
                    }`}
                  >
                    {box.status === "CONNECTED" ? "connected" : "needs attention"}
                  </span>
                  {canAdminister && (
                    <Button compact onClick={() => disconnect(box)} disabled={busy}>
                      Disconnect
                    </Button>
                  )}
                </div>
              ))}
            </div>

            {canAdminister && (
              <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-rule pt-4">
                <Button onClick={checkNow} disabled={busy}>
                  {busy ? "Checking…" : "Check for mail now"}
                </Button>
                <Button compact onClick={connectGmail} disabled={busy}>
                  Connect another mailbox
                </Button>
                <span className="text-xs text-ink-faint">
                  Checking now ignores the schedule above.
                </span>
              </div>
            )}
          </>
        )}
      </Card>
    </div>
  );
}
