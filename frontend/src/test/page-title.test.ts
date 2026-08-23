import { describe, expect, it } from "vitest";

import { pageTitle } from "../components/Shell";

/* ---------------------------------------------------------------------------
   What the app header calls the current page.

   The header is the only place a page is named now - the pages no longer
   print their own <h1> - so a route that falls through to the wrong title is
   a screen that lies about what it is showing.
   --------------------------------------------------------------------------- */

describe("the header's page title", () => {
  it("names each destination", () => {
    expect(pageTitle("/quotations")).toBe("Quotations");
    expect(pageTitle("/follow-ups")).toBe("Follow-ups");
    expect(pageTitle("/stock")).toBe("Stock");
    expect(pageTitle("/settings")).toBe("Settings");
  });

  it("keeps the list's title when one row is open", () => {
    /* The drawer is a view of the list, not a separate page. */
    expect(pageTitle("/quotations/17")).toBe("Quotations");
  });

  it("falls back to Home for the root", () => {
    expect(pageTitle("/")).toBe("Home");
  });

  it("prefers the longest matching prefix", () => {
    /* Every path starts with "/", so an unsorted match would return whichever
       entry happened to come first. Pinned because adding a nested route is
       exactly when this breaks. */
    expect(pageTitle("/mail-schedule")).toBe("Mail checking");
    expect(pageTitle("/account")).toBe("Your account");
  });

  it("does not invent a title for an unknown route", () => {
    expect(pageTitle("/nowhere")).toBe("Home");
  });
});
