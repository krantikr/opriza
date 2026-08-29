/* ---------------------------------------------------------------------------
   Sign in, and accept an invitation.

   Both live here because they are the same screen with a different job: one
   proves who you already are, the other decides who you will be. Sharing the
   frame keeps the first impression of the product consistent.
   --------------------------------------------------------------------------- */

import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { Button, Input } from "../components/ui";
import { useAuth } from "../lib/auth";

/** The shared frame: mark, title, and a card holding whatever form applies. */
function AuthFrame({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
}) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-ground px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-7 flex flex-col items-center gap-3 text-center">
          {/* The logo carries its own colour, so it sits on the page rather
              than in a tinted tile - a coloured mark inside a coloured chip
              reads as two logos fighting for the same corner. */}
          <img
            src="/logo.png"
            alt="tDesk"
            width={44}
            height={44}
            className="size-11 object-contain"
          />
          <div>
            <h1 className="text-lg font-semibold text-ink">{title}</h1>
            <p className="mt-1 text-sm text-ink-soft">{subtitle}</p>
          </div>
        </div>

        <div className="rounded-xl border border-rule bg-surface p-6 shadow-sm">
          {children}
        </div>

        <p className="mt-6 text-center text-xs text-ink-faint">
          Steel Desk — quotations, stock and follow-ups in one place.
        </p>
      </div>
    </div>
  );
}

function Label({ children }: { children: ReactNode }) {
  return <span className="mb-1.5 block text-sm font-medium text-ink">{children}</span>;
}

/** An error the person can act on, rather than a status code. */
function Problem({ message }: { message: string }) {
  return (
    <div className="mb-4 rounded-lg border border-danger-line bg-danger-wash px-3 py-2.5 text-sm text-danger-ink">
      {message}
    </div>
  );
}

export function SignIn() {
  const { signIn, user, loading } = useAuth();
  const navigate = useNavigate();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  // Somebody already signed in has no business on this page.
  useEffect(() => {
    if (!loading && user) navigate("/", { replace: true });
  }, [loading, user, navigate]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      await signIn(email, password);
      navigate("/", { replace: true });
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "We could not reach the server. Check your connection and try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthFrame title="Sign in to Steel Desk" subtitle="Use the account your team set up.">
      <form onSubmit={submit}>
        {error && <Problem message={error} />}

        <label className="mb-4 block">
          <Label>Email</Label>
          <Input
            value={email}
            onChange={setEmail}
            type="email"
            placeholder="you@yourcompany.com"
            className="w-full"
          />
        </label>

        <label className="mb-5 block">
          <Label>Password</Label>
          <Input
            value={password}
            onChange={setPassword}
            type="password"
            placeholder="Your password"
            className="w-full"
          />
        </label>

        <Button type="submit" variant="primary" disabled={busy || !email || !password}>
          {busy ? "Signing in…" : "Sign in"}
        </Button>
      </form>

      <p className="mt-5 border-t border-rule pt-4 text-xs text-ink-faint">
        Forgotten your password? Ask your account owner to send a new invitation.
      </p>
    </AuthFrame>
  );
}

export function AcceptInvite() {
  const { acceptInvite } = useAuth();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const inviteToken = params.get("token") ?? "";

  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  // Length is what actually makes a password hard to guess, and the backend
  // enforces the same number - this is the courtesy of saying so early.
  const tooShort = password.length > 0 && password.length < 10;
  const mismatch = confirm.length > 0 && password !== confirm;
  const ready = !!name && password.length >= 10 && password === confirm;

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      await acceptInvite(inviteToken, name, password);
      navigate("/", { replace: true });
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "We could not reach the server. Check your connection and try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (!inviteToken) {
    return (
      <AuthFrame title="This link is incomplete" subtitle="The invitation could not be read.">
        <p className="text-sm text-ink-soft">
          Open the link from your invitation email exactly as it was sent, or ask
          whoever invited you to send a new one.
        </p>
      </AuthFrame>
    );
  }

  return (
    <AuthFrame
      title="Set up your account"
      subtitle="Choose a password and you are in."
    >
      <form onSubmit={submit}>
        {error && <Problem message={error} />}

        <label className="mb-4 block">
          <Label>Your name</Label>
          <Input
            value={name}
            onChange={setName}
            placeholder="As your colleagues know you"
            className="w-full"
          />
        </label>

        <label className="mb-4 block">
          <Label>Password</Label>
          <Input
            value={password}
            onChange={setPassword}
            type="password"
            placeholder="At least 10 characters"
            className="w-full"
          />
          {tooShort && (
            <span className="mt-1 block text-xs text-danger-ink">
              A little longer — 10 characters or more.
            </span>
          )}
        </label>

        <label className="mb-5 block">
          <Label>Confirm password</Label>
          <Input
            value={confirm}
            onChange={setConfirm}
            type="password"
            placeholder="Type it again"
            className="w-full"
          />
          {mismatch && (
            <span className="mt-1 block text-xs text-danger-ink">
              These two do not match.
            </span>
          )}
        </label>

        <Button type="submit" variant="primary" disabled={busy || !ready}>
          {busy ? "Setting up…" : "Create my account"}
        </Button>
      </form>
    </AuthFrame>
  );
}
