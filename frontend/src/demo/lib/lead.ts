import { industryById } from "../data/industries";
import { PROBLEMS } from "../data/problems";
import type { Business } from "../engine/types";

/* ---------------------------------------------------------------------------
   Saving a demo sign-up as a lead.

   Sent when the visitor presses "Start my demo", to the public
   `/api/v1/leads/demo` route, which stores it in the same `leads` table as
   the Request-access form (source 'demo'); the team sees it in Admin →
   Requests. The demo never waits for it: if the request fails the visitor
   still gets their demo, and the next start tries again.

   Leads are append-only, so the same answers are sent once. Changing details
   and starting again sends a new row with the new answers.
   --------------------------------------------------------------------------- */

const SENT_KEY = "oprisa-demo-lead-sent-v1";

export type DemoLeadPayload = {
  name: string;
  company: string;
  email: string;
  phone: string;
  city: string;
  industry: string;
  industry_label: string;
  revenue: string;
  team: string;
  tally: string;
  problems: string[];
};

export function leadPayload(b: Business): DemoLeadPayload {
  return {
    name: b.owner.trim(),
    company: b.company.trim(),
    email: (b.email ?? "").trim(),
    phone: (b.phone ?? "").trim(),
    city: b.city.trim(),
    industry: b.industry,
    industry_label: industryById(b.industry).label,
    revenue: b.revenue,
    team: b.team,
    tally: b.tally,
    problems: b.problems.map((id) => PROBLEMS.find((p) => p.id === id)?.short ?? id),
  };
}

function lastSent(): string | null {
  try {
    return localStorage.getItem(SENT_KEY);
  } catch {
    return null;
  }
}

function markSent(sig: string) {
  try {
    localStorage.setItem(SENT_KEY, sig);
  } catch {
    /* storage blocked: we may send the same answers again, which is harmless */
  }
}

/** Stores the sign-up, once per set of answers. Never throws. */
export async function saveDemoLead(b: Business, fetcher: typeof fetch = fetch): Promise<"sent" | "skipped" | "failed"> {
  const payload = leadPayload(b);
  const sig = JSON.stringify(payload);
  if (lastSent() === sig) return "skipped";
  try {
    const res = await fetcher("/api/v1/leads/demo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: sig,
      // Lets the request finish even if the visitor closes the tab right away.
      keepalive: true,
    });
    if (!res.ok) return "failed";
    markSent(sig);
    return "sent";
  } catch {
    return "failed";
  }
}
