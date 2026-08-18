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

const STATUS_STYLES: Record<string, string> = {
  READY_FOR_REVIEW: "bg-amber-100 text-amber-800 ring-amber-200",
  NEEDS_INFORMATION: "bg-orange-100 text-orange-800 ring-orange-200",
  EDITED: "bg-sky-100 text-sky-800 ring-sky-200",
  APPROVED: "bg-emerald-100 text-emerald-800 ring-emerald-200",
  SENT: "bg-emerald-600 text-white ring-emerald-700",
  REJECTED: "bg-ink-200 text-ink-700 ring-ink-300",
  FAILED: "bg-rose-100 text-rose-800 ring-rose-200",
  PROCESSING: "bg-ink-100 text-ink-700 ring-ink-200",
  NEW: "bg-ink-100 text-ink-700 ring-ink-200",
  MATCH_FOUND: "bg-emerald-100 text-emerald-800 ring-emerald-200",
  MULTIPLE_MATCHES: "bg-amber-100 text-amber-800 ring-amber-200",
  NO_MATCH: "bg-rose-100 text-rose-800 ring-rose-200",
  PENDING: "bg-ink-100 text-ink-700 ring-ink-200",
  HIGH: "bg-emerald-100 text-emerald-800 ring-emerald-200",
  MEDIUM: "bg-amber-100 text-amber-800 ring-amber-200",
  LOW: "bg-rose-100 text-rose-800 ring-rose-200",
  CUSTOMER_ACCEPTED: "bg-emerald-600 text-white ring-emerald-700",
  CUSTOMER_DECLINED: "bg-ink-200 text-ink-700 ring-ink-300",
  ACCEPTED: "bg-emerald-100 text-emerald-800 ring-emerald-200",
  DECLINED: "bg-ink-200 text-ink-700 ring-ink-300",
  NEEDS_REVIEW: "bg-amber-100 text-amber-800 ring-amber-200",
};

export function Badge({
  value,
  className = "",
}: {
  value: QuotationStatus | MatchStatus | Confidence | string | null;
  className?: string;
}) {
  if (!value) return <span className="text-ink-500">—</span>;
  const style = STATUS_STYLES[value] ?? "bg-ink-100 text-ink-700 ring-ink-200";
  return (
    <span
      className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${style} ${className}`}
    >
      {value.replace(/_/g, " ")}
    </span>
  );
}

export function Card({
  title,
  action,
  children,
  className = "",
}: {
  title?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-xl border border-ink-200 bg-white shadow-sm ${className}`}
    >
      {(title || action) && (
        <header className="flex items-center justify-between gap-3 border-b border-ink-200 px-4 py-3">
          <h2 className="text-sm font-semibold text-ink-900">{title}</h2>
          {action}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function Kpi({
  label,
  value,
  hint,
  tone = "default",
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  tone?: "default" | "warn" | "good" | "bad";
}) {
  const tones = {
    default: "text-ink-900",
    warn: "text-amber-600",
    good: "text-emerald-600",
    bad: "text-rose-600",
  };
  return (
    <div className="rounded-xl border border-ink-200 bg-white p-4 shadow-sm">
      <p className="text-xs font-medium uppercase tracking-wide text-ink-500">{label}</p>
      <p className={`tabular mt-1 text-2xl font-semibold ${tones[tone]}`}>{value}</p>
      {hint && <p className="mt-1 text-xs text-ink-500">{hint}</p>}
    </div>
  );
}

export function Button({
  children,
  onClick,
  variant = "secondary",
  disabled,
  type = "button",
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "danger" | "ghost";
  disabled?: boolean;
  type?: "button" | "submit";
}) {
  const variants = {
    primary: "bg-emerald-600 text-white hover:bg-emerald-700 disabled:bg-emerald-300",
    secondary: "bg-white text-ink-900 ring-1 ring-inset ring-ink-300 hover:bg-ink-50",
    danger: "bg-white text-rose-700 ring-1 ring-inset ring-rose-300 hover:bg-rose-50",
    ghost: "text-ink-700 hover:bg-ink-100",
  };
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-60 ${variants[variant]}`}
    >
      {children}
    </button>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 p-6 text-sm text-ink-500">
      <span className="size-2 animate-pulse rounded-full bg-ink-300" />
      {label}…
    </div>
  );
}

export function ErrorNote({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">
      {message}
    </div>
  );
}

export function Empty({ message }: { message: string }) {
  return <p className="p-6 text-center text-sm text-ink-500">{message}</p>;
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex justify-between gap-4 py-1 text-sm">
      <dt className="text-ink-500">{label}</dt>
      <dd className="tabular text-right font-medium text-ink-900">{children}</dd>
    </div>
  );
}
