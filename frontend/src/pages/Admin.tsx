/* ---------------------------------------------------------------------------
   The platform operator's console.

   A small two-pane app in the desk's own theme: a left rail to move between
   views and a working area. "Desks" is the onboarding + support view; "Requests"
   lists design-partner requests captured by the public marketing form.

   It renders without the trader Shell (the operator belongs to no desk), so it
   carries its own chrome.
   --------------------------------------------------------------------------- */

import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, api } from "../api/client";
import { Button, Card, Loading, ago, when } from "../components/ui";
import { useToast } from "../components/Toasts";
import { useAuth } from "../lib/auth";

/* --- Types ----------------------------------------------------------------- */

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

interface DeskDetail extends Desk {
  email_count: number;
  needs_attention: boolean;
  users: { id: number; name: string; email: string; role: string; is_active: boolean; last_login_at: string | null }[];
  mailboxes: { id: number; email_address: string; status: string; last_error: string | null }[];
}

interface Lead {
  id: number;
  created_at: string;
  name: string;
  company: string;
  email: string;
  phone: string;
  monthly_enquiries: string | null;
  note: string | null;
  source: string;
  status: LeadStatus;
}

type LeadStatus = "new" | "contacted" | "qualified" | "won" | "lost";

const LEAD_STATUSES: LeadStatus[] = ["new", "contacted", "qualified", "won", "lost"];

const STATUS_STYLE: Record<LeadStatus, string> = {
  new: "bg-brand-wash text-brand-ink",
  contacted: "bg-attention-wash text-attention-ink",
  qualified: "bg-info-wash text-info-ink",
  won: "bg-settled-wash text-settled-ink",
  lost: "bg-sunk text-ink-faint",
};

type View = "desks" | "requests";

/* --- Small pieces ---------------------------------------------------------- */

function Stat({ label, value, concerning = false }: { label: string; value: number; concerning?: boolean }) {
  return (
    <div className="rounded-xl border border-rule bg-surface px-4 py-3">
      <p className={`tabular text-2xl font-semibold ${concerning && value > 0 ? "text-attention-ink" : "text-ink"}`}>
        {value}
      </p>
      <p className="mt-0.5 text-xs text-ink-faint">{label}</p>
    </div>
  );
}

function NavItem({
  active,
  onClick,
  icon,
  label,
  badge,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
  badge?: number;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-left text-sm transition ${
        active ? "bg-rail-hover text-rail-ink-strong" : "text-rail-ink hover:bg-rail-hover hover:text-rail-ink-strong"
      }`}
    >
      <span className="grid size-5 place-items-center">{icon}</span>
      <span className="flex-1 font-medium">{label}</span>
      {badge !== undefined && badge > 0 && (
        <span className="tabular rounded-full bg-brand px-1.5 py-0.5 text-[10px] font-semibold text-white">{badge}</span>
      )}
    </button>
  );
}

const IconDesks = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} className="size-[18px]">
    <rect x="3" y="4" width="18" height="12" rx="2" />
    <path d="M8 20h8M12 16v4" />
  </svg>
);
const IconRequests = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} className="size-[18px]">
    <path d="M4 6h16v12H4z" />
    <path d="M4 7l8 6 8-6" />
  </svg>
);

/* --- Page ------------------------------------------------------------------ */

export default function Admin() {
  const toast = useToast();
  const navigate = useNavigate();
  const { user, signOut } = useAuth();

  const [view, setView] = useState<View>("desks");
  const [desks, setDesks] = useState<Desk[] | null>(null);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [leads, setLeads] = useState<Lead[] | null>(null);
  const [open, setOpen] = useState<DeskDetail | null>(null);
  const [name, setName] = useState("");
  const [ownerEmail, setOwnerEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [freshLink, setFreshLink] = useState<{ email: string; url: string } | null>(null);

  const load = useCallback(async () => {
    const [list, summary, leadList] = await Promise.all([
      api.get<Desk[]>("/admin/organisations"),
      api.get<Overview>("/admin/overview"),
      api.get<Lead[]>("/admin/leads").catch(() => [] as Lead[]),
    ]);
    setDesks(list);
    setOverview(summary);
    setLeads(leadList);
  }, []);

  useEffect(() => {
    load().catch(() => {
      setDesks([]);
      setLeads([]);
    });
  }, [load]);

  async function inspect(desk: Desk) {
    setOpen(await api.get<DeskDetail>(`/admin/organisations/${desk.id}`));
  }

  async function reinviteOwner(desk: DeskDetail) {
    const email = window.prompt(`Send a new owner invitation for ${desk.name} to which address?`);
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
    const typed = window.prompt(
      `This permanently deletes ${desk.name} and all of its data. It cannot be undone.\n\nType "${desk.slug}" to confirm.`,
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

  async function onboard() {
    setBusy(true);
    try {
      const invite = await api.post<{ email: string; invite_url: string }>("/admin/organisations", {
        name,
        owner_email: ownerEmail,
      });
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
      action === "suspend" ? `${desk.name} is suspended. Their data is kept.` : `${desk.name} can sign in again.`,
    );
    await load();
  }

  async function setLeadStatus(lead: Lead, status: LeadStatus) {
    // Optimistic: reflect the change immediately, roll back on failure.
    setLeads((cur) => (cur ? cur.map((l) => (l.id === lead.id ? { ...l, status } : l)) : cur));
    try {
      await api.patch<Lead>(`/admin/leads/${lead.id}`, { status });
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not update that request.");
      setLeads((cur) => (cur ? cur.map((l) => (l.id === lead.id ? { ...l, status: lead.status } : l)) : cur));
    }
  }

  if (desks === null) {
    return (
      <div className="grid min-h-screen place-items-center bg-ground">
        <Loading />
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-ground">
      {/* ---- Rail ---- */}
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col justify-between bg-rail p-4 sm:flex">
        <div>
          <div className="mb-6 flex items-center gap-2.5 px-1">
            <img src="/favicon-192.png" alt="" width={28} height={28} className="size-7 rounded-lg" />
            <div className="leading-tight">
              <p className="text-sm font-semibold text-rail-ink-strong">Oprisa</p>
              <p className="text-[11px] text-rail-ink">Platform console</p>
            </div>
          </div>
          <nav className="space-y-1">
            <NavItem active={view === "desks"} onClick={() => setView("desks")} icon={IconDesks} label="Desks" badge={desks.length} />
            <NavItem
              active={view === "requests"}
              onClick={() => setView("requests")}
              icon={IconRequests}
              label="Requests"
              badge={leads?.length ?? 0}
            />
          </nav>
        </div>
        <div className="space-y-1 border-t border-white/10 pt-3">
          <p className="truncate px-3 text-[11px] text-rail-ink">{user?.email}</p>
          <button
            type="button"
            onClick={() => navigate("/account")}
            className="w-full rounded-lg px-3 py-1.5 text-left text-sm text-rail-ink hover:bg-rail-hover hover:text-rail-ink-strong"
          >
            Your account
          </button>
          <button
            type="button"
            onClick={signOut}
            className="w-full rounded-lg px-3 py-1.5 text-left text-sm text-rail-ink hover:bg-rail-hover hover:text-rail-ink-strong"
          >
            Sign out
          </button>
        </div>
      </aside>

      {/* ---- Mobile top bar (rail is hidden) ---- */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-3 border-b border-rule bg-surface px-5 py-3 sm:px-8">
          <div className="flex items-center gap-2">
            <h1 className="text-lg font-semibold text-ink">{view === "desks" ? "Desks" : "Incoming requests"}</h1>
            <span className="text-sm text-ink-faint">
              {view === "desks" ? `${desks.length} onboarded` : `${leads?.length ?? 0} total`}
            </span>
          </div>
          {/* Mobile view switch (the rail is hidden below sm) */}
          <div className="flex gap-1 sm:hidden">
            <Button compact variant={view === "desks" ? "primary" : "ghost"} onClick={() => setView("desks")}>
              Desks
            </Button>
            <Button compact variant={view === "requests" ? "primary" : "ghost"} onClick={() => setView("requests")}>
              Requests
            </Button>
          </div>
        </header>

        <main className="mx-auto w-full max-w-5xl space-y-5 p-5 sm:p-8">
          {freshLink && (
            <Card title="Send this to the new owner" subtitle="Shown once. They choose their own password from this link.">
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

          {view === "desks" ? (
            <DesksView
              desks={desks}
              overview={overview}
              name={name}
              ownerEmail={ownerEmail}
              busy={busy}
              setName={setName}
              setOwnerEmail={setOwnerEmail}
              onboard={onboard}
              inspect={inspect}
            />
          ) : (
            <RequestsView leads={leads} onStatus={setLeadStatus} />
          )}
        </main>
      </div>

      {/* ---- Desk detail drawer (single instance) ---- */}
      {open && (
        <div className="fixed inset-0 z-50 flex justify-end">
          <button type="button" aria-label="Close" className="flex-1 bg-ink/20" onClick={() => setOpen(null)} />
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
                A mailbox on this desk has stopped working. They may not have noticed — their inbox simply looks quiet.
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
                None connected — this desk is not receiving anything. Onboarding has stalled here.
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
                  {!person.is_active && <span className="text-xs text-danger-ink">no access</span>}
                </div>
              ))}
            </div>

            <div className="flex flex-wrap gap-2 border-t border-rule pt-4">
              <Button onClick={() => reinviteOwner(open)}>Invite a new owner</Button>
              <Button onClick={() => toggle(open).then(() => setOpen(null))}>
                {open.status === "ACTIVE" ? "Suspend" : "Reactivate"}
              </Button>
              <Button onClick={() => remove(open)}>Delete permanently</Button>
            </div>
            <p className="mt-2 text-xs text-ink-faint">Suspending keeps everything and can be undone. Deleting cannot.</p>
          </div>
        </div>
      )}
    </div>
  );
}

/* --- Views ----------------------------------------------------------------- */

function DesksView({
  desks,
  overview,
  name,
  ownerEmail,
  busy,
  setName,
  setOwnerEmail,
  onboard,
  inspect,
}: {
  desks: Desk[];
  overview: Overview | null;
  name: string;
  ownerEmail: string;
  busy: boolean;
  setName: (v: string) => void;
  setOwnerEmail: (v: string) => void;
  onboard: () => void;
  inspect: (d: Desk) => void;
}) {
  return (
    <>
      {overview && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <Stat label="Active desks" value={overview.active_desks} />
          <Stat label="Suspended" value={overview.suspended_desks} />
          <Stat label="No mailbox yet" value={overview.desks_without_mailbox} concerning />
          <Stat label="Mailboxes broken" value={overview.mailboxes_needing_attention} concerning />
          <Stat label="People" value={overview.people} />
          <Stat label="Mail this week" value={overview.emails_this_week} />
        </div>
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
                <th className="px-4 py-2 font-medium">Status</th>
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
                <tr
                  key={desk.id}
                  onClick={() => inspect(desk)}
                  tabIndex={0}
                  role="button"
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      inspect(desk);
                    }
                  }}
                  className={`cursor-pointer transition hover:bg-sunk focus:bg-sunk focus:outline-none ${
                    desk.status === "SUSPENDED" ? "opacity-60" : ""
                  }`}
                >
                  <td className="px-4 py-2.5">
                    <p className="font-medium text-ink">{desk.name}</p>
                    <p className="text-xs text-ink-faint">{desk.slug}</p>
                  </td>
                  <td className="px-4 py-2.5">
                    <span
                      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium ${
                        desk.status === "ACTIVE"
                          ? "bg-settled-wash text-settled-ink"
                          : "bg-sunk text-ink-faint"
                      }`}
                    >
                      <span
                        className={`size-1.5 rounded-full ${desk.status === "ACTIVE" ? "bg-settled" : "bg-ink-faint"}`}
                      />
                      {desk.status === "ACTIVE" ? "Active" : "Suspended"}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-ink-soft">{desk.timezone}</td>
                  <td className="tabular px-4 py-2.5 text-right text-ink">{desk.user_count}</td>
                  <td className="tabular px-4 py-2.5 text-right">
                    <span className={desk.mailbox_count === 0 ? "text-attention-ink" : "text-ink"}>
                      {desk.mailbox_count}
                    </span>
                  </td>
                  <td className="tabular px-4 py-2.5 text-right text-ink">{desk.quotation_count}</td>
                  <td className="px-4 py-2.5 text-xs text-ink-faint">{when(desk.created_at)}</td>
                  <td className="px-4 py-2.5 text-right text-ink-faint">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className="ml-auto size-4">
                      <path d="M9 6l6 6-6 6" />
                    </svg>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}

function RequestsView({
  leads,
  onStatus,
}: {
  leads: Lead[] | null;
  onStatus: (lead: Lead, status: LeadStatus) => void;
}) {
  const [filter, setFilter] = useState<LeadStatus | "all">("all");

  if (leads === null) return <Loading />;

  if (leads.length === 0) {
    return (
      <Card title="Incoming requests" subtitle="Design-partner requests from the marketing site land here.">
        <div className="py-10 text-center">
          <div className="mx-auto mb-3 grid size-11 place-items-center rounded-full bg-sunk text-ink-faint">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} className="size-5">
              <path d="M4 6h16v12H4z" />
              <path d="M4 7l8 6 8-6" />
            </svg>
          </div>
          <p className="text-sm font-medium text-ink">No requests yet</p>
          <p className="mt-1 text-sm text-ink-soft">
            When someone submits the Request-access form at <span className="text-ink">opriza.vercel.app</span>, it
            shows here.
          </p>
        </div>
      </Card>
    );
  }

  const counts = leads.reduce<Record<string, number>>((acc, l) => {
    acc[l.status] = (acc[l.status] ?? 0) + 1;
    return acc;
  }, {});
  const shown = filter === "all" ? leads : leads.filter((l) => l.status === filter);

  return (
    <div className="space-y-4">
      {/* Status filter chips */}
      <div className="flex flex-wrap gap-1.5">
        <FilterChip label="All" count={leads.length} active={filter === "all"} onClick={() => setFilter("all")} />
        {LEAD_STATUSES.map((s) => (
          <FilterChip
            key={s}
            label={s}
            count={counts[s] ?? 0}
            active={filter === s}
            onClick={() => setFilter(s)}
          />
        ))}
      </div>

      <div className="space-y-3">
        {shown.map((lead) => (
          <Card key={lead.id} padded>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="font-semibold text-ink">{lead.company}</p>
                  <span className={`rounded-full px-2 py-0.5 text-[11px] font-medium capitalize ${STATUS_STYLE[lead.status]}`}>
                    {lead.status}
                  </span>
                  {lead.monthly_enquiries && (
                    <span className="rounded-full bg-sunk px-2 py-0.5 text-[11px] font-medium text-ink-soft">
                      ~{lead.monthly_enquiries} enquiries/mo
                    </span>
                  )}
                </div>
                <p className="mt-1 text-sm text-ink-soft">
                  {lead.name} ·{" "}
                  <a href={`mailto:${lead.email}`} className="text-brand hover:underline">
                    {lead.email}
                  </a>
                  {lead.phone && (
                    <>
                      {" · "}
                      <a href={`tel:${lead.phone}`} className="text-brand hover:underline">
                        {lead.phone}
                      </a>
                    </>
                  )}
                </p>
                {lead.note && <p className="mt-2 max-w-prose text-sm text-ink">{lead.note}</p>}
              </div>
              <div className="flex flex-col items-end gap-2">
                <p className="text-xs text-ink-faint" title={when(lead.created_at)}>
                  {ago(lead.created_at)}
                </p>
                <label className="sr-only" htmlFor={`status-${lead.id}`}>
                  Status for {lead.company}
                </label>
                <select
                  id={`status-${lead.id}`}
                  value={lead.status}
                  onChange={(e) => onStatus(lead, e.target.value as LeadStatus)}
                  className="rounded-lg border border-rule bg-surface px-2.5 py-1.5 text-sm capitalize text-ink outline-none focus:border-brand"
                >
                  {LEAD_STATUSES.map((s) => (
                    <option key={s} value={s} className="capitalize">
                      {s}
                    </option>
                  ))}
                </select>
              </div>
            </div>
          </Card>
        ))}
        {shown.length === 0 && (
          <p className="py-6 text-center text-sm text-ink-soft">No requests in “{filter}”.</p>
        )}
      </div>
    </div>
  );
}

function FilterChip({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full px-3 py-1 text-xs font-medium capitalize transition ${
        active ? "bg-ink text-surface" : "border border-rule text-ink-soft hover:border-rule-firm hover:text-ink"
      }`}
    >
      {label}
      <span className="tabular ml-1.5 opacity-70">{count}</span>
    </button>
  );
}
