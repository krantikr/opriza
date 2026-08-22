import type { ReactNode } from "react";

import type { Confidence, MatchStatus, QuotationStatus } from "../api/types";

/** Rupee formatting with Indian digit grouping, matching the backend. */
export function inr(value: string | number | null | undefined, withSymbol = true): string {
  if (value === null || value === undefined || value === "") return "—";
  const amount = typeof value === "string" ? Number(value) : value;
  if (Number.isNaN(amount)) return "—";
  const formatted = new Intl.NumberFormat("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
  return withSymbol ? `₹${formatted}` : formatted;
}

/** Compact rupees for tiles, where two decimals are noise: ₹57.3L, ₹1.2Cr. */
export function inrShort(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const amount = typeof value === "string" ? Number(value) : value;
  if (Number.isNaN(amount)) return "—";
  const abs = Math.abs(amount);
  if (abs >= 1e7) return `₹${(amount / 1e7).toFixed(2)}Cr`;
  if (abs >= 1e5) return `₹${(amount / 1e5).toFixed(2)}L`;
  if (abs >= 1e3) return `₹${(amount / 1e3).toFixed(1)}k`;
  return `₹${amount.toFixed(0)}`;
}

export function num(value: string | number | null | undefined, digits = 3): string {
  if (value === null || value === undefined || value === "") return "—";
  const amount = typeof value === "string" ? Number(value) : value;
  if (Number.isNaN(amount)) return "—";
  return String(Number(amount.toFixed(digits)));
}

export function when(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  return date.toLocaleString("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** "3 days ago" - what a trader actually wants on a queue screen. */
export function ago(value: string | null | undefined): string {
  if (!value) return "—";
  const then = new Date(value).getTime();
  const mins = Math.round((Date.now() - then) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(value).toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
}

/** How long until a moment still ahead of us: "in 22h", "in 3d".
 *
 * `ago` counts backwards and would render a future date as "-22h ago", which
 * reads as a bug. Anything already past says "now", because a trader who is
 * overdue does not need the arithmetic - they need to act.
 */
export function until(value: string | null | undefined): string {
  if (!value) return "—";
  const mins = Math.round((new Date(value).getTime() - Date.now()) / 60000);
  if (mins <= 0) return "now";
  if (mins < 60) return `in ${mins}m`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `in ${hours}h`;
  const days = Math.round(hours / 24);
  if (days < 30) return `in ${days}d`;
  return new Date(value).toLocaleDateString("en-IN", { day: "2-digit", month: "short" });
}

/* ---------------------------------------------------------------------------
   Status
   State is encoded in form as well as colour - a dot plus a word - so it stays
   readable to anyone who cannot separate the hues.
   --------------------------------------------------------------------------- */

type Tone = "neutral" | "attention" | "settled" | "danger" | "info" | "strong";

const STATUS_TONE: Record<string, Tone> = {
  NEW: "neutral",
  PROCESSING: "neutral",
  PENDING: "neutral",
  READY_FOR_REVIEW: "attention",
  NEEDS_INFORMATION: "attention",
  NEEDS_REVIEW: "attention",
  MULTIPLE_MATCHES: "attention",
  MEDIUM: "attention",
  DUE: "attention",
  ENQUIRY: "info",
  FOLLOW_UP: "attention",
  NEEDS_REPLY: "danger",
  DELIVERY: "info",
  COMPLAINT: "danger",
  EDITED: "info",
  SCHEDULED: "info",
  APPROVED: "settled",
  SENT: "strong",
  MATCH_FOUND: "settled",
  HIGH: "settled",
  CUSTOMER_ACCEPTED: "strong",
  ACCEPTED: "settled",
  REJECTED: "neutral",
  CUSTOMER_DECLINED: "neutral",
  DECLINED: "neutral",
  SKIPPED: "neutral",
  CANCELLED: "neutral",
  FAILED: "danger",
  NO_MATCH: "danger",
  LOW: "danger",
};

const TONE_STYLES: Record<Tone, string> = {
  neutral: "bg-sunk text-ink-soft",
  attention: "bg-attention-wash text-attention-ink",
  settled: "bg-settled-wash text-settled-ink",
  danger: "bg-danger-wash text-danger-ink",
  info: "bg-info-wash text-info-ink",
  strong: "bg-settled text-white",
};

const TONE_DOT: Record<Tone, string> = {
  neutral: "bg-ink-faint",
  attention: "bg-attention",
  settled: "bg-settled",
  danger: "bg-danger",
  info: "bg-info",
  strong: "bg-white",
};

export function toneOf(value: string | null | undefined): Tone {
  return (value && STATUS_TONE[value]) || "neutral";
}

export function Badge({
  value,
  className = "",
  dot = true,
}: {
  value: QuotationStatus | MatchStatus | Confidence | string | null;
  className?: string;
  dot?: boolean;
}) {
  if (!value) return <span className="text-ink-faint">—</span>;
  const tone = toneOf(value);
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-medium capitalize ${TONE_STYLES[tone]} ${className}`}
    >
      {dot && <span className={`size-1.5 shrink-0 rounded-full ${TONE_DOT[tone]}`} />}
      {value.replace(/_/g, " ").toLowerCase()}
    </span>
  );
}

/* ---------------------------------------------------------------------------
   Surfaces
   --------------------------------------------------------------------------- */

export function Card({
  title,
  subtitle,
  action,
  children,
  padded = true,
  className = "",
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  padded?: boolean;
  className?: string;
}) {
  return (
    <section
      className={`overflow-hidden rounded-card border border-rule bg-surface shadow-card ${className}`}
    >
      {(title || action) && (
        <header className="flex items-center justify-between gap-3 border-b border-rule px-4 py-2.5">
          <div className="min-w-0">
            <h2 className="truncate text-sm font-semibold text-ink">{title}</h2>
            {subtitle && <p className="truncate text-xs text-ink-faint">{subtitle}</p>}
          </div>
          {action && <div className="flex shrink-0 items-center gap-2">{action}</div>}
        </header>
      )}
      <div className={padded ? "p-4" : ""}>{children}</div>
    </section>
  );
}

export function Kpi({
  label,
  value,
  hint,
  tone = "default",
  spark,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  tone?: "default" | "warn" | "good" | "bad" | "brand";
  spark?: number[];
}) {
  const tones = {
    default: "text-ink",
    warn: "text-attention",
    good: "text-settled",
    bad: "text-danger",
    brand: "text-brand",
  };
  return (
    <div className="rounded-card border border-rule bg-surface p-3.5 shadow-card">
      <p className="text-[11px] font-medium uppercase tracking-wider text-ink-faint">{label}</p>
      <div className="mt-1 flex items-end justify-between gap-2">
        <p className={`tabular text-2xl font-semibold leading-none ${tones[tone]}`}>{value}</p>
        {spark && spark.length > 1 && <Sparkline points={spark} />}
      </div>
      {hint && <p className="mt-1.5 text-xs text-ink-faint">{hint}</p>}
    </div>
  );
}

/** A small trend line. Endpoint emphasised, because that is the current value. */
export function Sparkline({ points, width = 56, height = 20 }: { points: number[]; width?: number; height?: number }) {
  const max = Math.max(...points, 1);
  const min = Math.min(...points, 0);
  const span = max - min || 1;
  const step = width / (points.length - 1);
  const coords = points.map((p, i) => [i * step, height - ((p - min) / span) * height] as const);
  const line = coords.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const [lastX, lastY] = coords[coords.length - 1];

  return (
    <svg width={width} height={height} className="overflow-visible" aria-hidden="true">
      <polyline
        points={line}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="text-brand/60"
      />
      <circle cx={lastX} cy={lastY} r="2" className="fill-brand" />
    </svg>
  );
}

/* ---------------------------------------------------------------------------
   Controls
   --------------------------------------------------------------------------- */

/**
 * One control height throughout.
 *
 * Buttons match `Input` and `Select` (`py-2 text-sm`), so a button beside a
 * field sits on the same baseline and a toolbar reads as one row rather than
 * as a set of differently-sized objects. `compact` exists only for controls
 * living *inside* a dense row - a table cell, a card header - where a
 * full-height button would set the row's height and loosen the whole table.
 */
export function Button({
  children,
  onClick,
  variant = "secondary",
  compact = false,
  disabled,
  type = "button",
  title,
  className = "",
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "danger" | "ghost";
  compact?: boolean;
  disabled?: boolean;
  type?: "button" | "submit";
  title?: string;
  className?: string;
}) {
  const variants = {
    primary: "bg-brand text-white hover:bg-brand-hover shadow-card",
    secondary: "bg-surface text-ink ring-1 ring-inset ring-rule hover:bg-sunk",
    danger: "bg-surface text-danger-ink ring-1 ring-inset ring-danger/40 hover:bg-danger-wash",
    ghost: "text-ink-soft hover:bg-sunk hover:text-ink",
  };
  // Both keep the same type size; only the padding tightens, so a compact
  // button never looks like a different component.
  const sizing = compact ? "px-2.5 py-1 text-sm gap-1.5" : "px-3.5 py-2 text-sm gap-1.5";
  // `whitespace-nowrap` and `shrink-0`: a button is sized by its label, so under
  // flex pressure it must make the row wrap rather than break its own text -
  // "Replace from Excel" stacked into three lines reads as three controls.
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`inline-flex shrink-0 items-center justify-center whitespace-nowrap rounded-lg font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${variants[variant]} ${sizing} ${className}`}
    >
      {children}
    </button>
  );
}

export function Input({
  value,
  onChange,
  placeholder,
  type = "text",
  className = "",
  disabled,
  step,
  min,
}: {
  value: string | number;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: string;
  className?: string;
  disabled?: boolean;
  step?: string;
  min?: string;
}) {
  return (
    <input
      type={type}
      value={value}
      step={step}
      min={min}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className={`w-full rounded-lg border border-rule bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:border-brand focus:outline-none disabled:opacity-60 ${className}`}
    />
  );
}

export function Select({
  value,
  onChange,
  options,
  className = "",
  disabled = false,
}: {
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  className?: string;
  /** A read-only viewer sees the setting and its value, but cannot change it -
   *  more useful than hiding the control and leaving them wondering. */
  disabled?: boolean;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      disabled={disabled}
      className={`rounded-lg border border-rule bg-surface px-3 py-2 text-sm text-ink focus:border-brand focus:outline-none disabled:cursor-not-allowed disabled:opacity-60 ${className}`}
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="inline-flex shrink-0 items-center gap-2 text-sm text-ink"
    >
      {/* `isolate` matters: the animated track paints into its own compositing
          layer, and without isolation that layer clipped the first glyph of
          the adjacent label - "Active" rendered as "\ctive". Confirmed by
          hiding the track, which made the label render correctly. */}
      <span
        className={`relative isolate h-4.5 w-8 shrink-0 rounded-full transition-colors ${checked ? "bg-brand" : "bg-rule-firm"}`}
      >
        <span
          className={`absolute top-0.5 size-3.5 rounded-full bg-white transition-transform ${checked ? "translate-x-4" : "translate-x-0.5"}`}
        />
      </span>
      {label && (
        <span className="relative shrink-0 whitespace-nowrap">{label}</span>
      )}
    </button>
  );
}

/* ---------------------------------------------------------------------------
   States
   --------------------------------------------------------------------------- */

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 p-6 text-sm text-ink-faint">
      <span className="size-3 animate-spin rounded-full border-2 border-rule border-t-brand" />
      {label}…
    </div>
  );
}

export function Skeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="flex flex-col gap-2 p-4">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-8 animate-pulse rounded bg-sunk" />
      ))}
    </div>
  );
}

export function ErrorNote({ message }: { message: string }) {
  return (
    <div className="rounded border border-danger/30 bg-danger-wash px-3 py-2 text-sm text-danger-ink">
      {message}
    </div>
  );
}

export function Empty({ message, action }: { message: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-3 p-10 text-center">
      <p className="text-sm text-ink-faint">{message}</p>
      {action}
    </div>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex justify-between gap-4 py-1 text-sm">
      <dt className="text-ink-faint">{label}</dt>
      <dd className="tabular text-right font-medium text-ink">{children}</dd>
    </div>
  );
}

export function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <h3 className="text-[11px] font-semibold uppercase tracking-wider text-ink-faint">{children}</h3>
  );
}

/** A wide element that must scroll on its own rather than the page. */
export function Scroller({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`overflow-x-auto ${className}`}>{children}</div>;
}

export function Banner({
  tone = "info",
  children,
  action,
}: {
  tone?: "info" | "attention" | "danger" | "settled";
  children: ReactNode;
  action?: ReactNode;
}) {
  const tones = {
    info: "border-info/30 bg-info-wash text-info-ink",
    attention: "border-attention/30 bg-attention-wash text-attention-ink",
    danger: "border-danger/30 bg-danger-wash text-danger-ink",
    settled: "border-settled/30 bg-settled-wash text-settled-ink",
  };
  return (
    <div
      className={`flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2 text-sm ${tones[tone]}`}
    >
      <div className="min-w-0 flex-1">{children}</div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

/* ---------------------------------------------------------------------------
   Summary and navigation primitives
   --------------------------------------------------------------------------- */

/**
 * A headline count in its own card. The figure carries the colour, not the
 * card, so a row of these reads as one band of numbers rather than a row of
 * competing blocks.
 */
export function StatCard({
  label,
  value,
  tone = "default",
  hint,
  onClick,
  active = false,
}: {
  label: string;
  value: ReactNode;
  tone?: "default" | "brand" | "attention" | "settled" | "danger" | "info";
  hint?: string;
  onClick?: () => void;
  active?: boolean;
}) {
  const tones = {
    default: "text-ink",
    brand: "text-brand",
    attention: "text-attention",
    settled: "text-settled",
    danger: "text-danger",
    info: "text-info",
  };

  const Tag = onClick ? "button" : "div";

  return (
    <Tag
      {...(onClick ? { type: "button" as const, onClick } : {})}
      className={`rounded-card border bg-surface px-4 py-3 text-left shadow-card transition-colors ${
        active ? "border-brand" : "border-rule"
      } ${onClick ? "hover:border-rule-firm" : ""}`}
    >
      <p className="text-xs font-medium text-ink-soft">{label}</p>
      <p className={`tabular mt-1 text-2xl font-bold leading-none ${tones[tone]}`}>{value}</p>
      {hint && <p className="mt-1 text-[11px] text-ink-faint">{hint}</p>}
    </Tag>
  );
}

/** Underlined tab strip, as used inside a detail panel. */
export function Tabs<T extends string>({
  tabs,
  value,
  onChange,
}: {
  tabs: { key: T; label: string; count?: number }[];
  value: T;
  onChange: (key: T) => void;
}) {
  return (
    <nav className="flex gap-1 overflow-x-auto border-b border-rule">
      {tabs.map((t) => (
        <button
          key={t.key}
          type="button"
          onClick={() => onChange(t.key)}
          className={`-mb-px flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2.5 text-sm font-medium transition-colors ${
            value === t.key
              ? "border-brand-soft text-brand-soft-ink"
              : "border-transparent text-ink-soft hover:text-ink"
          }`}
        >
          {t.label}
          {t.count !== undefined && (
            <span
              className={`tabular rounded-full px-1.5 text-[11px] ${
                value === t.key ? "bg-brand-wash text-brand-soft-ink" : "bg-sunk text-ink-faint"
              }`}
            >
              {t.count}
            </span>
          )}
        </button>
      ))}
    </nav>
  );
}

/** Numbered pager. Shown only when there is more than one page to reach. */
export function Pagination({
  page,
  pageCount,
  onChange,
  summary,
}: {
  page: number;
  pageCount: number;
  onChange: (page: number) => void;
  summary?: string;
}) {
  if (pageCount <= 1) {
    return summary ? (
      <div className="flex items-center justify-between px-4 py-2.5 text-xs text-ink-faint">
        <span>{summary}</span>
      </div>
    ) : null;
  }

  // A window around the current page, so a long list does not print 40 buttons.
  const pages: number[] = [];
  const from = Math.max(1, Math.min(page - 1, pageCount - 3));
  for (let i = from; i < from + 4 && i <= pageCount; i++) pages.push(i);

  const arrow = (dir: -1 | 1, label: string) => (
    <button
      type="button"
      aria-label={label}
      disabled={dir === -1 ? page === 1 : page === pageCount}
      onClick={() => onChange(page + dir)}
      className="grid size-7 place-items-center rounded-lg text-ink-faint transition-colors hover:bg-sunk hover:text-ink disabled:opacity-40 disabled:hover:bg-transparent"
    >
      <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="2">
        <path
          d={dir === -1 ? "M15 6l-6 6 6 6" : "M9 6l6 6-6 6"}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </button>
  );

  return (
    <div className="flex items-center justify-between gap-3 px-4 py-2.5">
      <span className="text-xs text-ink-faint">{summary}</span>
      <div className="flex items-center gap-1">
        {arrow(-1, "Previous page")}
        {pages.map((n) => (
          <button
            key={n}
            type="button"
            onClick={() => onChange(n)}
            className={`tabular grid size-7 place-items-center rounded-lg text-xs font-medium transition-colors ${
              n === page
                ? "border border-brand bg-brand-wash text-brand-ink"
                : "text-ink-soft hover:bg-sunk hover:text-ink"
            }`}
          >
            {n}
          </button>
        ))}
        {arrow(1, "Next page")}
      </div>
    </div>
  );
}

/** The funnel/filter glyph the toolbar uses. */
export function FilterButton({
  active = false,
  onClick,
  title = "Filters",
}: {
  active?: boolean;
  onClick?: () => void;
  title?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className={`grid size-9 place-items-center rounded-lg border transition-colors ${
        active
          ? "border-brand bg-brand-wash text-brand"
          : "border-rule bg-surface text-ink-soft hover:bg-sunk"
      }`}
    >
      <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="M3 5h18l-7 8v6l-4 2v-8z" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </button>
  );
}

/** Search box with a leading magnifier, as in the toolbar. */
export function SearchInput({
  value,
  onChange,
  placeholder = "Search…",
  className = "",
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  className?: string;
}) {
  return (
    <div className={`relative ${className}`}>
      <svg
        viewBox="0 0 24 24"
        className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-faint"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
      >
        <circle cx="11" cy="11" r="7" />
        <path d="M20 20l-3.5-3.5" strokeLinecap="round" />
      </svg>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-lg border border-rule bg-surface py-2 pl-9 pr-3 text-sm text-ink placeholder:text-ink-faint focus:border-brand focus:outline-none"
      />
    </div>
  );
}
