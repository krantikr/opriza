import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ColumnChart, MultiLineChart, StackedBarChart, WaterfallChart } from "../components/charts";

/* ---------------------------------------------------------------------------
   The bars in a column chart are sized as a percentage of their parent, so
   every box between the fixed-height root and the bar must pass that height
   down. When the root aligned its columns to the end instead of stretching
   them, each column shrink-wrapped to its label, the bars resolved to zero,
   and the chart drew its axis over nothing - a chart that looked merely empty
   rather than broken.

   jsdom does not lay out, so these pin the class contract that carries the
   height rather than the rendered pixels.
   --------------------------------------------------------------------------- */

const POINTS = [
  { label: "04 Aug", current: 82000, previous: undefined },
  { label: "06 Aug", current: 131000, previous: 82000 },
  { label: "08 Aug", current: 96000, previous: 131000 },
];

describe("ColumnChart", () => {
  it("stretches its columns so the bars have a height to measure against", () => {
    const { container } = render(<ColumnChart points={POINTS} />);
    const root = container.querySelector("div[style]") as HTMLElement;

    expect(root.className).toContain("items-stretch");
    // `items-end` on the root would shrink-wrap each column to its label.
    expect(root.className).not.toContain("items-end");
    expect(root.style.height).toBe("150px");
  });

  it("lets each column fill the row rather than sizing to its content", () => {
    const { container } = render(<ColumnChart points={POINTS} />);
    const column = container.querySelector(".group") as HTMLElement;

    expect(column.className).toContain("flex-1");
    expect(column.className).toContain("min-h-0");
  });

  it("gives the plot area a definite height and ends its bars at the baseline", () => {
    const { container } = render(<ColumnChart points={POINTS} />);
    const plot = container.querySelector(".group > div") as HTMLElement;

    expect(plot.className).toContain("flex-1");
    expect(plot.className).toContain("min-h-0");
    // The bars sit on the baseline; only the plot area aligns to the end.
    expect(plot.className).toContain("items-end");
  });

  it("scales every bar against the tallest value in the series", () => {
    const { container } = render(<ColumnChart points={POINTS} />);
    const bars = [...container.querySelectorAll(".max-w-3")] as HTMLElement[];

    // 131000 is the maximum, so it is the only bar at full height.
    expect(bars.some((b) => b.style.height === "100%")).toBe(true);
    expect(bars.every((b) => parseFloat(b.style.height) > 0)).toBe(true);
  });

  it("says so plainly when there is nothing to compare", () => {
    const { getByText } = render(
      <ColumnChart points={[{ label: "04 Aug", current: 0 }]} />,
    );

    expect(getByText("Not enough history to compare yet.")).toBeTruthy();
  });
});

/* ---------------------------------------------------------------------------
   Stacked columns carry the same percentage-height hazard as ColumnChart, plus
   one of their own: the stack must sit *on* the zero line. A stack that floats
   above the axis still draws every segment, so it looks like a styling quirk
   rather than a misplaced baseline, and the totals silently stop lining up
   with the gridline they are measured against.
   --------------------------------------------------------------------------- */

const SERIES = [
  { key: "cost", label: "Cost of goods", fill: "bg-brand" },
  { key: "profit", label: "Gross profit", fill: "bg-settled" },
];

const STACK = [
  { label: "04 Aug", values: { cost: 818000, profit: 82000 } },
  { label: "06 Aug", values: { cost: 1269000, profit: 131000 } },
];

describe("StackedBarChart", () => {
  it("seats the stack on the zero line rather than floating it", () => {
    const { container } = render(<StackedBarChart points={STACK} series={SERIES} />);
    const positive = container.querySelector(".flex-col.justify-end") as HTMLElement;

    expect(positive.className).toContain("justify-end");
  });

  it("draws one segment per series in every column", () => {
    const { container } = render(<StackedBarChart points={STACK} series={SERIES} />);
    const segments = container.querySelectorAll(".max-w-8");

    expect(segments.length).toBe(STACK.length * SERIES.length);
  });

  it("scales segments against the tallest column, not against each column", () => {
    const { container } = render(<StackedBarChart points={STACK} series={SERIES} />);
    const heights = [...container.querySelectorAll(".max-w-8")].map((el) =>
      parseFloat((el as HTMLElement).style.height),
    );

    // Every segment is a share of the same span, so none can reach 100%
    // while a taller column exists beside it.
    expect(heights.every((h) => h > 0 && h < 100)).toBe(true);
  });

  it("says so plainly when the period holds nothing", () => {
    const { getByText } = render(
      <StackedBarChart
        points={[{ label: "04 Aug", values: { cost: 0, profit: 0 } }]}
        series={SERIES}
        emptyMessage="Nothing recorded in this period."
      />,
    );

    expect(getByText("Nothing recorded in this period.")).toBeTruthy();
  });
});

/* ---------------------------------------------------------------------------
   The waterfall carries the same percentage-height hazard, one level deeper:
   the plot row must have a resolved height, or the bars collapse to nothing
   while the labels underneath still draw - which reads as a styling quirk
   rather than a missing chart.
   --------------------------------------------------------------------------- */

describe("WaterfallChart", () => {
  const STEPS = [
    { label: "Revenue", value: 14200000, total: true, colour: "#475569" },
    { label: "Less cost", value: -12920000, colour: "#2563EB" },
    { label: "Gross profit", value: 1280000, total: true, colour: "#059669" },
  ];

  it("gives the plot row a resolved height so the bars can size against it", () => {
    const { container } = render(<WaterfallChart steps={STEPS} />);
    const plot = container.querySelector(".relative.w-full") as HTMLElement;

    expect(plot.style.height).toBe("180px");
  });

  it("hangs the deduction below the bar it came out of", () => {
    const { container } = render(<WaterfallChart steps={STEPS} />);
    const fills = [...container.querySelectorAll("[title]")] as HTMLElement[];

    // The cost step starts where revenue ended, so it does not sit on zero.
    expect(fills[1].style.bottom).not.toBe("0%");
    expect(parseFloat(fills[1].style.height)).toBeGreaterThan(0);
  });

  it("draws every step with a visible height", () => {
    const { container } = render(<WaterfallChart steps={STEPS} />);
    const fills = [...container.querySelectorAll("[title]")] as HTMLElement[];

    expect(fills.length).toBe(3);
    expect(fills.every((f) => parseFloat(f.style.height) > 0)).toBe(true);
  });
});

describe("MultiLineChart", () => {
  const POINTS = [
    { label: "04 Jul", values: { quoted: 1300000, sold: 900000 } },
    { label: "07 Jul", values: { quoted: 1900000, sold: 1400000 } },
    { label: "10 Jul", values: { quoted: 1600000, sold: 1100000 } },
  ];
  const SERIES = [
    { key: "quoted", label: "Quoted", colour: "#94A3B8", dashed: true },
    { key: "sold", label: "Sold", colour: "#2563EB" },
  ];

  it("draws one polyline per series so the gap between them stays visible", () => {
    const { container } = render(<MultiLineChart points={POINTS} series={SERIES} />);

    expect(container.querySelectorAll("polyline").length).toBe(2);
  });

  it("scales both series against one shared peak", () => {
    const { container } = render(<MultiLineChart points={POINTS} series={SERIES} />);
    const lines = [...container.querySelectorAll("polyline")] as unknown as SVGElement[];
    const ys = lines.flatMap((l) =>
      (l.getAttribute("points") ?? "").split(" ").map((pair) => parseFloat(pair.split(",")[1])),
    );

    // A shared scale means no point escapes the plot box in either direction.
    expect(ys.every((y) => y >= 0 && y <= 120)).toBe(true);
  });

  it("says so plainly when there is only one bucket", () => {
    const { getByText } = render(
      <MultiLineChart
        points={[POINTS[0]]}
        series={SERIES}
        emptyMessage="A trend needs two."
      />,
    );

    expect(getByText("A trend needs two.")).toBeTruthy();
  });
});
