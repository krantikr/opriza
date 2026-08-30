import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PricingCalculatorGroup from "../components/PricingCalculatorGroup";
import type { LineItem, PricingComponent, QuotationPricing } from "../api/types";

/* ---------------------------------------------------------------------------
   The pricing calculator, now a single table with a column per despatch
   location a trader has added to compare. The commercially dangerous
   failures are still silent ones: a figure in the wrong column, an override
   posted against the wrong option, a column that can be selected while the
   quotation is frozen.
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

function pricing(over: Partial<QuotationPricing> = {}): QuotationPricing {
  return {
    id: 1,
    despatch_location: null,
    is_selected: true,
    is_manual: false,
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
      component("handling", "Loading / unloading", "HANDLING", "300.00"),
      component("target_margin", "Target margin", "TARGET_MARGIN", "2220.88"),
    ],
    explanation: null,
    warnings: [],
    has_overrides: false,
    draft_stale: false,
    rules_stale: false,
    ...over,
  };
}

function lineItem(over: Partial<LineItem> = {}): LineItem {
  return {
    id: 4,
    line_no: 1,
    raw_text: "IS 2062 E250 Plate",
    product_type: "Plate",
    grade: "E250",
    standard: null,
    thickness_mm: 10,
    width_mm: 1500,
    length_mm: 6000,
    diameter_mm: null,
    quantity: "20",
    quantity_unit: "MT",
    quantity_mt: "20",
    conversion_basis: null,
    remarks: null,
    match_status: "MATCH_FOUND",
    match_score: 100,
    matched_stock_item_id: 1,
    matched_stock_item_name: "E250 Plate",
    matched_stock_item_make: null,
    match_candidates: [],
    stock_availability: null,
    pricing: pricing(),
    pricing_option_count: 1,
    ...over,
  };
}

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

function renderGroup(item: LineItem = lineItem(), readOnly = false, onChanged = vi.fn()) {
  render(
    <PricingCalculatorGroup
      quotationId={9}
      item={item}
      readOnly={readOnly}
      onChanged={onChanged}
    />,
  );
  return onChanged;
}

describe("a single-option line", () => {
  it("shows one price column with every component's figure", () => {
    renderGroup();

    expect(screen.getByText("Base purchase price")).toBeInTheDocument();
    expect(screen.getByText("72,217.92")).toBeInTheDocument();
    expect(screen.getByText("76,250.00")).toBeInTheDocument();
  });

  it("puts the note behind a hover icon, not as visible text", () => {
    renderGroup();
    const row = screen.getByText("Base purchase price").closest("tr")!;
    expect(within(row).getByTitle("Base purchase price note")).toBeInTheDocument();
  });

  it("shows an unpriced line's banner instead of an empty table", () => {
    renderGroup(lineItem({ pricing: null }));
    expect(
      screen.getByText(/This line has not been priced/),
    ).toBeInTheDocument();
  });
});

describe("overriding a figure", () => {
  it("posts the component's code and which option it belongs to", async () => {
    const user = userEvent.setup();
    renderGroup();

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
      despatch_location: null,
    });
  });

  it("offers no editing at all in read-only mode", () => {
    renderGroup(lineItem(), true);
    const row = screen.getByText("Loading / unloading").closest("tr")!;
    expect(within(row).queryByTitle(/Override this figure/)).toBeNull();
  });

  it("offers no + column in read-only mode", () => {
    renderGroup(lineItem(), true);
    expect(screen.queryByTitle("Compare pricing from another location")).toBeNull();
  });
});

describe("comparing locations", () => {
  it("fetches every option once the line has more than one", () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => [
        pricing({ id: 1, despatch_location: null, is_selected: true }),
        pricing({ id: 2, despatch_location: "VARANASI", is_selected: false, base_rate: "50000.00" }),
      ],
    });

    renderGroup(lineItem({ pricing_option_count: 2 }));

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/quotations/9/lines/4/pricing/options",
      expect.anything(),
    );
  });

  it("clicking an unselected column header selects it", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => [
        pricing({ id: 1, despatch_location: null, is_selected: true }),
        pricing({ id: 2, despatch_location: "VARANASI", is_selected: false }),
      ],
    });

    const user = userEvent.setup();
    renderGroup(lineItem({ pricing_option_count: 2 }));

    const header = await screen.findByTitle("Click to select this as the price to send");
    await user.click(header);

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v1/quotations/9/lines/4/pricing/options/2/select",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("the selected column cannot be clicked again", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => [
        pricing({ id: 1, despatch_location: null, is_selected: true }),
        pricing({ id: 2, despatch_location: "VARANASI", is_selected: false }),
      ],
    });

    renderGroup(lineItem({ pricing_option_count: 2 }));
    const selected = await screen.findByTitle("Selected — this is what will be sent");
    expect(selected).toBeDisabled();
  });
});
