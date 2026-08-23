/* ---------------------------------------------------------------------------
   The people on this desk, and the invitations waiting to be accepted.

   An invite link is shown exactly once, because only its hash is stored. The
   interface says so plainly rather than letting somebody close the dialog and
   discover later that the link is gone.
   --------------------------------------------------------------------------- */

import { useCallback, useEffect, useState } from "react";

import { ApiError, api } from "../api/client";
import { Badge, Button, Card, Loading, Select, ago } from "../components/ui";
import { useAuth, type User } from "../lib/auth";
import { useToast } from "../components/Toasts";

interface Invite {
  id: number;
  email: string;
  role: string;
  status: string;
  expires_at: string;
  invite_url: string | null;
}

const ROLES = [
  { value: "MEMBER", label: "Member — can quote, send and chase" },
  { value: "VIEWER", label: "Viewer — can see everything, change nothing" },
  { value: "OWNER", label: "Owner — can also manage the team and settings" },
];

export default function Team() {
  const { user: me, canAdminister } = useAuth();
  const toast = useToast();

  const [team, setTeam] = useState<User[] | null>(null);
  const [invites, setInvites] = useState<Invite[]>([]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("MEMBER");
  const [busy, setBusy] = useState(false);
  //: The one moment a link exists outside the invited person's inbox.
  const [freshLink, setFreshLink] = useState<{ email: string; url: string } | null>(null);

  const load = useCallback(async () => {
    const people = await api.get<User[]>("/team");
    setTeam(people);
    if (canAdminister) {
      setInvites(await api.get<Invite[]>("/team/invites"));
    }
  }, [canAdminister]);

  useEffect(() => {
    load().catch(() => setTeam([]));
  }, [load]);

  async function invite() {
    setBusy(true);
    try {
      const created = await api.post<Invite>("/team/invites", { email, role });
      setFreshLink({ email: created.email, url: created.invite_url ?? "" });
      setEmail("");
      await load();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "The invitation could not be sent.");
    } finally {
      setBusy(false);
    }
  }

  async function revoke(id: number) {
    await api.del(`/team/invites/${id}`);
    toast.success("Invitation revoked.");
    await load();
  }

  async function deactivate(person: User) {
    try {
      await api.post(`/team/${person.id}/deactivate`);
      toast.success(`${person.name} no longer has access.`);
      await load();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "That did not work.");
    }
  }

  if (team === null) return <Loading />;

  return (
    <div className="mx-auto max-w-4xl space-y-5 p-5">
      <p className="text-sm text-ink-soft">
        Everyone who can sign in to this account.
      </p>

      {freshLink && (
        <Card
          title="Send this link to your colleague"
          subtitle="It is shown only once. If you lose it, invite them again."
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

      <Card title="People" subtitle={`${team.length} with access`}>
        <div className="divide-y divide-rule">
          {team.map((person) => (
            <div key={person.id} className="flex flex-wrap items-center gap-3 py-2.5">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-ink">
                  {person.name}
                  {person.id === me?.id && (
                    <span className="ml-1.5 text-xs font-normal text-ink-faint">(you)</span>
                  )}
                </p>
                <p className="truncate text-xs text-ink-faint">{person.email}</p>
              </div>

              <Badge value={person.role} dot={false} />
              {!person.is_active && <Badge value="NO ACCESS" dot={false} />}

              <span className="w-24 text-right text-xs text-ink-faint">
                {person.last_login_at ? ago(person.last_login_at) : "never signed in"}
              </span>

              {canAdminister && person.id !== me?.id && person.is_active && (
                <Button compact onClick={() => deactivate(person)}>
                  Remove access
                </Button>
              )}
            </div>
          ))}
        </div>
      </Card>

      {canAdminister && (
        <Card
          title="Invite a colleague"
          subtitle="They choose their own password, so you never handle it."
        >
          <div className="flex flex-wrap items-end gap-2">
            <label className="min-w-[16rem] flex-1">
              <span className="mb-1.5 block text-sm font-medium text-ink">Email</span>
              <input
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                type="email"
                placeholder="colleague@yourcompany.com"
                className="w-full rounded-lg border border-rule bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-brand"
              />
            </label>
            <label className="min-w-[18rem] flex-1">
              <span className="mb-1.5 block text-sm font-medium text-ink">Role</span>
              <Select value={role} onChange={setRole} options={ROLES} className="w-full" />
            </label>
            <Button variant="primary" onClick={invite} disabled={busy || !email}>
              {busy ? "Sending…" : "Send invitation"}
            </Button>
          </div>

          {invites.length > 0 && (
            <div className="mt-5 border-t border-rule pt-4">
              <p className="mb-2 text-sm font-medium text-ink">Waiting to be accepted</p>
              <div className="divide-y divide-rule">
                {invites.map((invite) => (
                  <div key={invite.id} className="flex items-center gap-3 py-2">
                    <span className="min-w-0 flex-1 truncate text-sm text-ink">
                      {invite.email}
                    </span>
                    <Badge value={invite.role} dot={false} />
                    <span className="text-xs text-ink-faint">
                      expires {ago(invite.expires_at)}
                    </span>
                    <Button compact onClick={() => revoke(invite.id)}>
                      Revoke
                    </Button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
