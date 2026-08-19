import { useState } from "react";

import { api } from "../api/client";
import type { StockHold, StockItem } from "../api/types";
import { Badge, Banner, Button, Empty, Input, num, Select, when } from "./ui";

/* ---------------------------------------------------------------------------
   Changing stock by hand.

   The spreadsheet import replaces the whole table, so nothing here writes to
   the imported balance. Every change is a *movement* recorded alongside, and
   replayed on top - which is what lets a receipt entered in March survive
   April's sheet.

   Two of the five kinds hold material without moving it:
   `RESERVATION` ties tonnage to a quotation, `BLOCK` withholds it generally -
   quarantine, an expected order, material promised on the phone. Both come out
   of what may be quoted; neither changes what is on the floor.
   --------------------------------------------------------------------------- */

const KINDS = [
  { value: "RECEIPT", label: "Goods in — received" },
  { value: "ISSUE", label: "Goods out — despatched" },
  { value: "BLOCK", label: "Block — hold back from quoting" },
  { value: "ADJUSTMENT", label: "Adjustment — stocktake correction" },
];

const KIND_HELP: Record<string, string> = {
  RECEIPT: "Adds to what is on hand and to what can be quoted.",
  ISSUE: "Removes it entirely — the material has left the yard.",
  BLOCK: "Stays on the floor but stops being offered. Can be lifted later.",
  ADJUSTMENT: "Corrects the figure either way. Use a minus sign to reduce.",
};

export function StockAdjustDialog({
  lot,
  onClose,
  onSaved,
}: {
  lot: StockItem;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [kind, setKind] = useState("RECEIPT");
  const [quantity, setQuantity] = useState("");
  const [unit, setUnit] = useState<"MT" | "KG">("MT");
  const [reference, setReference] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const kg = quantity ? Number(quantity) * (unit === "MT" ? 1000 : 1) : 0;
  const valid = Number.isFinite(kg) && Math.abs(kg) > 0;

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await api.post("/stock/movements", {
        kind,
        // The service normalises direction, so an ISSUE always reduces
        // whatever sign is sent. Only an adjustment keeps the caller's.
        quantity_kg: Math.abs(kg),
        stock_item_id: lot.id,
        location: lot.location,
        reference: reference || null,
        note: note || null,
      });
      onSaved();
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-40 flex items-end justify-center bg-ink/40 p-0 sm:items-center sm:p-4"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="max-h-[90vh] w-full overflow-y-auto rounded-t-card border border-rule bg-surface shadow-raised sm:max-w-lg sm:rounded-card"
      >
        <header className="flex items-start justify-between gap-3 border-b border-rule px-4 py-3">
          <div className="min-w-0">
            <h2 className="text-base font-semibold text-ink">Update stock</h2>
            <p className="truncate text-xs text-ink-faint">{lot.display_name}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg p-1 text-ink-faint hover:bg-sunk hover:text-ink"
          >
            <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="1.8">
              <path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" />
            </svg>
          </button>
        </header>

        <div className="flex flex-col gap-3 px-4 py-4">
          {error && <Banner tone="danger">{error}</Banner>}

          <label className="flex flex-col gap-1">
            <span className="text-xs font-medium text-ink-soft">What happened</span>
            <Select value={kind} onChange={setKind} options={KINDS} className="w-full" />
            <span className="text-[11px] text-ink-faint">{KIND_HELP[kind]}</span>
          </label>

          <div className="flex items-end gap-2">
            <label className="flex flex-1 flex-col gap-1">
              <span className="text-xs font-medium text-ink-soft">Quantity</span>
              <Input value={quantity} onChange={setQuantity} type="number" step="0.001" placeholder="0" />
            </label>
            <div className="flex overflow-hidden rounded-lg border border-rule">
              {(["MT", "KG"] as const).map((u) => (
                <button
                  key={u}
                  type="button"
                  onClick={() => setUnit(u)}
                  className={`px-3 py-2 text-sm font-medium transition-colors ${
                    unit === u ? "bg-brand text-white" : "bg-surface text-ink-soft hover:bg-sunk"
                  }`}
                >
                  {u}
                </button>
              ))}
            </div>
          </div>

          <label className="flex flex-col gap-1">
            <span className="text-xs font-medium text-ink-soft">Reference</span>
            <Input
              value={reference}
              onChange={setReference}
              placeholder={kind === "ISSUE" ? "Despatch or invoice no." : "GRN, PO or order no."}
            />
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-xs font-medium text-ink-soft">Note</span>
            <Input value={note} onChange={setNote} placeholder="Why, in a few words" />
          </label>

          {valid && (
            <div className="rounded-lg border border-rule bg-sunk px-3 py-2 text-xs text-ink-soft">
              {kind === "RECEIPT" && `Adds ${num(kg / 1000)} MT to free stock.`}
              {kind === "ISSUE" && `Removes ${num(kg / 1000)} MT from the yard.`}
              {kind === "BLOCK" &&
                `Holds ${num(kg / 1000)} MT back from quoting. It stays on hand and can be released.`}
              {kind === "ADJUSTMENT" && `Corrects the balance by ${num(kg / 1000)} MT.`}
            </div>
          )}
        </div>

        <footer className="flex justify-end gap-2 border-t border-rule bg-sunk px-4 py-3">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={!valid || busy} onClick={save}>
            {busy ? "Recording…" : "Record"}
          </Button>
        </footer>
      </div>
    </div>
  );
}

/** Everything currently withheld from quoting, and the means to release it. */
export function HoldsPanel({
  holds,
  onChanged,
}: {
  holds: StockHold[];
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState<number | null>(null);

  if (holds.length === 0) {
    return <Empty message="Nothing is held back. All stock on hand is free to quote." />;
  }

  return (
    <ul className="divide-y divide-rule">
      {holds.map((h) => (
        <li key={h.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Badge value={h.kind} dot={false} />
              <span className="truncate text-sm text-ink">
                {[h.grade, h.product_type, h.thickness_mm && `${h.thickness_mm}mm`]
                  .filter(Boolean)
                  .join(" ") || "Unspecified"}
              </span>
              <span className="tabular text-sm font-semibold text-ink">
                {num(Number(h.quantity_kg) / 1000)} MT
              </span>
            </div>
            <p className="mt-0.5 truncate text-xs text-ink-faint">
              {[h.reference, h.note, h.location].filter(Boolean).join(" · ") || "no reference"}
              {" · "}
              {when(h.created_at)}
            </p>
          </div>

          <Button
            disabled={busy === h.id}
            onClick={async () => {
              setBusy(h.id);
              try {
                await api.post(`/stock/holds/${h.id}/lift`);
                onChanged();
              } finally {
                setBusy(null);
              }
            }}
          >
            {busy === h.id ? "Releasing…" : "Release"}
          </Button>
        </li>
      ))}
    </ul>
  );
}
