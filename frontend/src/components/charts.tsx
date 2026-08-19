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
    <div className="flex items-end gap-1.5" style={{ height }}>
      {points.map((p, i) => (
        <div key={p.label} className="group flex min-w-0 flex-1 flex-col items-center gap-1">
          <div className="flex h-full w-full items-end justify-center gap-0.5">
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
}: {
  data: BarDatum[];
  size?: number;
  centerLabel?: string;
  centerValue?: string;
}) {
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
              className={DONUT_TONES[i % DONUT_TONES.length]}
            >
              <title>{`${d.label}: ${d.value} (${(fraction * 100).toFixed(0)}%)`}</title>
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
            <span
              className={`size-2 shrink-0 rounded-sm bg-current ${DONUT_TONES[i % DONUT_TONES.length]}`}
            />
            <span className="min-w-0 flex-1 truncate text-ink-soft">{d.label}</span>
            <span className="tabular shrink-0 font-medium text-ink">{d.value}</span>
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
