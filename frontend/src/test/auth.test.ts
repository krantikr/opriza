import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

/* ---------------------------------------------------------------------------
   The client side of tenant isolation.

   The database enforces the real guarantee. What the frontend can still get
   wrong is sending a request without the token, keeping a token the server
   has rejected, or letting an unauthenticated page render desk data. These
   are structural checks on exactly those three.
   --------------------------------------------------------------------------- */

const read = (path: string) =>
  readFileSync(resolve(process.cwd(), path), "utf8");

describe("the API client", () => {
  const source = read("src/api/client.ts");

  it("attaches the token to every request from one place", () => {
    // Per-call headers would mean one forgotten call is an anonymous request
    // that 401s for no visible reason.
    expect(source).toContain("Authorization: `Bearer ${auth}`");
    expect(source.match(/Authorization/g)?.length).toBe(1);
  });

  it("discards a token the server has rejected", () => {
    // Keeping it means every later request retries a credential already known
    // to be dead, and the person sees failures instead of a sign-in page.
    const block = source.slice(
      source.indexOf("if (response.status === 401)"),
      source.indexOf("if (!response.ok)"),
    );
    expect(block).toContain("token.clear()");
    expect(block).toContain("onSessionExpired");
  });

  it("reads the token at call time rather than capturing it once", () => {
    // Captured at module load, a token minted by a later sign-in would never
    // be sent.
    expect(source).toContain("const auth = token.get();");
  });
});

describe("the auth provider", () => {
  const source = read("src/lib/auth.tsx");

  it("waits for the stored token to be checked before deciding", () => {
    // Without this the app shows the sign-in page for a moment to somebody
    // who is already signed in, on every refresh.
    expect(source).toContain("loading");
    expect(source).toContain("setLoading(false)");
  });

  it("clears the session when any request reports it expired", () => {
    expect(source).toContain("setSessionExpiredHandler(signOut)");
  });

  it("derives permissions from the role rather than storing them", () => {
    expect(source).toContain('user.role === "OWNER"');
    expect(source).toContain('user.role === "VIEWER"');
  });

  it("drops the token on sign-out", () => {
    const block = source.slice(source.indexOf("const signOut"), source.indexOf("// A 401"));
    expect(block).toContain("token.clear()");
    expect(block).toContain("setUser(null)");
  });
});

describe("routing", () => {
  const source = read("src/App.tsx");

  it("puts every desk screen behind a session", () => {
    // Only sign-in and invite acceptance may render without a user; a route
    // added outside <Desk> would be reachable by anyone.
    expect(source).toContain('<Route path="/sign-in"');
    expect(source).toContain('<Route path="/accept-invite"');
    expect(source).toContain('<Route path="*" element={<Desk />} />');
  });

  it("sends a caller with no session to sign in", () => {
    expect(source).toContain('if (!user) return <Navigate to="/sign-in" replace />');
  });

  it("keeps the operator console separate from the trading screens", () => {
    // The super admin belongs to no desk, so the trading pages would have
    // nothing to show them.
    expect(source).toContain("user.is_super_admin");
    expect(source).toContain('<Route path="/admin" element={<Admin />} />');
  });
});

describe("the invite screen", () => {
  const source = read("src/pages/SignIn.tsx");

  it("says the password rule before the server refuses it", () => {
    expect(source).toContain("password.length < 10");
    expect(source).toMatch(/10 characters/);
  });

  it("asks for confirmation, because a typo here locks somebody out", () => {
    expect(source).toContain("password !== confirm");
  });

  it("explains an incomplete link instead of failing silently", () => {
    expect(source).toContain("This link is incomplete");
  });
});

describe("changing a password", () => {
  const source = read("src/pages/Account.tsx");

  it("signs the person out, because the server invalidated their token", () => {
    // The password change bumps `token_version`, so the token in hand is
    // already dead. Staying on the page means every later request 401s.
    expect(source).toContain("tokenStore.clear()");
    expect(source).toContain("signOut");
  });

  it("warns that other devices are signed out before it happens", () => {
    expect(source).toMatch(/signs out every device/i);
  });

  it("refuses a new password identical to the current one", () => {
    expect(source).toContain("next === current");
  });
});

describe("connecting a mailbox", () => {
  const source = read("src/pages/MailSchedule.tsx");

  it("navigates to Google rather than opening a popup", () => {
    // Google refuses to render consent in an iframe, and popup blockers eat
    // the alternative.
    expect(source).toContain("window.location.href = url");
  });

  it("reports the outcome Google redirects back with", () => {
    expect(source).toContain('params.get("connected")');
    expect(source).toContain('params.get("error")');
  });

  it("clears the result from the URL so a refresh does not repeat it", () => {
    expect(source).toContain("window.history.replaceState");
  });

  it("says which permissions are being asked for", () => {
    expect(source).toMatch(/never/);
    expect(source).toMatch(/read/);
    expect(source).toMatch(/send/);
  });

  it("offers sample data so the system can be tried without a real inbox", () => {
    expect(source).toContain("connectSample");
  });
});

describe("the operator console", () => {
  const source = read("src/pages/Admin.tsx");

  it("requires the desk handle typed back before deleting", () => {
    // Deleting removes every quotation, customer and email. Suspension is the
    // reversible action and the one that should usually be taken.
    expect(source).toContain("desk.slug");
    expect(source).toMatch(/cannot be undone/i);
  });

  it("highlights the counts that mean somebody must act", () => {
    expect(source).toContain("desks_without_mailbox");
    expect(source).toContain("mailboxes_needing_attention");
    expect(source).toContain("concerning");
  });

  it("recovers a locked-out desk by invitation, not by password reset", () => {
    // The operator must never learn a customer's credentials.
    expect(source).toContain("invite-owner");
  });
});

describe("the invite link", () => {
  it("is presented as shown-once, because only its hash is stored", () => {
    for (const page of ["src/pages/Team.tsx", "src/pages/Admin.tsx"]) {
      expect(read(page)).toMatch(/only once|Shown once/);
    }
  });
});
