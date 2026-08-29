/* Adding one lot by hand.
 *
 * The Excel import remains the bulk route. This exists for the ordinary case
 * that had no route at all: a single delivery arrives and the trader has to
 * record it, which previously meant editing a spreadsheet and re-importing
 * the whole sheet.
 *
 * Quantity is asked for in MT because that is the unit steel is bought and
 * sold in; the store keeps kilograms, and the conversion happens on the
 * server so the two cannot disagree.
 */

import { useState } from "react";

import { api, ApiError } from "../api/client";
import { Button, Input } from "./ui";

interface Draft {
  product_type: string;
  grade: string;
  thickness_mm: string;
  width_mm: string;
  length_mm: string;
  quantity_mt: string;
  location: string;
  make: string;
  nop: string;
  purchase_rate_per_kg: string;
  landed_cost_per_kg: string;
}

const EMPTY: Draft = {
  product_type: "Plate",
  grade: "",
  thickness_mm: "",
  width_mm: "",
  length_mm: "",
  quantity_mt: "",
  location: "",
  make: "",
  nop: "",
  purchase_rate_per_kg: "",
  landed_cost_per_kg: "",
};

/** Blank optional fields are omitted rather than sent as empty strings, which
 *  the numeric validators would reject. */
function payload(draft: Draft) {
  const out: Record<string, unknown> = {
    product_type: draft.product_type.trim(),
    grade: draft.grade.trim(),
    quantity_mt: draft.quantity_mt,
  };
  const numeric: (keyof Draft)[] = [
    "thickness_mm", "width_mm", "length_mm", "nop",
    "purchase_rate_per_kg", "landed_cost_per_kg",
  ];
  for (const key of numeric) {
    const value = draft[key].trim();
    if (value) out[key] = Number(value);
  }
  for (const key of ["location", "make"] as const) {
    const value = draft[key].trim();
    if (value) out[key] = value;
  }
  return out;
}

export default function AddStock({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: () => void;
}) {
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /* Grade and quantity are the minimum that makes a lot meaningful: without
     them there is nothing to match against and nothing to sell. */
  const ready = draft.grade.trim() !== "" && Number(draft.quantity_mt) > 0;

  const set = (key: keyof Draft) => (value: string) =>
    setDraft((d) => ({ ...d, [key]: value }));

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await api.post("/stock", payload(draft));
      onSaved();
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : (e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const field = (
    key: keyof Draft,
    label: string,
    placeholder = "",
    hint?: string,
  ) => (
    <label className="flex flex-col gap-1">
      <span className="text-[11px] font-medium text-ink-faint">{label}</span>
      <Input value={draft[key]} onChange={set(key)} placeholder={placeholder} />
      {hint && <span className="text-[11px] text-ink-faint">{hint}</span>}
    </label>
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="max-h-[90vh] w-full max-w-2xl overflow-auto rounded-card border border-rule bg-surface shadow-card"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-rule px-5 py-3">
          <div>
            <h2 className="text-sm font-semibold text-ink">Add stock</h2>
            <p className="text-xs text-ink-faint">
              One lot. Use the Excel import for a whole sheet.
            </p>
          </div>
          <Button variant="ghost" compact onClick={onClose}>
            Close
          </Button>
        </header>

        <div className="flex flex-col gap-4 p-5">
          {error && (
            <p className="rounded-lg border border-danger-line bg-danger-wash px-3 py-2 text-sm text-danger-ink">
              {error}
            </p>
          )}

          <div className="grid gap-3 sm:grid-cols-3">
            {field("product_type", "Type", "Plate")}
            {field("grade", "Grade", "E250")}
            {field("quantity_mt", "Quantity (MT)", "20")}
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            {field("thickness_mm", "Thickness (mm)", "10")}
            {field("width_mm", "Width (mm)", "1500")}
            {field("length_mm", "Length (mm)", "6000")}
          </div>

          <div className="grid gap-3 sm:grid-cols-3">
            {field("location", "Location", "Nagpur")}
            {field("make", "Mill / make", "SAIL")}
            {field("nop", "Pieces", "40")}
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            {field("purchase_rate_per_kg", "Purchase rate / kg", "54.00")}
            {field(
              "landed_cost_per_kg",
              "Landed cost / kg",
              "56.50",
              "What it cost to have on the floor. Used for pricing.",
            )}
          </div>
        </div>

        <footer className="flex justify-end gap-2 border-t border-rule bg-sunk px-5 py-3">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" onClick={save} disabled={busy || !ready}>
            {busy ? "Adding…" : "Add stock"}
          </Button>
        </footer>
      </div>
    </div>
  );
}
