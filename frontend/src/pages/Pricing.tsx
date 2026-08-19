import { useEffect, useState } from "react";

import { api, useApi } from "../api/client";
import type {
  LocationDistance,
  PricingPreview,
  PricingRule,
  PricingRuleSet,
  VehicleRate,
} from "../api/types";
import {
  Badge,
  Banner,
  Button,
  Card,
  Empty,
  ErrorNote,
  Input,
  inr,
  Loading,
  SectionLabel,
  Select,
  Toggle,
} from "../components/ui";

/* ---------------------------------------------------------------------------
   The rules a trader owns.

   Two panels side by side: the rules on the left, a live worked example on the
   right. Editing a rule re-prices the example immediately, so the effect of a
   change is visible *before* it is published - which is what makes handing
   pricing to a non-developer safe.
   --------------------------------------------------------------------------- */

const KIND_OPTIONS = [
  { value: "BASE_PRICE", label: "Base price" },
  { value: "TRANSPORTATION", label: "Transportation" },
  { value: "HANDLING", label: "Loading / unloading" },
  { value: "FINANCING", label: "Financing cost" },
  { value: "RISK_BUFFER", label: "Risk buffer" },
  { value: "QUANTITY_SLAB", label: "Volume band" },
  { value: "CUSTOMER_TIER", label: "Customer tier" },
  { value: "INVOICE_ANCHOR", label: "Recent sales anchor" },
  { value: "ADJUSTMENT", label: "Other adjustment" },
  { value: "TARGET_MARGIN", label: "Target margin" },
  { value: "MARGIN_FLOOR", label: "Minimum margin" },
  { value: "ROUNDING", label: "Rounding" },
];

/** Which config field a kind actually needs, so the editor asks for that. */
const CONFIG_FIELD: Record<string, { key: string; label: string; suffix: string } | null> = {
  HANDLING: { key: "amount_per_mt", label: "Amount", suffix: "₹/MT" },
  RISK_BUFFER: { key: "amount_per_mt", label: "Amount", suffix: "₹/MT" },
  ADJUSTMENT: { key: "amount_per_mt", label: "Amount", suffix: "₹/MT" },
  FINANCING: { key: "annual_rate_pct", label: "Interest", suffix: "% p.a." },
  TARGET_MARGIN: { key: "pct", label: "Margin", suffix: "%" },
  MARGIN_FLOOR: { key: "minimum_margin_pct", label: "Minimum", suffix: "%" },
  ROUNDING: { key: "nearest", label: "Nearest", suffix: "₹" },
  BASE_PRICE: null,
  TRANSPORTATION: null,
  QUANTITY_SLAB: null,
  CUSTOMER_TIER: null,
  INVOICE_ANCHOR: null,
};

function RuleRow({
  rule,
  onChange,
  onRemove,
  onMove,
}: {
  rule: PricingRule;
  onChange: (next: PricingRule) => void;
  onRemove: () => void;
  onMove: (direction: -1 | 1) => void;
}) {
  const field = CONFIG_FIELD[rule.kind];

  return (
    <div
      className={`flex flex-col gap-2 border-b border-rule px-3 py-2.5 last:border-0 ${
        rule.is_active ? "" : "opacity-55"
      }`}
    >
      <div className="flex items-center gap-2">
        <div className="flex flex-col">
          <button
            type="button"
            onClick={() => onMove(-1)}
            className="text-ink-faint hover:text-ink"
            title="Move up"
          >
            <svg viewBox="0 0 24 24" className="size-3" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M6 15l6-6 6 6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
          <button
            type="button"
            onClick={() => onMove(1)}
            className="text-ink-faint hover:text-ink"
            title="Move down"
          >
            <svg viewBox="0 0 24 24" className="size-3" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M6 9l6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        </div>

        <Input
          value={rule.label}
          onChange={(label) => onChange({ ...rule, label })}
          className="flex-1"
        />

        <Select
          value={rule.kind}
          onChange={(kind) => onChange({ ...rule, kind: kind as PricingRule["kind"] })}
          options={KIND_OPTIONS}
          className="w-44"
        />

        {field && (
          <div className="flex items-center gap-1">
            <Input
              type="number"
              step="0.01"
              value={String(rule.config[field.key] ?? "")}
              onChange={(v) =>
                onChange({ ...rule, config: { ...rule.config, [field.key]: Number(v) } })
              }
              className="w-24 text-right"
            />
            <span className="w-12 text-xs text-ink-faint">{field.suffix}</span>
          </div>
        )}
        {!field && <span className="w-[9.25rem] text-xs text-ink-faint">configured below</span>}

        <Toggle
          checked={rule.is_active}
          onChange={(is_active) => onChange({ ...rule, is_active })}
        />

        <button
          type="button"
          onClick={onRemove}
          title="Remove this rule"
          className="rounded p-1 text-ink-faint hover:bg-danger-wash hover:text-danger"
        >
          <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M4 7h16M9 7V5h6v2M6 7l1 13h10l1-13" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </div>

      {rule.kind === "TRANSPORTATION" && (
        <p className="pl-8 text-xs text-ink-faint">
          Uses the distance and vehicle tables below. Set{" "}
          <code className="rounded bg-sunk px-1">amount_per_mt</code> in advanced config for a flat
          rate instead.
        </p>
      )}
    </div>
  );
}

function PreviewPanel({ rules }: { rules: PricingRule[] }) {
  const [baseRate, setBaseRate] = useState("52000");
  const [quantity, setQuantity] = useState("100");
  const [location, setLocation] = useState("Patna");
  const [preview, setPreview] = useState<PricingPreview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const timer = setTimeout(async () => {
      try {
        const result = await api.post<PricingPreview>("/pricing/preview", {
          rules: rules.map(({ id, ...rest }) => rest),
          base_rate: baseRate || null,
          quantity_mt: quantity || null,
          delivery_location: location || null,
        });
        setPreview(result);
        setError(null);
      } catch (e) {
        setError((e as Error).message);
      }
    }, 350);
    return () => clearTimeout(timer);
  }, [rules, baseRate, quantity, location]);

  return (
    <Card
      title="Worked example"
      subtitle="Updates as you edit. Nothing is saved until you publish."
    >
      <div className="flex flex-col gap-3">
        <div className="grid grid-cols-3 gap-2">
          <label className="flex flex-col gap-1">
            <span className="text-[11px] uppercase tracking-wider text-ink-faint">Base ₹/MT</span>
            <Input value={baseRate} onChange={setBaseRate} type="number" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[11px] uppercase tracking-wider text-ink-faint">Quantity MT</span>
            <Input value={quantity} onChange={setQuantity} type="number" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[11px] uppercase tracking-wider text-ink-faint">Deliver to</span>
            <Input value={location} onChange={setLocation} />
          </label>
        </div>

        {error && <ErrorNote message={error} />}

        {preview && (
          <div className="overflow-hidden rounded-lg border border-rule">
            <table className="w-full text-sm">
              <tbody className="divide-y divide-rule">
                {preview.components.map((c) => (
                  <tr key={c.code} className={c.applied ? "" : "opacity-55"}>
                    <td className="px-2.5 py-1.5">
                      <div className="text-ink">{c.label}</div>
                      <div className="text-[11px] leading-snug text-ink-faint">{c.note}</div>
                    </td>
                    <td className="px-2.5 py-1.5 text-right tabular text-ink">
                      {inr(c.amount, false)}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot className="border-t-2 border-ink/70 bg-sunk">
                <tr>
                  <td className="px-2.5 py-2 font-semibold text-ink">Total cost</td>
                  <td className="px-2.5 py-2 text-right font-semibold tabular text-ink">
                    {inr(preview.total_cost, false)}
                  </td>
                </tr>
                <tr>
                  <td className="px-2.5 py-2 font-semibold text-brand">Quote price</td>
                  <td className="px-2.5 py-2 text-right text-base font-bold tabular text-brand">
                    {inr(preview.quote_rate, false)} / MT
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        )}

        {preview?.warnings.map((w) => (
          <Banner key={w} tone="attention">
            {w}
          </Banner>
        ))}
      </div>
    </Card>
  );
}

function DistancesPanel() {
  const { data, reload } = useApi<LocationDistance[]>("/pricing/distances");
  const [origin, setOrigin] = useState("Nagpur");
  const [destination, setDestination] = useState("");
  const [km, setKm] = useState("");
  const [days, setDays] = useState("");

  async function add() {
    if (!destination || !km) return;
    await api.post("/pricing/distances", {
      origin,
      destination,
      distance_km: Number(km),
      typical_days: days ? Number(days) : null,
    });
    setDestination("");
    setKm("");
    setDays("");
    reload();
  }

  return (
    <Card title="Distances" subtitle="Road distances the freight rule reads" padded={false}>
      <div className="flex items-end gap-2 border-b border-rule p-3">
        <Input value={origin} onChange={setOrigin} placeholder="From" className="w-24 shrink-0" />
        <Input value={destination} onChange={setDestination} placeholder="To" className="min-w-24 flex-1" />
        <Input value={km} onChange={setKm} placeholder="km" type="number" className="w-20 shrink-0" />
        <Input value={days} onChange={setDays} placeholder="days" type="number" className="w-20 shrink-0" />
        <Button variant="primary" onClick={add}>
          Add
        </Button>
      </div>
      <table className="w-full text-sm">
        <tbody className="divide-y divide-rule">
          {data?.map((row) => (
            <tr key={row.id}>
              <td className="px-3 py-1.5 text-ink">
                {row.origin} → {row.destination}
              </td>
              <td className="px-3 py-1.5 text-right tabular text-ink-soft">{row.distance_km} km</td>
              <td className="px-3 py-1.5 text-right tabular text-ink-faint">
                {row.typical_days ? `${row.typical_days} d` : "—"}
              </td>
              <td className="px-3 py-1.5 text-right">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={async () => {
                    await api.del(`/pricing/distances/${row.id}`);
                    reload();
                  }}
                >
                  Remove
                </Button>
              </td>
            </tr>
          ))}
          {!data?.length && (
            <tr>
              <td colSpan={4} className="px-3 py-6 text-center text-sm text-ink-faint">
                No distances yet. Freight cannot be calculated without them.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </Card>
  );
}

function VehiclesPanel() {
  const { data, reload } = useApi<VehicleRate[]>("/pricing/vehicles");
  const [name, setName] = useState("");
  const [capacity, setCapacity] = useState("");
  const [rate, setRate] = useState("");

  async function add() {
    if (!name || !capacity || !rate) return;
    await api.post("/pricing/vehicles", {
      name,
      capacity_mt: capacity,
      rate_per_day: rate,
    });
    setName("");
    setCapacity("");
    setRate("");
    reload();
  }

  return (
    <Card title="Vehicles" subtitle="Hire economics freight is derived from" padded={false}>
      <div className="flex items-end gap-2 border-b border-rule p-3">
        <Input value={name} onChange={setName} placeholder="Trailer" className="flex-1" />
        <Input value={capacity} onChange={setCapacity} placeholder="MT" type="number" className="w-20" />
        <Input value={rate} onChange={setRate} placeholder="₹/day" type="number" className="w-28" />
        <Button variant="primary" onClick={add}>
          Add
        </Button>
      </div>
      <table className="w-full text-sm">
        <tbody className="divide-y divide-rule">
          {data?.map((row) => (
            <tr key={row.id}>
              <td className="px-3 py-1.5 text-ink">{row.name}</td>
              <td className="px-3 py-1.5 text-right tabular text-ink-soft">{row.capacity_mt} MT</td>
              <td className="px-3 py-1.5 text-right tabular text-ink-soft">
                {inr(row.rate_per_day)}/day
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

export default function Pricing() {
  const { data: active, loading, error, reload } = useApi<PricingRuleSet>("/pricing/rules");
  const [rules, setRules] = useState<PricingRule[] | null>(null);
  const [publishing, setPublishing] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (active) setRules(active.rules.map((r) => ({ ...r })));
  }, [active]);

  if (loading && !active) return <Loading label="Loading pricing rules" />;
  if (error) return <div className="p-6"><ErrorNote message={error} /></div>;
  if (!rules) return <Empty message="No pricing rules are published yet." />;

  const dirty = JSON.stringify(rules) !== JSON.stringify(active?.rules ?? []);

  function update(index: number, next: PricingRule) {
    setRules((current) => current!.map((r, i) => (i === index ? next : r)));
  }

  function move(index: number, direction: -1 | 1) {
    const target = index + direction;
    if (target < 0 || target >= rules!.length) return;
    const next = [...rules!];
    [next[index], next[target]] = [next[target], next[index]];
    setRules(next.map((r, i) => ({ ...r, priority: (i + 1) * 10 })));
  }

  async function publish() {
    setPublishing(true);
    setMessage(null);
    try {
      const saved = await api.put<PricingRuleSet>("/pricing/rules", {
        label: `Edited ${new Date().toLocaleDateString("en-IN")}`,
        rules: rules!.map(({ id, ...rest }, i) => ({ ...rest, priority: (i + 1) * 10 })),
      });
      setMessage(`Published version ${saved.version}. It is now pricing every new enquiry.`);
      reload();
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setPublishing(false);
    }
  }

  return (
    <div className="flex flex-col gap-4 p-5">
      <header className="flex items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-ink">Pricing</h1>
          <p className="text-sm text-ink-faint">
            The cost build-up applied to every enquiry. Version {active?.version} is live.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {dirty && <Badge value="UNPUBLISHED" />}
          <Button
            variant="primary"
            disabled={!dirty || publishing}
            onClick={publish}
          >
            {publishing ? "Publishing…" : "Publish new version"}
          </Button>
        </div>
      </header>

      {message && <Banner tone={message.startsWith("Published") ? "settled" : "danger"}>{message}</Banner>}

      {dirty && (
        <Banner tone="info">
          These edits are not live yet. The example on the right shows what they would produce.
        </Banner>
      )}

      <div className="grid gap-4 xl:grid-cols-[1.35fr_1fr]">
        <Card
          title="Rules"
          subtitle="Applied in order. Margin, floor and rounding always run last."
          padded={false}
          action={
            <Button
              size="sm"
              onClick={() =>
                setRules([
                  ...rules,
                  {
                    code: `rule_${Date.now().toString(36)}`,
                    label: "New cost line",
                    kind: "HANDLING",
                    priority: (rules.length + 1) * 10,
                    is_active: true,
                    conditions: null,
                    config: { amount_per_mt: 0 },
                  },
                ])
              }
            >
              Add rule
            </Button>
          }
        >
          {rules.map((rule, index) => (
            <RuleRow
              key={rule.code}
              rule={rule}
              onChange={(next) => update(index, next)}
              onRemove={() => setRules(rules.filter((_, i) => i !== index))}
              onMove={(direction) => move(index, direction)}
            />
          ))}
        </Card>

        <div className="flex flex-col gap-4">
          <PreviewPanel rules={rules} />
          <DistancesPanel />
          <VehiclesPanel />
        </div>
      </div>

      <SectionLabel>Version history</SectionLabel>
      <VersionHistory onRestore={reload} />
    </div>
  );
}

function VersionHistory({ onRestore }: { onRestore: () => void }) {
  const { data, reload } = useApi<PricingRuleSet[]>("/pricing/rules/history");

  return (
    <Card padded={false}>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-rule bg-sunk text-[11px] uppercase tracking-wider text-ink-faint">
            <th className="px-3 py-1.5 text-left font-medium">Version</th>
            <th className="px-3 py-1.5 text-left font-medium">Label</th>
            <th className="px-3 py-1.5 text-left font-medium">Published</th>
            <th className="px-3 py-1.5 text-right font-medium">Rules</th>
            <th className="px-3 py-1.5" />
          </tr>
        </thead>
        <tbody className="divide-y divide-rule">
          {data?.map((set) => (
            <tr key={set.id}>
              <td className="px-3 py-1.5 tabular font-medium text-ink">
                v{set.version} {set.is_active && <Badge value="ACTIVE" className="ml-1" />}
              </td>
              <td className="px-3 py-1.5 text-ink-soft">{set.label ?? "—"}</td>
              <td className="px-3 py-1.5 text-ink-faint">
                {set.published_at ? new Date(set.published_at).toLocaleString("en-IN") : "—"}
              </td>
              <td className="px-3 py-1.5 text-right tabular text-ink-soft">{set.rules.length}</td>
              <td className="px-3 py-1.5 text-right">
                {!set.is_active && (
                  <Button
                    size="sm"
                    onClick={async () => {
                      await api.post(`/pricing/rules/${set.version}/restore`);
                      reload();
                      onRestore();
                    }}
                  >
                    Restore
                  </Button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}
