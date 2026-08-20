/* ---------------------------------------------------------------------------
   The platform operator's console.

   Deliberately plain. This is an internal tool for onboarding and support,
   and the counts are here because they answer the only question that matters
   at a glance: is this desk actually working, or did somebody sign up and
   never connect a mailbox?
   --------------------------------------------------------------------------- */

import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, api } from "../api/client";
import { Button, Card, Loading, when } from "../components/ui";
import { useToast } from "../components/Toasts";
import { useAuth } from "../lib/auth";

interface Overview {
  desks: number;
  active_desks: number;
  suspended_desks: number;
  desks_without_mailbox: number;
  mailboxes_needing_attention: number;
  people: number;
  quotations: number;
  emails_this_week: number;
}

interface DeskDetail extends Desk {
  email_count: number;
  needs_attention: boolean;
  users: { id: number; name: string; email: string; role: string; is_active: boolean; last_login_at: string | null }[];
  mailboxes: { id: number; email_address: string; status: string; last_error: string | null }[];
}

/** One number with its label. Amber when it is a number somebody must act on. */
function Stat({
  label,
  value,
  concerning = false,
}: {
  label: string;
  value: number;
  concerning?: boolean;
}) {
  return (
    <div className="rounded-xl border border-rule bg-surface px-4 py-3">
      <p
        className={`tabular text-2xl font-semibold ${
          concerning && value > 0 ? "text-attention-ink" : "text-ink"
        }`}
      >
        {value}
      </p>
      <p className="mt-0.5 text-xs text-ink-faint">{label}</p>
    </div>
  );
}

interface Desk {
  id: number;
  slug: string;
  name: string;
  status: "ACTIVE" | "SUSPENDED";
  timezone: string;
  crawl_enabled: boolean;
  user_count: number;
  mailbox_count: number;
  quotation_count: number;
  created_at: string | null;
}

export default function Admin() {
  const toast = useToast();
  const navigate = useNavigate();
  const { user, signOut } = useAuth();
  const [desks, setDesks] = useState<Desk[] | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [open, setOpen] = useState<DeskDetail | null>(null);
  const [name, setName] = useState("");
  const [ownerEmail, setOwnerEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [freshLink, setFreshLink] = useState<{ email: string; url: string } | null>(null);

  const load = useCallback(async () => {
    const [list, summary] = await Promise.all([
      api.get<Desk[]>("/admin/organisations"),
      api.get<Overview>("/admin/overview"),
    ]);
    setDesks(list);
    setOverview(summary);
  }, []);

  async function inspect(desk: Desk) {
    setOpen(await api.get<DeskDetail>(`/admin/organisations/${desk.id}`));
  }

  async function reinviteOwner(desk: DeskDetail) {
    const email = window.prompt(
      `Send a new owner invitation for ${desk.name} to which address?`,
    );
    if (!email) return;
    try {
      const invite = await api.post<{ email: string; invite_url: string }>(
        `/admin/organisations/${desk.id}/invite-owner`,
        { email },
      );
      setFreshLink({ email: invite.email, url: invite.invite_url });
      setOpen(null);
      await load();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "That invitation failed.");
    }
  }

  async function remove(desk: DeskDetail) {
    // Typing the handle back is the confirmation. Deleting a desk removes
    // every quotation, customer and email it has, and cannot be undone -
    // suspension is the reversible action and should be the usual one.
    const typed = window.prompt(
      `This permanently deletes ${desk.name} and all of its data. ` +
        `It cannot be undone.\n\nType "${desk.slug}" to confirm.`,
    );
    if (typed === null) return;
    try {
      await api.del(`/admin/organisations/${desk.id}?confirm=${encodeURIComponent(typed)}`);
      toast.success(`${desk.name} was deleted.`);
      setOpen(null);
      await load();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "That desk was not deleted.");
    }
  }

  useEffect(() => {
    load().catch(() => setDesks([]));
  }, [load]);

  async function onboard() {
    setBusy(true);
    try {
      const invite = await api.post<{ email: string; invite_url: string }>(
        "/admin/organisations",
        { name, owner_email: ownerEmail },
      );
      setFreshLink({ email: invite.email, url: invite.invite_url });
      setName("");
      setOwnerEmail("");
      await load();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "That desk could not be created.");
    } finally {
      setBusy(false);
    }
  }

  async function toggle(desk: Desk) {
    const action = desk.status === "ACTIVE" ? "suspend" : "reactivate";
    await api.post(`/admin/organisations/${desk.id}/${action}`);
    toast.success(
      action === "suspend"
        ? `${desk.name} is suspended. Their data is kept.`
        : `${desk.name} can sign in again.`,
    );
    await load();
  }

  if (desks === null) return <Loading />;

  return (
    <div className="mx-auto max-w-5xl space-y-5 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink">Steel Desk platform</h1>
          <p className="mt-0.5 text-sm text-ink-soft">
            {desks.length} desks onboarded. Each sees only its own data.
          </p>
        </div>
        {/* The console has no Shell around it, so it carries its own controls. */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-ink-faint">{user?.email}</span>
          <Button compact onClick={() => navigate("/account")}>
            Your account
          </Button>
          <Button compact onClick={signOut}>
            Sign out
          </Button>
        </div>
      </div>

      {overview && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <Stat label="Active desks" value={overview.active_desks} />
          <Stat label="Suspended" value={overview.suspended_desks} />
          {/* The two that mean somebody should do something today. */}
          <Stat
            label="No mailbox yet"
            value={overview.desks_without_mailbox}
            concerning
          />
          <Stat
            label="Mailboxes broken"
            value={overview.mailboxes_needing_attention}
            concerning
          />
          <Stat label="People" value={overview.people} />
          <Stat label="Mail this week" value={overview.emails_this_week} />
        </div>
      )}

      {freshLink && (
        <Card
          title="Send this to the new owner"
          subtitle="Shown once. They choose their own password from this link."
        >
          <p className="mb-2 text-sm text-ink-soft">
            Invitation for <span className="font-medium text-ink">{freshLink.email}</span>:
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <code className="min-w-0 flex-1 overflow-x-auto rounded bg-sunk px-2.5 py-2 text-xs text-ink">
              {freshLink.url}
            </code>
            <Button
              compact
              onClick={() => {
                navigator.clipboard.writeText(freshLink.url);
                toast.success("Link copied.");
              }}
            >
              Copy
            </Button>
            <Button compact onClick={() => setFreshLink(null)}>
              Done
            </Button>
          </div>
        </Card>
      )}

      <Card title="Onboard a desk" subtitle="Creates the account and invites its owner.">
        <div className="flex flex-wrap items-end gap-2">
          <label className="min-w-[14rem] flex-1">
            <span className="mb-1.5 block text-sm font-medium text-ink">Company name</span>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Alpha Steel Traders"
              className="w-full rounded-lg border border-rule bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-brand"
            />
          </label>
          <label className="min-w-[16rem] flex-1">
            <span className="mb-1.5 block text-sm font-medium text-ink">Owner email</span>
            <input
              value={ownerEmail}
              onChange={(e) => setOwnerEmail(e.target.value)}
              type="email"
              placeholder="owner@alphasteel.com"
              className="w-full rounded-lg border border-rule bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-brand"
            />
          </label>
          <Button variant="primary" onClick={onboard} disabled={busy || !name || !ownerEmail}>
            {busy ? "Creating…" : "Create desk"}
          </Button>
        </div>
      </Card>

      <Card title="All desks" padded={false}>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-rule text-left text-xs text-ink-faint">
                <th className="px-4 py-2 font-medium">Desk</th>
                <th className="px-4 py-2 font-medium">Timezone</th>
                <th className="px-4 py-2 text-right font-medium">People</th>
                <th className="px-4 py-2 text-right font-medium">Mailboxes</th>
                <th className="px-4 py-2 text-right font-medium">Quotations</th>
                <th className="px-4 py-2 font-medium">Since</th>
                <th className="px-4 py-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-rule">
              {desks.map((desk) => (
                <tr key={desk.id} className={desk.status === "SUSPENDED" ? "opacity-60" : ""}>
                  <td className="px-4 py-2.5">
                    <button
                      type="button"
                      onClick={() => inspect(desk)}
                      className="text-left"
                    >
                      <p className="font-medium text-brand hover:underline">{desk.name}</p>
                      <p className="text-xs text-ink-faint">{desk.slug}</p>
                    </button>
                  </td>
                  <td className="px-4 py-2.5 text-ink-soft">{desk.timezone}</td>
                  <td className="tabular px-4 py-2.5 text-right text-ink">{desk.user_count}</td>
                  <td className="tabular px-4 py-2.5 text-right">
                    {/* Zero mailboxes is the signal that onboarding stalled. */}
                    <span className={desk.mailbox_count === 0 ? "text-attention-ink" : "text-ink"}>
                      {desk.mailbox_count}
                    </span>
                  </td>
                  <td className="tabular px-4 py-2.5 text-right text-ink">
                    {desk.quotation_count}
                  </td>
                  <td className="px-4 py-2.5 text-xs text-ink-faint">
                    {when(desk.created_at)}
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    <div className="flex justify-end gap-1.5">
                      <Button compact onClick={() => inspect(desk)}>
                        Open
                      </Button>
                      <Button compact onClick={() => toggle(desk)}>
                        {desk.status === "ACTIVE" ? "Suspend" : "Reactivate"}
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      {open && (
        <div className="fixed inset-0 z-50 flex justify-end">
          <button
            type="button"
            aria-label="Close"
            className="flex-1 bg-ink/20"
            onClick={() => setOpen(null)}
          />
          <div className="w-full max-w-md overflow-y-auto bg-surface p-5 shadow-xl sm:max-w-lg">
            <div className="mb-4 flex items-start justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-ink">{open.name}</h2>
                <p className="text-xs text-ink-faint">
                  {open.slug} · {open.timezone} · since {when(open.created_at)}
                </p>
              </div>
              <Button compact onClick={() => setOpen(null)}>
                Close
              </Button>
            </div>

            {open.needs_attention && (
              <div className="mb-4 rounded-lg border border-attention-line bg-attention-wash px-3 py-2 text-sm text-attention-ink">
                A mailbox on this desk has stopped working. They may not have
                noticed — their inbox simply looks quiet.
              </div>
            )}

            <div className="mb-5 grid grid-cols-3 gap-2">
              <Stat label="Quotations" value={open.quotation_count} />
              <Stat label="Emails" value={open.email_count} />
              <Stat label="People" value={open.user_count} />
            </div>

            <p className="mb-1.5 text-sm font-medium text-ink">Mailboxes</p>
            {open.mailboxes.length === 0 ? (
              <p className="mb-5 text-sm text-ink-soft">
                None connected — this desk is not receiving anything. Onboarding
                has stalled here.
              </p>
            ) : (
              <div className="mb-5 divide-y divide-rule">
                {open.mailboxes.map((box) => (
                  <div key={box.id} className="py-2">
                    <p className="text-sm text-ink">{box.email_address}</p>
                    <p className="text-xs text-ink-faint">
                      {box.status}
                      {box.last_error && ` · ${box.last_error}`}
                    </p>
                  </div>
                ))}
              </div>
            )}

            <p className="mb-1.5 text-sm font-medium text-ink">People</p>
            <div className="mb-5 divide-y divide-rule">
              {open.users.map((person) => (
                <div key={person.id} className="flex items-center gap-2 py-2">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-ink">{person.name}</p>
                    <p className="truncate text-xs text-ink-faint">{person.email}</p>
                  </div>
                  <span className="text-xs text-ink-faint">{person.role}</span>
                  {!person.is_active && (
                    <span className="text-xs text-danger-ink">no access</span>
                  )}
                </div>
              ))}
            </div>

            <div className="flex flex-wrap gap-2 border-t border-rule pt-4">
              <Button onClick={() => reinviteOwner(open)}>
                Invite a new owner
              </Button>
              <Button
                onClick={() => toggle(open).then(() => setOpen(null))}
              >
                {open.status === "ACTIVE" ? "Suspend" : "Reactivate"}
              </Button>
              <Button onClick={() => remove(open)}>Delete permanently</Button>
            </div>
            <p className="mt-2 text-xs text-ink-faint">
              Suspending keeps everything and can be undone. Deleting cannot.
            </p>
          </div>
        </div>
      )}
      {open && (
        <div className="fixed inset-0 z-50 flex justify-end">
          <button
            type="button"
            aria-label="Close"
            className="flex-1 bg-ink/20"
            onClick={() => setOpen(null)}
          />
          <div className="w-full max-w-md overflow-y-auto bg-surface p-5 shadow-xl sm:max-w-lg">
            <div className="mb-4 flex items-start justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-ink">{open.name}</h2>
                <p className="text-xs text-ink-faint">
                  {open.slug} · {open.timezone} · since {when(open.created_at)}
                </p>
              </div>
              <Button compact onClick={() => setOpen(null)}>
                Close
              </Button>
            </div>

            {open.needs_attention && (
              <div className="mb-4 rounded-lg border border-attention-line bg-attention-wash px-3 py-2 text-sm text-attention-ink">
                A mailbox on this desk has stopped working. They may not have
                noticed — their inbox simply looks quiet.
              </div>
            )}

            <div className="mb-5 grid grid-cols-3 gap-2">
              <Stat label="Quotations" value={open.quotation_count} />
              <Stat label="Emails" value={open.email_count} />
              <Stat label="People" value={open.user_count} />
            </div>

            <p className="mb-1.5 text-sm font-medium text-ink">Mailboxes</p>
            {open.mailboxes.length === 0 ? (
              <p className="mb-5 text-sm text-ink-soft">
                None connected — this desk is not receiving anything. Onboarding
                has stalled here.
              </p>
            ) : (
              <div className="mb-5 divide-y divide-rule">
                {open.mailboxes.map((box) => (
                  <div key={box.id} className="py-2">
                    <p className="text-sm text-ink">{box.email_address}</p>
                    <p className="text-xs text-ink-faint">
                      {box.status}
                      {box.last_error && ` · ${box.last_error}`}
                    </p>
                  </div>
                ))}
              </div>
            )}

            <p className="mb-1.5 text-sm font-medium text-ink">People</p>
            <div className="mb-5 divide-y divide-rule">
              {open.users.map((person) => (
                <div key={person.id} className="flex items-center gap-2 py-2">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm text-ink">{person.name}</p>
                    <p className="truncate text-xs text-ink-faint">{person.email}</p>
                  </div>
                  <span className="text-xs text-ink-faint">{person.role}</span>
                  {!person.is_active && (
                    <span className="text-xs text-danger-ink">no access</span>
                  )}
                </div>
              ))}
            </div>

            <div className="flex flex-wrap gap-2 border-t border-rule pt-4">
              <Button onClick={() => reinviteOwner(open)}>
                Invite a new owner
              </Button>
              <Button
                onClick={() => toggle(open).then(() => setOpen(null))}
              >
                {open.status === "ACTIVE" ? "Suspend" : "Reactivate"}
              </Button>
              <Button onClick={() => remove(open)}>Delete permanently</Button>
            </div>
            <p className="mt-2 text-xs text-ink-faint">
              Suspending keeps everything and can be undone. Deleting cannot.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
