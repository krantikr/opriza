import type { LineItem, QuotationStage } from "../api/types";
import { num } from "../components/ui";

/* ---------------------------------------------------------------------------
   How a material line is written in a table cell.

   Shared by the Quotations list and the Follow-ups board: the two screens
   show the same columns for the same steel, and a trader crossing between
   them should never have to work out whether "8 x 1250 x 5800 mm" on one
   screen means the same as something worded differently on the other.
   --------------------------------------------------------------------------- */

export function sizeText(item: LineItem): string {
  if (item.diameter_mm) {
    const base = `OD ${item.diameter_mm}mm`;
    return item.thickness_mm ? `${base} x ${item.thickness_mm}mm` : base;
  }
  const dims = [item.thickness_mm, item.width_mm, item.length_mm].filter(
    (d): d is number => d != null,
  );
  return dims.length ? `${dims.join(" x ")} mm` : "—";
}

export function pcsText(item: LineItem): string {
  if (item.quantity_unit !== "PCS" || !item.quantity) return "—";
  return num(item.quantity, 0);
}

/** How far back a list looks. Shared so the two tables offer the same
 *  windows - "Last 30 days" has to mean the same thing on both. */
export const PERIODS = [
  { value: "7", label: "Last 7 days" },
  { value: "30", label: "Last 30 days" },
  { value: "90", label: "Last quarter" },
  { value: "180", label: "Last 6 months" },
  { value: "365", label: "Last year" },
  { value: "all", label: "All time" },
];

/** The six working stages, mirrored from `stages.py::COMMERCIAL_STAGES`.
 *
 *  Duplicated from the server rather than fetched: a round trip to render a
 *  picker would leave it blank for a moment on every load, and the server
 *  remains the authority - it rejects a stage it does not know.
 *
 *  One definition across the app, because a stage picker offering different
 *  options on different screens reads as two different things being tracked. */
export const STAGES: { key: QuotationStage; label: string }[] = [
  { key: "received", label: "Received" },
  { key: "sent", label: "Sent" },
  { key: "negotiation", label: "Negotiation" },
  { key: "delivery_pending", label: "Delivery pending" },
  { key: "payment_pending", label: "Payment pending" },
  { key: "completed", label: "Completed" },
];

export const STAGE_COLOR: Record<QuotationStage, string> = {
  received: "text-attention-ink",
  sent: "text-brand-ink",
  negotiation: "text-info-ink",
  delivery_pending: "text-attention-ink",
  payment_pending: "text-attention-ink",
  completed: "text-settled-ink",
};

/** Stable hue per customer, matching the chase board and the Inbox: the same
 *  buyer is always the same colour on every screen. */
export function hueFor(name: string): number {
  const hues = [212, 340, 152, 28, 265, 190];
  let total = 0;
  for (const ch of name) total += ch.charCodeAt(0);
  return hues[total % hues.length];
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0] ?? "")
    .join("")
    .toUpperCase();
}
