import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { ago, inr, inrShort, num, toneOf, until, when } from "../components/ui";

/* ---------------------------------------------------------------------------
   Formatting.

   This application is columns of money, so a formatter that quietly rounds or
   drops a figure is a commercial bug, not a cosmetic one. These pin the
   behaviour that the rest of the interface assumes.
   --------------------------------------------------------------------------- */

describe("inr", () => {
  it("groups in the Indian system, not thousands", () => {
    // 12,20,000 - not 1,220,000. Getting this wrong misreads by a factor of ten
    // to anyone scanning the column.
    expect(inr("1220000")).toBe("₹12,20,000.00");
    expect(inr(5714632)).toBe("₹57,14,632.00");
  });

  it("always shows two decimals, so a column stays aligned", () => {
    expect(inr(100)).toBe("₹100.00");
    expect(inr("61000.5")).toBe("₹61,000.50");
  });

  it("can omit the symbol for a table that heads its own column", () => {
    expect(inr("72217.92", false)).toBe("72,217.92");
  });

  it("renders a dash rather than NaN or zero for a missing figure", () => {
    // A missing price must never read as free.
    expect(inr(null)).toBe("—");
    expect(inr(undefined)).toBe("—");
    expect(inr("")).toBe("—");
    expect(inr("not a number")).toBe("—");
  });

  it("keeps a real zero distinct from a missing one", () => {
    expect(inr(0)).toBe("₹0.00");
  });
});

describe("inrShort", () => {
  it("uses lakh and crore, as an Indian desk reads them", () => {
    expect(inrShort(11137500)).toBe("₹1.11Cr");
    expect(inrShort(3812500)).toBe("₹38.13L");
    expect(inrShort(45000)).toBe("₹45.0k");
    expect(inrShort(750)).toBe("₹750");
  });

  it("handles negatives without losing the sign", () => {
    expect(inrShort(-3812500)).toBe("₹-38.13L");
  });

  it("returns a dash for nothing", () => {
    expect(inrShort(null)).toBe("—");
  });
});

describe("num", () => {
  it("trims trailing zeros a tonnage does not need", () => {
    expect(num("28.260")).toBe("28.26");
    expect(num("20.000")).toBe("20");
  });

  it("respects the requested precision", () => {
    expect(num("40.4", 0)).toBe("40");
  });

  it("returns a dash for nothing", () => {
    expect(num(null)).toBe("—");
    expect(num("")).toBe("—");
  });
});

describe("when / ago", () => {
  it("returns a dash rather than 'Invalid Date'", () => {
    expect(when(null)).toBe("—");
    expect(ago(null)).toBe("—");
  });

  it("describes recent times in units a person uses", () => {
    const minutesAgo = new Date(Date.now() - 5 * 60_000).toISOString();
    const hoursAgo = new Date(Date.now() - 3 * 3_600_000).toISOString();
    const daysAgo = new Date(Date.now() - 4 * 86_400_000).toISOString();

    expect(ago(minutesAgo)).toBe("5m ago");
    expect(ago(hoursAgo)).toBe("3h ago");
    expect(ago(daysAgo)).toBe("4d ago");
  });

  it("falls back to a date once 'days ago' stops being useful", () => {
    const longAgo = new Date(Date.now() - 200 * 86_400_000).toISOString();
    expect(ago(longAgo)).not.toContain("ago");
  });
});

describe("until", () => {
  it("counts forwards, where ago would render a negative", () => {
    // The Follow up tab shows when a nudge falls due, which is in the future.
    // Passing that to `ago` renders "-22h ago", which reads as a bug.
    const soon = new Date(Date.now() + 22 * 3_600_000).toISOString();
    expect(until(soon)).toBe("in 22h");
    expect(ago(soon)).not.toBe("in 22h");
  });

  it("says 'now' once the moment has passed", () => {
    // An overdue trader needs to act, not to do arithmetic.
    const past = new Date(Date.now() - 3 * 3_600_000).toISOString();
    expect(until(past)).toBe("now");
  });

  it("scales through minutes, hours and days", () => {
    expect(until(new Date(Date.now() + 20 * 60_000).toISOString())).toBe("in 20m");
    expect(until(new Date(Date.now() + 3 * 86_400_000).toISOString())).toBe("in 3d");
  });

  it("returns a dash for nothing", () => {
    expect(until(null)).toBe("—");
  });
});

describe("toneOf", () => {
  it("maps a status needing a human to attention, not to success", () => {
    expect(toneOf("READY_FOR_REVIEW")).toBe("attention");
    expect(toneOf("NEEDS_INFORMATION")).toBe("attention");
  });

  it("maps failure to danger", () => {
    expect(toneOf("FAILED")).toBe("danger");
    expect(toneOf("NO_MATCH")).toBe("danger");
    expect(toneOf("LOW")).toBe("danger");
  });

  it("maps settled outcomes to settled or strong", () => {
    expect(toneOf("APPROVED")).toBe("settled");
    expect(toneOf("SENT")).toBe("strong");
  });

  it("falls back to neutral for anything unrecognised", () => {
    expect(toneOf("SOMETHING_NEW")).toBe("neutral");
    expect(toneOf(null)).toBe("neutral");
  });
});

/* ---------------------------------------------------------------------------
   Error messages a trader can act on.

   The provider returns a wall of JSON. Showing it raw tells a trader nothing
   about whether the enquiry is lost or what to do next, which is the only
   thing they actually need to know.
   --------------------------------------------------------------------------- */

describe("error summaries", () => {
  // Kept in step with the copy in Inbox.tsx by reading it, so the two cannot
  // drift into saying different things about the same failure.
  const source = readFileSync(
    resolve(process.cwd(), "src/pages/Inbox.tsx"),
    "utf8",
  );

  it("has a plain sentence for every failure it recognises", () => {
    const block = source.slice(
      source.indexOf("function summariseError"),
      source.indexOf("/** Colour-blocked initials"),
    );
    for (const cause of ["429", "not a valid model", "api key", "timeout"]) {
      expect(block).toContain(cause);
    }
    // Rate limits are recoverable, and saying so is the whole point.
    expect(block).toMatch(/Nothing is lost/);
  });

  it("keeps the raw text available rather than discarding it", () => {
    expect(source).toContain("Technical detail");
    expect(source).toContain("{data.error_message}");
  });

  it("offers a retry, because most of these failures are transient", () => {
    expect(source).toContain("Try again");
  });
});
