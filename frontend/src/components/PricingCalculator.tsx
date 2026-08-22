import { useState } from "react";

import { api } from "../api/client";
import type { PricingComponent, QuotationPricing } from "../api/types";
import { Badge, Banner, Button, inr, num } from "./ui";

/* ---------------------------------------------------------------------------
   The cost build-up.

   A three-column table - what, how much, and the working - because that is how
   a trader reads a quote. The notes column is not decoration: it is the reason
   the figure is what it is, and it is what makes the price arguable with a
   customer rather than merely assertable.

   Only the rows a rule computes are editable. A subtotal has no independent
   value to override; it is the sum of the rows above it.
   --------------------------------------------------------------------------- */

const MARGIN_KINDS = new Set(["TARGET_MARGIN", "MARGIN_FLOOR", "ROUNDING"]);

function PencilIcon() {
  return (
    <svg viewBox="0 0 24 24" className="size-3.5" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path d="M4 20h4L18.5 9.5a2.1 2.1 0 0 0-3-3L5 17v3z" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function RevertIcon() {
  return (
    <svg viewBox="0 0 24 24" className="size-3.5" fill="none" stroke="currentColor" strokeWidth="1.6">
      <path d="M3 10a8 8 0 1 1 2 6" strokeLinecap="round" />
      <path d="M3 5v5h5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function Row({
  component,
  index,
  readOnly,
  busy,
  onSave,
  onClear,
}: {
  component: PricingComponent;
  index: number;
  readOnly: boolean;
  busy: boolean;
  onSave: (amount: string) => void;
  onClear: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(component.amount);

  return (
    <tr className={`border-b border-rule ${component.applied ? "" : "opacity-60"}`}>
      <td className="px-4 py-2.5 align-top text-ink">
        <span className="tabular mr-1.5 text-ink-faint">{index}.</span>
        {component.label}
      </td>

      <td className="px-4 py-2.5 text-right align-top">
        {editing ? (
          <div className="flex items-center justify-end gap-1">
            <input
              autoFocus
              type="number"
              step="0.01"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  onSave(draft);
                  setEditing(false);
                }
                if (e.key === "Escape") setEditing(false);
              }}
              className="tabular w-28 rounded-lg border border-brand bg-surface px-2 py-1 text-right text-sm text-ink outline-none"
            />
            <Button
              compact
              variant="primary"
              disabled={busy}
              onClick={() => {
                onSave(draft);
                setEditing(false);
              }}
            >
              Save
            </Button>
          </div>
        ) : (
          <span
            className={`tabular font-semibold ${
              component.overridden ? "text-brand" : "text-ink"
            }`}
          >
            {inr(component.amount, false)}
          </span>
        )}
      </td>

      <td className="px-4 py-2.5 align-top">
        <div className="flex items-start justify-between gap-2">
          <span className="text-xs leading-relaxed text-ink-soft">{component.note}</span>

          {!readOnly && !editing && (
            <span className="flex shrink-0 items-center gap-0.5">
              {component.overridden && (
                <button
                  type="button"
                  title="Put this back to what the rules say"
                  onClick={onClear}
                  className="rounded p-1 text-ink-faint transition-colors hover:bg-danger-wash hover:text-danger"
                >
                  <RevertIcon />
                </button>
              )}
              <button
                type="button"
                title="Override this figure for this quotation"
                onClick={() => {
                  setDraft(component.amount);
                  setEditing(true);
                }}
                className="rounded p-1 text-ink-faint transition-colors hover:bg-brand-wash hover:text-brand"
              >
                <PencilIcon />
              </button>
            </span>
          )}
        </div>
      </td>
    </tr>
  );
}

export default function PricingCalculator({
  pricing,
  quotationId,
  lineId,
  onChange,
  readOnly = false,
}: {
  pricing: QuotationPricing;
  quotationId: number;
  lineId: number;
  onChange: () => void;
  readOnly?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const costs = pricing.components.filter((c) => !MARGIN_KINDS.has(c.kind));
  const margins = pricing.components.filter((c) => MARGIN_KINDS.has(c.kind));

  async function override(code: string, amount: string) {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/quotations/${quotationId}/lines/${lineId}/pricing/override`, {
        component_code: code,
        amount,
      });
      onChange();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  /** Re-run the live rules over this quotation. The endpoint keeps overrides
   *  by default, so a figure a human deliberately set is not discarded. */
  async function recalculate() {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/quotations/${quotationId}/pricing/recalculate`);
      onChange();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function clearOverride(code: string) {
    setBusy(true);
    setError(null);
    try {
      await api.del(`/quotations/${quotationId}/lines/${lineId}/pricing/override/${code}`);
      onChange();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      {error && <Banner tone="danger">{error}</Banner>}

      {/* Stored warnings describe the state at the moment this line was
          priced. Once the live rule set has moved on - somebody published
          rules that did not exist then - repeating them tells a desk with
          working pricing that it has none. Offer the recompute instead. */}
      {pricing.rules_stale ? (
        <Banner
          tone="attention"
          action={
            <Button variant="primary" disabled={busy} onClick={recalculate}>
              {busy ? "Recalculating…" : "Recalculate"}
            </Button>
          }
        >
          This was priced before the current rules were published, so the
          figures below are out of date.
        </Banner>
      ) : (
        pricing.warnings.map((w) => (
          <Banner key={w} tone="attention">
            {w}
          </Banner>
        ))
      )}

      <div className="overflow-hidden rounded-card border border-rule bg-surface shadow-card">
        <header className="flex items-center justify-between gap-3 border-b border-rule px-4 py-3">
          <h3 className="text-base font-semibold text-ink">Pricing calculator</h3>
          <div className="flex items-center gap-2">
            <Badge value={pricing.basis} dot={false} />
            <span className="text-[11px] text-ink-faint">
              rules v{pricing.rules_version ?? "—"}
              {pricing.has_overrides && " · edited"}
            </span>
          </div>
        </header>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[36rem] text-sm">
            <thead>
              <tr className="border-b border-rule bg-sunk text-xs font-medium text-ink-soft">
                <th className="w-[38%] px-4 py-2 text-left">Description</th>
                <th className="w-[20%] px-4 py-2 text-right">Price ({pricing.currency}/MT)</th>
                <th className="px-4 py-2 text-left">Notes</th>
              </tr>
            </thead>

            <tbody>
              {costs.map((c, i) => (
                <Row
                  key={c.code}
                  component={c}
                  index={i + 1}
                  readOnly={readOnly}
                  busy={busy}
                  onSave={(amount) => override(c.code, amount)}
                  onClear={() => clearOverride(c.code)}
                />
              ))}

              {/* Total cost: the sum, so it carries no pencil of its own. */}
              <tr className="border-b border-rule bg-sunk">
                <td className="px-4 py-2.5 font-semibold text-ink">Total cost</td>
                <td className="tabular px-4 py-2.5 text-right font-bold text-ink">
                  {inr(pricing.total_cost, false)}
                </td>
                <td className="px-4 py-2.5" />
              </tr>

              {margins.map((c, i) => (
                <Row
                  key={c.code}
                  component={c}
                  index={costs.length + i + 1}
                  readOnly={readOnly}
                  busy={busy}
                  onSave={(amount) => override(c.code, amount)}
                  onClear={() => clearOverride(c.code)}
                />
              ))}
            </tbody>

            <tfoot>
              <tr className="bg-brand-wash">
                <td className="px-4 py-3 font-semibold text-brand">Recommended quote price</td>
                <td className="tabular px-4 py-3 text-right text-base font-bold text-brand">
                  {inr(pricing.quote_rate, false)} / MT
                </td>
                <td className="px-4 py-3 text-xs text-ink-soft">
                  {pricing.line_total && pricing.quantity_mt
                    ? `${num(pricing.quantity_mt)} MT · ${inr(pricing.line_total)} total`
                    : "Indicative — subject to confirmation"}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>
    </div>
  );
}
