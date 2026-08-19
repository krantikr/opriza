import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

/* ---------------------------------------------------------------------------
   The mailbox tabs against the backend's state machine.

   The tabs are a queue of pending work: each message resolves to exactly one
   state on the backend, and leaves it when somebody acts. A tab naming a state
   the backend never produces would simply be permanently empty - silently, and
   with no error to notice - so both sides are read here rather than trusted.
   --------------------------------------------------------------------------- */

const root = resolve(process.cwd());

/** The array literal only - the declaration's type annotation also has "];". */
function foldersBlock(): string {
  const source = readFileSync(`${root}/src/pages/Inbox.tsx`, "utf8");
  const from = source.indexOf("[", source.indexOf("const FOLDERS"));
  return source.slice(from, source.indexOf("\n];", from));
}

function backendStates(): string[] {
  const source = readFileSync(
    `${root}/../backend/app/services/pipeline_state.py`,
    "utf8",
  );
  const block = source.slice(
    source.indexOf("class PipelineState"),
    source.indexOf("#: A quotation that has gone out"),
  );
  return [...block.matchAll(/^\s{4}[A-Z_]+\s*=\s*"([A-Z_]+)"/gm)].map((m) => m[1]);
}

function tabStates(): string[] {
  return [...foldersBlock().matchAll(/state:\s*"([A-Z_]+)"/g)].map((m) => m[1]);
}

describe("mailbox tabs", () => {
  it("only names states the backend actually produces", () => {
    const known = backendStates();
    expect(known).toContain("ENQUIRY");

    const unknown = tabStates().filter((s) => !known.includes(s));
    expect(unknown).toEqual([]);
  });

  it("gives every pending state a tab - DONE is the only exception", () => {
    // Work with nowhere to appear is work that never gets done.
    const pending = backendStates().filter((s) => s !== "DONE");
    const missing = pending.filter((s) => !tabStates().includes(s));
    expect(missing).toEqual([]);
  });

  it("follows the lifecycle a trader actually lives", () => {
    const labels = [...foldersBlock().matchAll(/label:\s*"([^"]+)"/g)].map((m) => m[1]);
    expect(labels).toEqual([
      "All mail",
      "Enquiries",
      "Follow up",
      "Needs reply",
      "Delivery",
      "Complaints",
    ]);
  });

  it("keeps All mail as the only tab that is not pending work", () => {
    // One entry per `label:`, taking the text up to the next label so the
    // type annotation above the array is not mistaken for an entry.
    const block = foldersBlock();
    const entries = block.split(/(?=\{\s*key:)/).filter((e) => e.includes("label:"));
    const withoutState = entries.filter((e) => !e.includes("state:"));

    expect(entries).toHaveLength(6);
    expect(withoutState).toHaveLength(1);
    expect(withoutState[0]).toContain("All mail");
  });

  it("explains each tab's rule, so the model is visible", () => {
    const hints = [...foldersBlock().matchAll(/hint:\s*"([^"]+)"/g)].map((m) => m[1]);
    // One per tab, and none left as a placeholder.
    expect(hints).toHaveLength(6);
    expect(hints.every((h) => h.length > 20)).toBe(true);
  });

  it("stays at six tabs - a long row stops being scannable", () => {
    const labels = [...foldersBlock().matchAll(/label:\s*"([^"]+)"/g)].map((m) => m[1]);
    expect(labels.length).toBeLessThanOrEqual(6);
  });
});
