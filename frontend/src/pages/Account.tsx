/* ---------------------------------------------------------------------------
   Your own account.

   Changing a password signs out every other session, which is the point - if
   you are changing it because something felt wrong, half-measures are no use.
   The interface says so before you do it rather than after.
   --------------------------------------------------------------------------- */

import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError, api, token as tokenStore } from "../api/client";
import { Button, Card } from "../components/ui";
import { useToast } from "../components/Toasts";
import { useAuth } from "../lib/auth";

export default function Account() {
  const { user, organisation, signOut } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();

  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const tooShort = next.length > 0 && next.length < 10;
  const mismatch = confirm.length > 0 && next !== confirm;
  const same = next.length > 0 && next === current;
  const ready = !!current && next.length >= 10 && next === confirm && !same;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      await api.post("/auth/change-password", {
        current_password: current,
        new_password: next,
      });
      // The token that made this request is now invalid: the server bumped
      // `token_version`. Signing out is the honest response - anything else
      // leaves the app making requests that will 401 on the next page.
      tokenStore.clear();
      toast.success("Password changed. Please sign in again.");
      setTimeout(signOut, 900);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "That could not be saved.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (!user) return null;

  return (
    <div className="mx-auto max-w-2xl space-y-5 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink">Your account</h1>
          <p className="mt-0.5 text-sm text-ink-soft">
            {user.email}
            {organisation && ` · ${organisation.name}`}
          </p>
        </div>
        {/* The operator sees this page outside the Shell, so it needs its own
            way back to the console. */}
        {user.is_super_admin && (
          <Button compact onClick={() => navigate("/admin")}>
            Back to the console
          </Button>
        )}
      </div>

      <Card title="Details">
        <dl className="divide-y divide-rule text-sm">
          <div className="flex justify-between gap-4 py-2">
            <dt className="text-ink-faint">Name</dt>
            <dd className="font-medium text-ink">{user.name}</dd>
          </div>
          <div className="flex justify-between gap-4 py-2">
            <dt className="text-ink-faint">Email</dt>
            <dd className="font-medium text-ink">{user.email}</dd>
          </div>
          <div className="flex justify-between gap-4 py-2">
            <dt className="text-ink-faint">Role</dt>
            <dd className="font-medium text-ink">
              {user.is_super_admin
                ? "Platform operator"
                : user.role === "OWNER"
                  ? "Owner — can manage the team and settings"
                  : user.role === "VIEWER"
                    ? "Viewer — read only"
                    : "Member — can quote, send and chase"}
            </dd>
          </div>
        </dl>
      </Card>

      <Card
        title="Change your password"
        subtitle="This signs out every device you are signed in on, including this one."
      >
        <form onSubmit={submit} className="max-w-sm">
          {error && (
            <div className="mb-4 rounded-lg border border-danger-line bg-danger-wash px-3 py-2.5 text-sm text-danger-ink">
              {error}
            </div>
          )}

          <label className="mb-4 block">
            <span className="mb-1.5 block text-sm font-medium text-ink">
              Current password
            </span>
            <input
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              type="password"
              autoComplete="current-password"
              className="w-full rounded-lg border border-rule bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-brand"
            />
          </label>

          <label className="mb-4 block">
            <span className="mb-1.5 block text-sm font-medium text-ink">
              New password
            </span>
            <input
              value={next}
              onChange={(e) => setNext(e.target.value)}
              type="password"
              autoComplete="new-password"
              placeholder="At least 10 characters"
              className="w-full rounded-lg border border-rule bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-brand"
            />
            {tooShort && (
              <span className="mt-1 block text-xs text-danger-ink">
                A little longer — 10 characters or more.
              </span>
            )}
            {same && (
              <span className="mt-1 block text-xs text-danger-ink">
                That is the password you are already using.
              </span>
            )}
          </label>

          <label className="mb-5 block">
            <span className="mb-1.5 block text-sm font-medium text-ink">
              Confirm new password
            </span>
            <input
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              type="password"
              autoComplete="new-password"
              className="w-full rounded-lg border border-rule bg-surface px-3 py-2 text-sm text-ink outline-none focus:border-brand"
            />
            {mismatch && (
              <span className="mt-1 block text-xs text-danger-ink">
                These two do not match.
              </span>
            )}
          </label>

          <Button type="submit" variant="primary" disabled={busy || !ready}>
            {busy ? "Changing…" : "Change password"}
          </Button>
        </form>
      </Card>
    </div>
  );
}
