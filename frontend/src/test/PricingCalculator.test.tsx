import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PricingCalculator from "../components/PricingCalculator";
import type { PricingComponent, QuotationPricing } from "../api/types";

/* ---------------------------------------------------------------------------
   The pricing calculator.

   The commercially dangerous failures here are silent ones: a figure rendered
   in the wrong row, an override that posts the wrong code, a subtotal offering
   a pencil it should not have. Each is pinned below.
   --------------------------------------------------------------------------- */

const component = (
  code: string,
  label: string,
  kind: string,
  amount: string,
  over: Partial<PricingComponent> = {},
): PricingComponent => ({
  code,
  label,
  kind: kind as PricingComponent["kind"],
  amount,
  note: `${label} note`,
  applied: true,
  overridden: false,
  computed_amount: null,
  subtotal: null,
  meta: {},
  ...over,
});

const pricing: QuotationPricing = {
  id: 1,
  basis: "STOCK",
  basis_note: null,
  base_rate: "72217.92",
  total_cost: "74029.20",
  margin_amount: "2220.88",
  quote_rate: "76250.00",
  line_total: "38125.00",
  currency: "INR",
  quantity_mt: "0.5",
  rules_version: 1,
  components: [
    component("base_price", "Base purchase price", "BASE_PRICE", "72217.92"),
    component("transportation", "Transportation", "TRANSPORTATION", "0.00", {
      applied: false,
      note: "No delivery location was stated, so the quote is on an ex-works basis.",
    }),
    component("handling", "Loading / unloading", "HANDLING", "300.00"),
    component("target_margin", "Target margin", "TARGET_MARGIN", "2220.88"),
    component("rounding", "Rounding", "ROUNDING", "-0.08"),
  ],
  explanation: null,
  warnings: [],
  has_overrides: false,
  draft_stale: false,
  rules_stale: false,
};

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  fetchMock.mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({}),
  });
  vi.stubGlobal("fetch", fetchMock);
});

function renderCalculator(over: Partial<QuotationPricing> = {}, onChange = vi.fn()) {
  render(
    <PricingCalculator
      pricing={{ ...pricing, ...over }}
      quotationId={9}
      lineId={4}
      onChange={onChange}
    />,
  );
  return onChange;
}

describe("the build-up", () => {
  it("shows every component with its figure and its working", () => {
    renderCalculator();

    expect(screen.getByText("Base purchase price")).toBeInTheDocument();
    expect(screen.getByText("72,217.92")).toBeInTheDocument();
    expect(
      screen.getByText(/No delivery location was stated/),
    ).toBeInTheDocument();
  });

  it("separates cost lines from margin lines with the total cost between", () => {
    renderCalculator();

    const rows = screen.getAllByRole("row").map((r) => r.textContent ?? "");
    const totalAt = rows.findIndex((t) => t.includes("Total cost"));
    const handlingAt = rows.findIndex((t) => t.includes("Loading / unloading"));
    const marginAt = rows.findIndex((t) => t.includes("Target margin"));

    // Cost, then the subtotal, then margin: any other order misstates what the
    // margin was taken on.
    expect(handlingAt).toBeLessThan(totalAt);
    expect(totalAt).toBeLessThan(marginAt);
  });

  it("numbers the rows continuously across the total-cost break", () => {
    renderCalculator();
    const rows = screen.getAllByRole("row").map((r) => r.textContent ?? "");
    expect(rows.find((t) => t.includes("Target margin"))).toMatch(/4\./);
    expect(rows.find((t) => t.includes("Rounding"))).toMatch(/5\./);
  });

  it("leads with the recommended quote price", () => {
    renderCalculator();
    expect(screen.getByText("76,250.00 / MT")).toBeInTheDocument();
  });

  it("dims a component that did not apply, but still explains why", () => {
    renderCalculator();
    const row = screen.getByText("Transportation").closest("tr")!;
    expect(row.className).toContain("opacity-60");
    expect(within(row).getByText(/ex-works basis/)).toBeInTheDocument();
  });

  it("surfaces warnings rather than burying them", () => {
    renderCalculator({ warnings: ["Distance to Patna is not configured."] });
    expect(screen.getByText("Distance to Patna is not configured.")).toBeInTheDocument();
  });

  it("leaves warnings to the parent when it has hoisted them", () => {
    /* Every line of a quotation usually fails for the same reason, so the
       engine records the same warning on each. Rendered per line, one fact
       became a stack of identical banners above the figures. */
    render(
      <PricingCalculator
        pricing={{ ...pricing, warnings: ["No base price available."] }}
        quotationId={9}
        lineId={4}
        onChange={vi.fn()}
        hideWarnings
      />,
    );
    expect(screen.queryByText("No base price available.")).toBeNull();
  });

  it("still shows the stale-rules notice when warnings are hoisted", () => {
    /* Staleness is a fact about this line's own figures, not about the
       quotation, so hoisting must not silence it. */
    render(
      <PricingCalculator
        pricing={{ ...pricing, rules_stale: true, warnings: ["No base price available."] }}
        quotationId={9}
        lineId={4}
        onChange={vi.fn()}
        hideWarnings
      />,
    );
    expect(screen.getByText(/priced before the current rules/)).toBeInTheDocument();
  });
});

describe("overriding a figure", () => {
  it("posts the component's own code, not its position", async () => {
    const user = userEvent.setup();
    renderCalculator();

    const row = screen.getByText("Loading / unloading").closest("tr")!;
    await user.click(within(row).getByTitle(/Override this figure/));
    const input = within(row).getByRole("spinbutton");
    await user.clear(input);
    await user.type(input, "500");
    await user.click(within(row).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/quotations/9/lines/4/pricing/override");
    expect(JSON.parse(init.body)).toEqual({
      component_code: "handling",
      amount: "500",
    });
  });

  it("tells the parent so the quote in the list refreshes", async () => {
    const user = userEvent.setup();
    const onChange = renderCalculator();

    const row = screen.getByText("Loading / unloading").closest("tr")!;
    await user.click(within(row).getByTitle(/Override this figure/));
    await user.click(within(row).getByRole("button", { name: "Save" }));

    await waitFor(() => expect(onChange).toHaveBeenCalled());
  });

  it("offers no pencil on the total cost, which has no value of its own", () => {
    renderCalculator();
    const row = screen.getByText("Total cost").closest("tr")!;
    expect(within(row).queryByTitle(/Override/)).toBeNull();
  });

  it("marks an overridden figure and offers to put it back", () => {
    renderCalculator({
      has_overrides: true,
      components: pricing.components.map((c) =>
        c.code === "handling"
          ? { ...c, amount: "500.00", overridden: true, computed_amount: "300.00" }
          : c,
      ),
    });

    const row = screen.getByText("Loading / unloading").closest("tr")!;
    expect(within(row).getByText("500.00").className).toContain("text-brand");
    expect(within(row).getByTitle(/Put this back/)).toBeInTheDocument();
  });

  it("clears an override through the delete route", async () => {
    const user = userEvent.setup();
    renderCalculator({
      components: pricing.components.map((c) =>
        c.code === "handling" ? { ...c, overridden: true } : c,
      ),
    });

    const row = screen.getByText("Loading / unloading").closest("tr")!;
    await user.click(within(row).getByTitle(/Put this back/));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/quotations/9/lines/4/pricing/override/handling");
    expect(init.method).toBe("DELETE");
  });

  it("shows the server's refusal instead of failing silently", async () => {
    const user = userEvent.setup();
    fetchMock.mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({ detail: "This quotation has already been sent." }),
    });
    renderCalculator();

    const row = screen.getByText("Loading / unloading").closest("tr")!;
    await user.click(within(row).getByTitle(/Override this figure/));
    await user.click(within(row).getByRole("button", { name: "Save" }));

    expect(
      await screen.findByText("This quotation has already been sent."),
    ).toBeInTheDocument();
  });

  it("offers no editing at all in read-only mode", () => {
    render(
      <PricingCalculator
        pricing={pricing}
        quotationId={9}
        lineId={4}
        onChange={vi.fn()}
        readOnly
      />,
    );
    expect(screen.queryByTitle(/Override this figure/)).toBeNull();
  });
});
