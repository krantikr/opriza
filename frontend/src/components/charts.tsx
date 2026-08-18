/** Minimal chart primitives, built in plain HTML/Tailwind — this app has no
 * chart library, and these are simple enough not to need one. */

export interface BarDatum {
  label: string;
  value: number;
  tone?: "good" | "warn" | "bad" | "neutral" | "brand";
}

const TONE_FILL: Record<NonNullable<BarDatum["tone"]>, string> = {
  good: "bg-emerald-600",
  warn: "bg-amber-500",
  bad: "bg-rose-500",
  neutral: "bg-ink-300",
  brand: "bg-sky-600",
};

/** Ranked horizontal bars for magnitude-by-category comparisons.
 *
 * Each row is its own hit target: the value is direct-labeled at the bar's
 * tip so the hover tooltip enhances rather than gates, and the category
 * label sits beside the bar so identity never depends on color alone.
 */
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
    return <p className="text-sm text-ink-500">{emptyMessage}</p>;
  }

  return (
    <div className="space-y-2.5">
      {data.map((d) => {
        const pct = total > 0 ? (d.value / total) * 100 : 0;
        const widthPct = (d.value / max) * 100;
        return (
          <div
            key={d.label}
            tabIndex={0}
            title={`${d.label}: ${d.value.toLocaleString("en-IN")}${unit ? ` ${unit}` : ""} (${pct.toFixed(0)}%)`}
            className="group/bar -mx-1 rounded px-1 py-0.5 outline-none focus-visible:ring-2 focus-visible:ring-sky-500"
          >
            <div className="mb-1 flex items-baseline justify-between gap-2 text-xs">
              <span className="truncate text-ink-700">{d.label}</span>
              <span className="tabular shrink-0 font-medium text-ink-900">
                {d.value.toLocaleString("en-IN")}
                {unit && <span className="ml-0.5 font-normal text-ink-500">{unit}</span>}
              </span>
            </div>
            <div className="h-2 rounded-full bg-ink-100">
              <div
                className={`h-2 rounded-full transition-all group-hover/bar:brightness-110 ${TONE_FILL[d.tone ?? "brand"]}`}
                style={{ width: `${Math.max(widthPct, d.value > 0 ? 2 : 0)}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
