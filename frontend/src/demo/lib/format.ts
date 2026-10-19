/** Money and time the way an Indian distributor reads them. */

/** Full rupees with Indian grouping: ₹80,28,720. */
export function inr(n: number): string {
  return "₹" + Math.round(n).toLocaleString("en-IN");
}

/** Short rupees: ₹4.2 Cr, ₹42.0 L, ₹8,400. */
export function money(n: number): string {
  const sign = n < 0 ? "−" : "";
  const a = Math.abs(n);
  if (a >= 1e7) return `${sign}₹${(a / 1e7).toFixed(a >= 1e9 ? 0 : a >= 1e8 ? 1 : 2)} Cr`;
  if (a >= 1e5) return `${sign}₹${(a / 1e5).toFixed(a >= 1e7 ? 0 : 1)} L`;
  return sign + inr(a);
}

/** A rate: ₹54,900 per MT, or ₹2,350 per coil. */
export function rate(n: number, unit: string): string {
  return `${inr(n)}/${unit}`;
}

/** A quantity with its unit, trimming needless decimals. */
export function qty(n: number, unit: string): string {
  const v = Number.isInteger(n) ? n.toLocaleString("en-IN") : n.toFixed(1);
  return `${v} ${unit}`;
}

export function pct(n: number, digits = 1): string {
  return `${n.toFixed(digits)}%`;
}

/** Minutes since midnight → "10:42". */
export function clock(min: number): string {
  const h = Math.floor(min / 60) % 24;
  const m = Math.floor(min % 60);
  return `${h}:${m.toString().padStart(2, "0")}`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

export function shortDate(d: Date): string {
  return `${d.getDate()} ${MONTHS[d.getMonth()]}`;
}

export function dayDate(d: Date): string {
  return `${DAYS[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]}`;
}

export function addDays(base: Date, days: number): Date {
  const d = new Date(base);
  d.setDate(d.getDate() + days);
  return d;
}

export function monthName(offset: number, base = new Date()): string {
  const d = new Date(base.getFullYear(), base.getMonth() + offset, 1);
  return MONTHS[d.getMonth()] as string;
}
