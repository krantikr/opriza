import { useId, useState } from "react";

/* ---------------------------------------------------------------------------
   Chart primitives, drawn as inline SVG.

   No chart library: these are simple shapes, and hand-drawing them keeps the
   marks on the same type scale and palette as the rest of the interface rather
   than importing a second design system.

   Three rules run through all of them:
   - the value is direct-labelled or reachable without hover, so a tooltip
     enhances rather than gates;
   - the current/latest point is emphasised, because that is what is being
     asked about;
   - a series with no data says so, instead of drawing a flat line that looks
     like a real measurement of zero.
   --------------------------------------------------------------------------- */

export interface BarDatum {
  label: string;
  value: number;
  tone?: "good" | "warn" | "bad" | "neutral" | "brand";
}

const TONE_FILL: Record<NonNullable<BarDatum["tone"]>, string> = {
  good: "bg-settled",
  warn: "bg-attention",
  bad: "bg-danger",
  neutral: "bg-rule-firm",
  brand: "bg-brand",
};

/** Ranked horizontal bars for magnitude-by-category comparisons. */
export function HBarChart({
  data,
  unit,
  emptyMessage = "No data yet.",
}: {
  data: BarDatum[];
  unit?: string;
  emptyMessage?: string;
}) {
  const max = Math.max(1, ...data.map((d) => d.value));
  const total = data.reduce((sum, d) => sum + d.value, 0);

  if (data.length === 0 || total === 0) {
    return <p className="py-4 text-center text-sm text-ink-faint">{emptyMessage}</p>;
  }

  return (
    <div className="flex flex-col gap-2.5">
      {data.map((d) => {
        const pct = (d.value / total) * 100;
        const widthPct = (d.value / max) * 100;
        return (
          <div
            key={d.label}
            tabIndex={0}
            title={`${d.label}: ${d.value.toLocaleString("en-IN")}${unit ? ` ${unit}` : ""} (${pct.toFixed(0)}%)`}
            className="group/bar -mx-1 rounded px-1 py-0.5 outline-none focus-visible:ring-2 focus-visible:ring-brand"
          >
            <div className="mb-1 flex items-baseline justify-between gap-2 text-xs">
              <span className="truncate text-ink-soft">{d.label}</span>
              <span className="tabular shrink-0 font-medium text-ink">
                {d.value.toLocaleString("en-IN")}
                {unit && <span className="ml-0.5 font-normal text-ink-faint">{unit}</span>}
              </span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-sunk">
              <div
                className={`h-full rounded-full transition-all group-hover/bar:brightness-110 ${TONE_FILL[d.tone ?? "brand"]}`}
                style={{ width: `${Math.max(widthPct, d.value > 0 ? 2 : 0)}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ---------------------------------------------------------------------------
   Area / line
   --------------------------------------------------------------------------- */

export interface SeriesPoint {
  label: string;
  value: number;
}

/**
 * A trend over time with a soft fill, a faint baseline grid and an emphasised
 * final point. Hovering a column reveals its exact figure; the axis labels and
 * the last value are readable without any interaction at all.
 */
export function AreaChart({
  points,
  height = 160,
  unit = "",
  format = (v: number) => v.toLocaleString("en-IN"),
  emptyMessage = "Nothing recorded in this period.",
}: {
  points: SeriesPoint[];
  height?: number;
  unit?: string;
  format?: (v: number) => string;
  emptyMessage?: string;
}) {
  const gradientId = useId();
  const [hover, setHover] = useState<number | null>(null);

  if (points.length < 2 || points.every((p) => p.value === 0)) {
    return (
      <div
        className="flex items-center justify-center text-sm text-ink-faint"
        style={{ height }}
      >
        {emptyMessage}
      </div>
    );
  }

  const width = 640;
  const padY = 12;
  const max = Math.max(...points.map((p) => p.value));
  const scale = max === 0 ? 0 : (height - padY * 2) / max;
  const step = width / (points.length - 1);

  const coords = points.map((p, i) => ({
    x: i * step,
    y: height - padY - p.value * scale,
    ...p,
  }));

  const line = coords.map((c) => `${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(" ");
  const area = `${line} ${width},${height} 0,${height}`;
  const last = coords[coords.length - 1];
  const active = hover === null ? last : coords[hover];

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        style={{ height }}
        preserveAspectRatio="none"
        role="img"
        aria-label={`Trend from ${points[0].label} to ${points[points.length - 1].label}`}
      >
        <defs>
          <linearGradient id={gradientId} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor="currentColor" stopOpacity="0.22" />
            <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* Baseline grid: three faint rules, enough to read height against. */}
        {[0.25, 0.5, 0.75].map((f) => (
          <line
            key={f}
            x1="0"
            x2={width}
            y1={padY + (height - padY * 2) * f}
            y2={padY + (height - padY * 2) * f}
            className="stroke-rule"
            strokeWidth="1"
            vectorEffect="non-scaling-stroke"
          />
        ))}

        <polygon points={area} fill={`url(#${gradientId})`} className="text-brand" />
        <polyline
          points={line}
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
          className="text-brand"
        />

        {active && (
          <line
            x1={active.x}
            x2={active.x}
            y1={padY}
            y2={height}
            className="stroke-rule-firm"
            strokeWidth="1"
            strokeDasharray="3 3"
            vectorEffect="non-scaling-stroke"
          />
        )}
        {active && (
          <circle cx={active.x} cy={active.y} r="4" className="fill-brand" vectorEffect="non-scaling-stroke" />
        )}

        {/* Invisible hit columns: hovering anywhere in the band selects it. */}
        {coords.map((c, i) => (
          <rect
            key={c.label}
            x={c.x - step / 2}
            y={0}
            width={step}
            height={height}
            fill="transparent"
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover(null)}
          />
        ))}
      </svg>

      <div className="mt-1 flex items-baseline justify-between text-[11px] text-ink-faint">
        <span>{points[0].label}</span>
        <span className="tabular font-medium text-ink">
          {active && `${active.label}: ${format(active.value)}${unit}`}
        </span>
        <span>{points[points.length - 1].label}</span>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------------------
   Grouped columns
   --------------------------------------------------------------------------- */

/**
 * Two series side by side per bucket - this period against the last. Pairing
 * the columns is what makes the comparison readable at a glance; stacking or
 * overlaying them would not.
 */
export function ColumnChart({
  points,
  height = 150,
  format = (v: number) => v.toLocaleString("en-IN"),
}: {
  points: { label: string; current: number; previous?: number }[];
  height?: number;
  format?: (v: number) => string;
}) {
  const max = Math.max(1, ...points.flatMap((p) => [p.current, p.previous ?? 0]));
  const empty = points.every((p) => p.current === 0 && !p.previous);
  // Past a handful of columns the labels stop fitting; showing every other one
  // keeps the axis readable instead of printing truncated stubs.
  const labelEvery = points.length > 8 ? Math.ceil(points.length / 6) : 1;

  if (empty) {
    return (
      <div
        className="flex items-center justify-center text-sm text-ink-faint"
        style={{ height }}
      >
        Not enough history to compare yet.
      </div>
    );
  }

  return (
    // `items-stretch`, not `items-end`: the columns must take the full height
    // of the row so the percentage-sized bars inside them have something
    // definite to measure against. Aligning the row to the end instead
    // shrink-wraps every column to its label, and the bars vanish while the
    // axis still draws. Each column ends its own bars with `items-end`.
    <div className="flex items-stretch gap-1.5" style={{ height }}>
      {points.map((p, i) => (
        // `min-h-0 flex-1` on the column and `min-h-0 flex-1` on the plot area:
        // the bars are sized as a percentage of their parent, so that parent
        // needs a definite height. Without it `h-full` resolves against an
        // auto-height flex item, collapses to zero, and every bar disappears
        // while the axis labels still draw - a chart that looks merely empty.
        <div key={p.label} className="group flex min-h-0 min-w-0 flex-1 flex-col items-center gap-1">
          <div className="flex min-h-0 w-full flex-1 items-end justify-center gap-0.5">
            {p.previous !== undefined && (
              <div
                title={`Previous: ${format(p.previous)}`}
                className={`w-full max-w-3 rounded-t-sm transition-all ${
                  p.previous > 0 ? "bg-rule-firm" : "bg-rule"
                }`}
                style={{ height: `${Math.max((p.previous / max) * 100, 1.5)}%` }}
              />
            )}
            <div
              title={`${p.label}: ${format(p.current)}`}
              className={`w-full max-w-3 rounded-t-sm transition-all group-hover:brightness-110 ${
                p.current > 0 ? "bg-brand" : "bg-rule"
              }`}
              style={{ height: `${Math.max((p.current / max) * 100, 1.5)}%` }}
            />
          </div>
          <span className="w-full truncate text-center text-[10px] text-ink-faint">
            {i % labelEvery === 0 ? p.label : ""}
          </span>
        </div>
      ))}
    </div>
  );
}

/* ---------------------------------------------------------------------------
   Donut
   --------------------------------------------------------------------------- */

const DONUT_TONES = [
  "text-brand",
  "text-attention",
  "text-settled",
  "text-info",
  "text-danger",
  "text-ink-faint",
];

/** Composition of a whole, with the total held in the middle. */
export function DonutChart({
  data,
  size = 132,
  centerLabel,
  centerValue,
  tones,
  format,
}: {
  data: BarDatum[];
  size?: number;
  centerLabel?: string;
  centerValue?: string;
  /** Per-slice `text-*` classes, when the meaning of a slice fixes its colour -
   *  deadstock is red wherever it happens to sit in the series. */
  tones?: string[];
  format?: (v: number) => string;
}) {
  const palette = (i: number) => tones?.[i] ?? DONUT_TONES[i % DONUT_TONES.length];
  const show = format ?? ((v: number) => v.toLocaleString("en-IN"));
  const total = data.reduce((sum, d) => sum + d.value, 0);
  const radius = size / 2 - 10;
  const circumference = 2 * Math.PI * radius;

  if (total === 0) {
    return <p className="py-6 text-center text-sm text-ink-faint">Nothing to show yet.</p>;
  }

  let offset = 0;

  return (
    <div className="flex items-center gap-5">
      <svg width={size} height={size} className="shrink-0 -rotate-90" role="img" aria-label="Composition">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          className="stroke-sunk"
          strokeWidth="12"
        />
        {data.map((d, i) => {
          const fraction = d.value / total;
          const dash = fraction * circumference;
          const element = (
            <circle
              key={d.label}
              cx={size / 2}
              cy={size / 2}
              r={radius}
              fill="none"
              stroke="currentColor"
              strokeWidth="12"
              strokeDasharray={`${dash} ${circumference - dash}`}
              strokeDashoffset={-offset}
              className={palette(i)}
            >
              <title>{`${d.label}: ${show(d.value)} (${(fraction * 100).toFixed(0)}%)`}</title>
            </circle>
          );
          offset += dash;
          return element;
        })}
      </svg>

      <div className="flex min-w-0 flex-col gap-1.5">
        {centerValue && (
          <div className="mb-1">
            <p className="tabular text-xl font-semibold leading-none text-ink">{centerValue}</p>
            {centerLabel && <p className="text-[11px] text-ink-faint">{centerLabel}</p>}
          </div>
        )}
        {data.map((d, i) => (
          <div key={d.label} className="flex items-center gap-2 text-xs">
            <span className={`size-2 shrink-0 rounded-sm bg-current ${palette(i)}`} />
            <span className="min-w-0 flex-1 truncate text-ink-soft">{d.label}</span>
            <span className="tabular shrink-0 font-medium text-ink">{show(d.value)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------------------
   Funnel
   --------------------------------------------------------------------------- */

/** Stage-to-stage progression, where the drop between rows is the message. */
export function FunnelChart({
  stages,
}: {
  stages: { stage: string; count: number; note?: string }[];
}) {
  const peak = Math.max(1, ...stages.map((s) => s.count));

  return (
    <div className="flex flex-col gap-2">
      {stages.map((s, i) => {
        const previous = i > 0 ? stages[i - 1].count : null;
        const drop = previous && previous > 0 ? 1 - s.count / previous : null;
        return (
          <div key={s.stage} className="flex items-center gap-3">
            <span className="w-36 shrink-0 truncate text-sm text-ink-soft">{s.stage}</span>
            <div className="h-6 flex-1 overflow-hidden rounded-sm bg-sunk">
              <div
                className="flex h-full items-center rounded-sm bg-brand/80 px-2 transition-[width]"
                style={{ width: `${Math.max((s.count / peak) * 100, s.count ? 6 : 0)}%` }}
              >
                <span className="tabular text-[11px] font-semibold text-white">{s.count}</span>
              </div>
            </div>
            <span className="w-24 shrink-0 text-right text-[11px] text-ink-faint">
              {drop !== null && drop > 0 ? `−${(drop * 100).toFixed(0)}%` : ""}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/* ---------------------------------------------------------------------------
   Stacked columns
   --------------------------------------------------------------------------- */

export interface StackSeries {
  key: string;
  label: string;
  /** A `bg-*` utility. Kept as a class so the palette stays in the token file. */
  fill: string;
}

export interface StackPoint {
  label: string;
  values: Record<string, number>;
}

/** Composition over time: several series stacked on a shared zero baseline.
 *
 *  A trading period is made of parts - what was quoted, what closed, what was
 *  declined - and the question is nearly always "how did the mix change?".
 *  Separate lines make the reader add the parts up mentally; stacking states
 *  the total and the split in one mark.
 *
 *  Negative values stack downward from the baseline, so a loss reads as a
 *  descent rather than as a bar that merely got shorter. */
export function StackedBarChart({
  points,
  series,
  height = 210,
  format = (v: number) => v.toLocaleString("en-IN"),
  emptyMessage = "Nothing recorded in this period.",
}: {
  points: StackPoint[];
  series: StackSeries[];
  height?: number;
  format?: (v: number) => string;
  emptyMessage?: string;
}) {
  const [hover, setHover] = useState<number | null>(null);

  const totals = points.map((p) => {
    let up = 0;
    let down = 0;
    for (const s of series) {
      const v = p.values[s.key] ?? 0;
      if (v >= 0) up += v;
      else down += v;
    }
    return { up, down };
  });

  const ceiling = Math.max(0, ...totals.map((t) => t.up));
  const floor = Math.min(0, ...totals.map((t) => t.down));
  const span = ceiling - floor;

  if (points.length === 0 || span === 0) {
    return (
      <div className="flex items-center justify-center text-sm text-ink-faint" style={{ height }}>
        {emptyMessage}
      </div>
    );
  }

  // Where zero sits, as a share of the plot from the top. With no negative
  // values this is the bottom edge and the chart looks like ordinary columns.
  const zero = (ceiling / span) * 100;
  const labelEvery = points.length > 8 ? Math.ceil(points.length / 6) : 1;

  return (
    <div>
      <div className="relative flex items-stretch gap-1" style={{ height }}>
        {/* The zero line is the reading anchor: above it is profit, below is loss. */}
        <div
          className="pointer-events-none absolute inset-x-0 border-t border-rule-firm"
          style={{ top: `${zero}%` }}
        />

        {points.map((p, i) => {
          const up = series.filter((s) => (p.values[s.key] ?? 0) > 0);
          const down = series.filter((s) => (p.values[s.key] ?? 0) < 0);
          const active = hover === i;

          return (
            <div
              key={p.label}
              className="group relative flex min-w-0 flex-1 flex-col"
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
            >
              {/* Above the baseline */}
              {/* `justify-end` seats the stack on the zero line; without it the
                  column floats above the axis with a gap beneath it. Series are
                  declared bottom-up, so they are reversed here to paint from
                  the top of a column-direction flex box downward. */}
              <div
                className="flex w-full flex-col justify-end"
                style={{ height: `${zero}%` }}
              >
                {[...up].reverse().map((s) => (
                  <div
                    key={s.key}
                    className={`${s.fill} mx-auto w-full max-w-8 transition-opacity ${
                      hover !== null && !active ? "opacity-40" : ""
                    }`}
                    style={{ height: `${((p.values[s.key] ?? 0) / span) * 100}%` }}
                    title={`${s.label}: ${format(p.values[s.key] ?? 0)}`}
                  />
                ))}
              </div>

              {/* Below the baseline */}
              <div className="flex w-full flex-col" style={{ height: `${100 - zero}%` }}>
                {down.map((s) => (
                  <div
                    key={s.key}
                    className={`${s.fill} mx-auto w-full max-w-8 transition-opacity ${
                      hover !== null && !active ? "opacity-40" : ""
                    }`}
                    style={{ height: `${(Math.abs(p.values[s.key] ?? 0) / span) * 100}%` }}
                    title={`${s.label}: ${format(p.values[s.key] ?? 0)}`}
                  />
                ))}
              </div>

              {active && (
                <div className="pointer-events-none absolute -top-1 left-1/2 z-10 min-w-36 -translate-x-1/2 -translate-y-full rounded-lg border border-rule bg-surface p-2 shadow-lg">
                  <p className="mb-1 text-[11px] font-medium text-ink">{p.label}</p>
                  {series.map((s) => (
                    <div key={s.key} className="flex items-center gap-2 text-[11px]">
                      <span className={`size-2 shrink-0 rounded-sm ${s.fill}`} />
                      <span className="flex-1 text-ink-faint">{s.label}</span>
                      <span className="tabular font-medium text-ink">
                        {format(p.values[s.key] ?? 0)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="mt-1.5 flex gap-1">
        {points.map((p, i) => (
          <span
            key={p.label}
            className="min-w-0 flex-1 truncate text-center text-[10px] text-ink-faint"
          >
            {i % labelEvery === 0 ? p.label : ""}
          </span>
        ))}
      </div>
    </div>
  );
}

/** The key beneath a stacked chart. Separate from the chart so a caller can
 *  place it where the layout wants it. */
export function StackLegend({ series }: { series: StackSeries[] }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5">
      {series.map((s) => (
        <span key={s.key} className="flex items-center gap-1.5 text-[11px] text-ink-soft">
          <span className={`size-2 shrink-0 rounded-sm ${s.fill}`} />
          {s.label}
        </span>
      ))}
    </div>
  );
}

/* ---------------------------------------------------------------------------
   Multi-line
   --------------------------------------------------------------------------- */

export interface LineSeries {
  key: string;
  label: string;
  /** A CSS colour, not a class: the same series definitions are handed to the
   *  server-rendered HTML report, which has no Tailwind. */
  colour: string;
  dashed?: boolean;
}

/** Two or more series against a shared scale.
 *
 *  Stacked columns answer "what is this total made of"; two lines answer
 *  "did these two move together?" - which is the question behind quoted
 *  against sold. Plotting them as one stack would hide the gap, and the gap
 *  is the conversion story. */
export function MultiLineChart({
  points,
  series,
  height = 180,
  format = (v: number) => v.toLocaleString("en-IN"),
  emptyMessage = "Not enough history to plot a trend.",
}: {
  points: { label: string; values: Record<string, number> }[];
  series: LineSeries[];
  height?: number;
  format?: (v: number) => string;
  emptyMessage?: string;
}) {
  const [hover, setHover] = useState<number | null>(null);

  const peak = Math.max(
    1,
    ...points.flatMap((p) => series.map((s) => p.values[s.key] ?? 0)),
  );

  if (points.length < 2) {
    return (
      <div className="flex items-center justify-center text-sm text-ink-faint" style={{ height }}>
        {emptyMessage}
      </div>
    );
  }

  const W = 320;
  const H = 120;
  const pad = 4;
  const x = (i: number) => pad + (i / (points.length - 1)) * (W - pad * 2);
  const y = (v: number) => H - pad - (v / peak) * (H - pad * 2);

  return (
    <div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        style={{ height }}
        preserveAspectRatio="none"
        role="img"
        aria-label="Trend"
        onMouseLeave={() => setHover(null)}
      >
        {[0.25, 0.5, 0.75].map((f) => (
          <line
            key={f}
            x1={0}
            x2={W}
            y1={pad + f * (H - pad * 2)}
            y2={pad + f * (H - pad * 2)}
            className="stroke-rule"
            strokeWidth="0.5"
          />
        ))}

        {series.map((s) => (
          <polyline
            key={s.key}
            fill="none"
            stroke={s.colour}
            strokeWidth="1.5"
            strokeDasharray={s.dashed ? "3 2" : undefined}
            strokeLinejoin="round"
            strokeLinecap="round"
            vectorEffect="non-scaling-stroke"
            points={points.map((p, i) => `${x(i)},${y(p.values[s.key] ?? 0)}`).join(" ")}
          />
        ))}

        {points.map((p, i) => (
          <rect
            key={p.label}
            x={x(i) - (W / points.length) / 2}
            y={0}
            width={W / points.length}
            height={H}
            fill="transparent"
            onMouseEnter={() => setHover(i)}
          />
        ))}

        {hover !== null && (
          <line
            x1={x(hover)}
            x2={x(hover)}
            y1={0}
            y2={H}
            className="stroke-rule-firm"
            strokeWidth="0.5"
          />
        )}
      </svg>

      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1">
        {series.map((s) => (
          <span key={s.key} className="flex items-center gap-1.5 text-[11px] text-ink-soft">
            <span
              className="inline-block h-0.5 w-3.5 shrink-0"
              style={{
                background: s.dashed ? "none" : s.colour,
                borderTop: s.dashed ? `1.5px dashed ${s.colour}` : undefined,
              }}
            />
            {s.label}
            {hover !== null && (
              <span className="tabular font-medium text-ink">
                {format(points[hover].values[s.key] ?? 0)}
              </span>
            )}
          </span>
        ))}
        {hover !== null && (
          <span className="text-[11px] text-ink-faint">{points[hover].label}</span>
        )}
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------------------
   Waterfall
   --------------------------------------------------------------------------- */

export interface WaterfallStep {
  label: string;
  value: number;
  /** A total rests on the baseline; a step floats where the running sum left it. */
  total?: boolean;
  colour: string;
}

/** How a starting figure becomes a finishing one.
 *
 *  Revenue less cost equals profit is a *subtraction*, and a waterfall is the
 *  only common chart that draws subtraction: the deduction hangs below the bar
 *  it came out of, so the eye sees the gross profit bar as the remainder rather
 *  than as a third unrelated quantity. */
export function WaterfallChart({
  steps,
  height = 180,
  format = (v: number) => v.toLocaleString("en-IN"),
}: {
  steps: WaterfallStep[];
  height?: number;
  format?: (v: number) => string;
}) {
  let running = 0;
  const bars = steps.map((s) => {
    const start = s.total ? 0 : running;
    const end = s.total ? s.value : running + s.value;
    if (!s.total) running += s.value;
    else running = s.value;
    return { ...s, start, end };
  });

  const peak = Math.max(1, ...bars.map((b) => Math.max(b.start, b.end)));

  if (peak <= 1) {
    return (
      <div className="flex items-center justify-center text-sm text-ink-faint" style={{ height }}>
        Nothing to reconcile in this period.
      </div>
    );
  }

  return (
    <div>
      {/* `items-stretch`, and the plot row carries the height: a
          percentage-positioned bar needs an ancestor with a resolved height,
          and a flex child sized by its content does not give it one. */}
      <div className="flex items-stretch gap-2">
        {bars.map((b) => {
          const top = Math.max(b.start, b.end);
          const bottom = Math.min(b.start, b.end);
          return (
            <div key={b.label} className="flex min-w-0 flex-1 flex-col items-center">
              <div className="relative w-full" style={{ height }}>
                <div
                  className="absolute inset-x-0 mx-auto max-w-12"
                  style={{
                    background: b.colour,
                    bottom: `${(bottom / peak) * 100}%`,
                    height: `${Math.max(((top - bottom) / peak) * 100, 1)}%`,
                  }}
                  title={`${b.label}: ${format(b.value)}`}
                />
              </div>
              <span className="tabular mt-1.5 w-full truncate text-center text-[11px] font-medium text-ink">
                {format(b.value)}
              </span>
              <span className="w-full truncate text-center text-[10px] text-ink-faint">
                {b.label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
