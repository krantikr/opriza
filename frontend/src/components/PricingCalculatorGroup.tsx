import { useEffect, useState } from "react";

import { api, query, useApi } from "../api/client";
import type { LineItem, PricingComponent, QuotationPricing } from "../api/types";
import { Banner, Button, inr, Loading, num } from "./ui";

/* ---------------------------------------------------------------------------
   One line item's pricing, as a single table - one row per cost component,
   one column per despatch location a trader has added to compare. Almost
   every line has exactly one column: the calculator's ordinary shape,
   unchanged. A location is added on demand (max 3) and selected by clicking
   its column header - that is the price this line will actually send.
   --------------------------------------------------------------------------- */

const MARGIN_KINDS = new Set(["TARGET_MARGIN", "MARGIN_FLOOR", "ROUNDING"]);
const MAX_OPTIONS = 3;

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

function InfoIcon() {
  return (
    <svg viewBox="0 0 24 24" className="size-3.5" fill="none" stroke="currentColor" strokeWidth="1.6">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5.5" strokeLinecap="round" />
      <circle cx="12" cy="8" r="0.75" fill="currentColor" stroke="none" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg viewBox="0 0 24 24" className="size-3.5" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 5v14M5 12h14" strokeLinecap="round" />
    </svg>
  );
}

/** The location a trader adds to compare - a known warehouse, or "Other"
 *  typed in by hand with no matched stock behind it. */
function AddLocationPicker({
  knownLocations,
  excluding,
  onAdd,
  onCancel,
}: {
  knownLocations: string[];
  excluding: (string | null)[];
  onAdd: (location: string, manual: boolean) => void;
  onCancel: () => void;
}) {
  const [other, setOther] = useState(false);
  const [text, setText] = useState("");
  const available = knownLocations.filter((loc) => !excluding.includes(loc));

  if (other) {
    return (
      <form
        className="flex items-center gap-1.5"
        onSubmit={(e) => {
          e.preventDefault();
          if (text.trim()) onAdd(text.trim(), true);
        }}
      >
        <input
          autoFocus
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Escape" && onCancel()}
          placeholder="Location name…"
          className="w-36 rounded-lg border border-brand bg-surface px-2 py-1 text-xs text-ink outline-none"
        />
        <Button compact variant="primary" type="submit" disabled={!text.trim()}>
          Add
        </Button>
      </form>
    );
  }

  return (
    <select
      autoFocus
      defaultValue=""
      onChange={(e) => {
        if (e.target.value === "__other__") {
          setOther(true);
        } else if (e.target.value) {
          onAdd(e.target.value, false);
        }
      }}
      onBlur={onCancel}
      className="rounded-lg border border-brand bg-surface px-2 py-1 text-xs text-ink outline-none"
    >
      <option value="" disabled>
        Compare from…
      </option>
      {available.map((loc) => (
        <option key={loc} value={loc}>
          {loc}
        </option>
      ))}
      <option value="__other__">Other…</option>
    </select>
  );
}

/** One cost row's cell for one location column - the figure, its note behind
 *  a hover icon, and (when editable) the override controls. */
function Cell({
  component,
  selected,
  readOnly,
  busy,
  onSave,
  onClear,
}: {
  component: PricingComponent | undefined;
  selected: boolean;
  readOnly: boolean;
  busy: boolean;
  onSave: (amount: string) => void;
  onClear: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(component?.amount ?? "0");
  // The chosen column is framed, not merely shaded: side rails carry the eye
  // down it, which a background tint alone does not do once the table is
  // wide enough that three columns of similar figures sit side by side.
  const tint = selected ? "bg-brand-wash border-x-2 border-x-brand" : "";

  if (!component) {
    return (
      <td className={`px-4 py-2.5 text-right align-top text-ink-faint ${tint}`}>—</td>
    );
  }

  return (
    <td
      className={`px-4 py-2.5 align-top ${tint} ${component.applied ? "" : "opacity-60"}`}
    >
      <div className="flex items-center justify-end gap-1.5">
        {editing ? (
          <>
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
              className="tabular w-24 rounded-lg border border-brand bg-surface px-2 py-1 text-right text-sm text-ink outline-none"
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
          </>
        ) : (
          <>
            <span
              className={`tabular ${selected ? "font-bold" : "font-semibold"} ${
                component.overridden ? "text-brand" : "text-ink"
              }`}
            >
              {inr(component.amount, false)}
            </span>
            <span
              tabIndex={0}
              title={component.note}
              className="rounded p-0.5 text-ink-faint outline-none transition-colors hover:text-ink focus-visible:text-ink"
            >
              <InfoIcon />
            </span>
            {!readOnly && (
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
          </>
        )}
      </div>
    </td>
  );
}

export default function PricingCalculatorGroup({
  quotationId,
  item,
  readOnly,
  onChanged,
}: {
  quotationId: number;
  item: LineItem;
  readOnly: boolean;
  onChanged: () => void;
}) {
  // Most lines have exactly one option already embedded on `item.pricing` -
  // only fetch the full list when there is reason to think there's more
  // than one, or once the trader opens the picker.
  const [expanded, setExpanded] = useState(item.pricing_option_count > 1);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const optionsApi = useApi<QuotationPricing[]>(
    expanded ? `/quotations/${quotationId}/lines/${item.id}/pricing/options` : null,
  );
  const locationsApi = useApi<string[]>(adding ? "/quotations/pricing/locations" : null);

  const options = expanded ? optionsApi.data ?? [] : item.pricing ? [item.pricing] : [];

  useEffect(() => {
    if (item.pricing_option_count > 1) setExpanded(true);
  }, [item.pricing_option_count]);

  async function addOption(location: string, manual: boolean) {
    setBusy("add");
    setError(null);
    try {
      await api.post(`/quotations/${quotationId}/lines/${item.id}/pricing/options`, {
        despatch_location: location,
        manual,
      });
      setExpanded(true);
      setAdding(false);
      optionsApi.reload();
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function selectOption(pricingId: number) {
    setBusy("select");
    setError(null);
    try {
      await api.post(
        `/quotations/${quotationId}/lines/${item.id}/pricing/options/${pricingId}/select`,
      );
      optionsApi.reload();
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function override(pricing: QuotationPricing, code: string, amount: string) {
    setBusy("override");
    setError(null);
    try {
      await api.post(`/quotations/${quotationId}/lines/${item.id}/pricing/override`, {
        component_code: code,
        amount,
        despatch_location: pricing.despatch_location,
      });
      optionsApi.reload();
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function clearOverride(pricing: QuotationPricing, code: string) {
    setBusy("clear");
    setError(null);
    try {
      await api.del(
        `/quotations/${quotationId}/lines/${item.id}/pricing/override/${code}` +
          query({ despatch_location: pricing.despatch_location }),
      );
      optionsApi.reload();
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  // Fetching the full option list (a line with more than one, or the
  // trader just added a second) - `options` is briefly empty here even
  // though this line does have pricing, and must not be read as "unpriced".
  if (expanded && optionsApi.loading && options.length === 0) {
    return <Loading label="Loading pricing options" />;
  }

  if (!item.pricing && options.length === 0) {
    return (
      <Banner tone="attention">
        This line has not been priced — no landed cost on the matched stock and no current mill
        offer covers it.
      </Banner>
    );
  }

  // One row per component code that appears in *any* option, in the order
  // it first appears - so a manual option's empty table doesn't collapse
  // the columns that do have figures down to nothing.
  const codeOrder: string[] = [];
  const kindByCode = new Map<string, string>();
  const labelByCode = new Map<string, string>();
  for (const option of options) {
    for (const c of option.components) {
      if (!codeOrder.includes(c.code)) codeOrder.push(c.code);
      if (!kindByCode.has(c.code)) kindByCode.set(c.code, c.kind);
      if (!labelByCode.has(c.code)) labelByCode.set(c.code, c.label);
    }
  }
  const costCodes = codeOrder.filter((code) => !MARGIN_KINDS.has(kindByCode.get(code) ?? ""));
  const marginCodes = codeOrder.filter((code) => MARGIN_KINDS.has(kindByCode.get(code) ?? ""));
  const componentFor = (option: QuotationPricing, code: string) =>
    option.components.find((c) => c.code === code);

  /* Marking the chosen column only means something when there is another one
     to choose instead. On the ordinary single-column line, framing the only
     column is decoration around a decision nobody made. */
  const marked = (option: QuotationPricing) => options.length > 1 && option.is_selected;

  return (
    <div className="flex flex-col gap-3">
      {error && <Banner tone="danger">{error}</Banner>}

      <div className="overflow-hidden rounded-card border border-rule bg-surface shadow-card">
        <header className="flex items-center justify-between gap-3 border-b border-rule px-4 py-3">
          <h3 className="text-base font-semibold text-ink">Pricing calculator</h3>
        </header>

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-rule bg-sunk text-xs font-medium text-ink-soft">
                <th className="px-4 py-2 text-left">Description</th>
                {options.map((o) => (
                  <th
                    key={o.id}
                    className={`px-4 py-2 text-right ${
                      marked(o)
                        ? "border-x-2 border-t-2 border-brand bg-brand-wash"
                        : ""
                    }`}
                  >
                    <button
                      type="button"
                      disabled={readOnly || busy !== null || o.is_selected}
                      onClick={() => selectOption(o.id)}
                      title={
                        o.is_selected
                          ? "Selected — this is what will be sent"
                          : "Click to select this as the price to send"
                      }
                      className={`inline-flex items-center gap-1 rounded px-1 py-0.5 transition-colors ${
                        o.is_selected
                          ? "text-[13px] font-bold text-brand"
                          : "text-ink-soft hover:text-brand disabled:hover:text-ink-soft"
                      }`}
                    >
                      {o.despatch_location ?? "Price"} ({o.currency}/MT)
                      {o.is_selected && " ✓"}
                    </button>
                  </th>
                ))}
                {!readOnly && options.length < MAX_OPTIONS && (
                  <th className="w-10 px-2 py-2 text-center">
                    {adding ? (
                      <AddLocationPicker
                        knownLocations={locationsApi.data ?? []}
                        excluding={options.map((o) => o.despatch_location)}
                        onAdd={addOption}
                        onCancel={() => setAdding(false)}
                      />
                    ) : (
                      <button
                        type="button"
                        title="Compare pricing from another location"
                        onClick={() => setAdding(true)}
                        className="rounded-lg border border-dashed border-rule p-1.5 text-ink-faint transition-colors hover:border-brand hover:text-brand"
                      >
                        <PlusIcon />
                      </button>
                    )}
                  </th>
                )}
              </tr>
            </thead>

            <tbody>
              {costCodes.map((code, i) => (
                <tr key={code} className="border-b border-rule">
                  <td className="px-4 py-2.5 align-top text-ink">
                    <span className="tabular mr-1.5 text-ink-faint">{i + 1}.</span>
                    {labelByCode.get(code) ?? code}
                  </td>
                  {options.map((o) => (
                    <Cell
                      key={o.id}
                      component={componentFor(o, code)}
                      selected={marked(o)}
                      readOnly={readOnly}
                      busy={busy !== null}
                      onSave={(amount) => override(o, code, amount)}
                      onClear={() => clearOverride(o, code)}
                    />
                  ))}
                  {!readOnly && options.length < MAX_OPTIONS && <td />}
                </tr>
              ))}

              {/* Total cost: the sum, so it carries no pencil of its own. */}
              <tr className="border-b border-rule bg-sunk">
                <td className="px-4 py-2.5 font-semibold text-ink">Total cost</td>
                {options.map((o) => (
                  <td
                    key={o.id}
                    className={`tabular px-4 py-2.5 text-right font-bold text-ink ${
                      marked(o) ? "border-x-2 border-x-brand bg-brand-wash" : ""
                    }`}
                  >
                    {inr(o.total_cost, false)}
                  </td>
                ))}
                {!readOnly && options.length < MAX_OPTIONS && <td />}
              </tr>

              {marginCodes.map((code, i) => (
                <tr key={code} className="border-b border-rule">
                  <td className="px-4 py-2.5 align-top text-ink">
                    <span className="tabular mr-1.5 text-ink-faint">
                      {costCodes.length + i + 1}.
                    </span>
                    {labelByCode.get(code) ?? code}
                  </td>
                  {options.map((o) => (
                    <Cell
                      key={o.id}
                      component={componentFor(o, code)}
                      selected={marked(o)}
                      readOnly={readOnly}
                      busy={busy !== null}
                      onSave={(amount) => override(o, code, amount)}
                      onClear={() => clearOverride(o, code)}
                    />
                  ))}
                  {!readOnly && options.length < MAX_OPTIONS && <td />}
                </tr>
              ))}
            </tbody>

            <tfoot>
              <tr className="bg-brand-wash">
                <td className="px-4 py-3 font-semibold text-brand">
                  Recommended quote price
                </td>
                {options.map((o) => (
                  <td
                    key={o.id}
                    className={`px-4 py-3 text-right ${
                      marked(o) ? "border-x-2 border-b-2 border-brand" : ""
                    }`}
                  >
                    <span
                      className={`tabular font-bold text-brand ${
                        marked(o) ? "text-lg" : "text-base"
                      }`}
                    >
                      {inr(o.quote_rate, false)}
                    </span>
                    <span className="mt-0.5 block text-xs font-normal text-brand/80">
                      {o.line_total && o.quantity_mt
                        ? `${num(o.quantity_mt)} MT · ${inr(o.line_total)} total`
                        : "Indicative"}
                    </span>
                  </td>
                ))}
                {!readOnly && options.length < MAX_OPTIONS && <td />}
              </tr>
            </tfoot>
          </table>
        </div>
      </div>
    </div>
  );
}

