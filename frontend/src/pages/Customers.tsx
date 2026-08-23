import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, query, useApi } from "../api/client";
import type { Customer, CustomerNote, Page, TimelineEntry } from "../api/types";
import {
  ago,
  Badge,
  Banner,
  Button,
  Empty,
  ErrorNote,
  Field,
  Input,
  Loading,
  Scroller,
  when,
} from "../components/ui";

/* ---------------------------------------------------------------------------
   Accounts.

   A directory beside a record, with the interaction timeline built from what
   already happened - every enquiry, every quotation, every note - rather than
   from a separate CRM the desk would have to keep up to date by hand.
   --------------------------------------------------------------------------- */

function Avatar({ name }: { name: string }) {
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase())
    .join("");
  let hash = 0;
  for (const ch of name) hash = (hash * 31 + ch.charCodeAt(0)) % 360;

  return (
    <span
      className="grid size-8 shrink-0 place-items-center rounded-full text-[11px] font-semibold text-white"
      style={{ background: `oklch(0.58 0.1 ${hash})` }}
      aria-hidden="true"
    >
      {initials || "?"}
    </span>
  );
}

const TIMELINE_TONE: Record<string, string> = {
  ENQUIRY: "bg-info",
  QUOTED: "bg-brand",
  NOTE: "bg-ink-faint",
};

function Timeline({ customerId }: { customerId: number }) {
  const { data } = useApi<TimelineEntry[]>(`/customers/${customerId}/timeline`);

  if (!data) return <Loading label="Loading history" />;
  if (data.length === 0) return <Empty message="Nothing recorded yet." />;

  return (
    <ol className="flex flex-col">
      {data.map((entry, i) => (
        <li key={`${entry.at}-${i}`} className="flex gap-3">
          <div className="flex flex-col items-center">
            <span
              className={`mt-1.5 size-2 shrink-0 rounded-full ${TIMELINE_TONE[entry.kind] ?? "bg-rule-firm"}`}
            />
            {i < data.length - 1 && <span className="w-px flex-1 bg-rule" />}
          </div>
          <div className="min-w-0 flex-1 pb-4">
            <div className="flex items-baseline justify-between gap-2">
              {entry.link ? (
                <Link to={entry.link} className="text-sm font-medium text-brand hover:underline">
                  {entry.title}
                </Link>
              ) : (
                <span className="text-sm font-medium text-ink">{entry.title}</span>
              )}
              <span className="shrink-0 text-[11px] text-ink-faint">{ago(entry.at)}</span>
            </div>
            {entry.detail && (
              <p className="mt-0.5 whitespace-pre-wrap text-xs text-ink-soft">{entry.detail}</p>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}

function Notes({ customerId }: { customerId: number }) {
  const { data, reload } = useApi<CustomerNote[]>(`/customers/${customerId}/notes`);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);

  async function add() {
    if (!draft.trim()) return;
    setBusy(true);
    try {
      await api.post(`/customers/${customerId}/notes`, { body: draft.trim() });
      setDraft("");
      reload();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex gap-2">
        <Input
          value={draft}
          onChange={setDraft}
          placeholder="Add a note about this account"
          className="flex-1"
        />
        <Button variant="primary" disabled={busy || !draft.trim()} onClick={add}>
          Add
        </Button>
      </div>
      {data?.map((note) => (
        <div key={note.id} className="rounded-lg border border-rule bg-sunk px-3 py-2">
          <p className="whitespace-pre-wrap text-sm text-ink">{note.body}</p>
          <p className="mt-1 text-[11px] text-ink-faint">{when(note.created_at)}</p>
        </div>
      ))}
    </div>
  );
}

function Detail({ id, onChanged }: { id: number; onChanged: () => void }) {
  const { data, loading, reload } = useApi<Customer>(`/customers/${id}`);
  const [tab, setTab] = useState<"history" | "notes">("history");
  const [busy, setBusy] = useState(false);

  if (loading && !data) return <Loading />;
  if (!data) return null;

  async function verify() {
    setBusy(true);
    try {
      await api.post(`/customers/${id}/verify`);
      reload();
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex h-full flex-col">
      <header className="border-b border-rule px-5 py-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <Avatar name={data.company || data.name} />
            <div className="min-w-0">
              <h2 className="truncate text-base font-semibold text-ink">
                {data.company || data.name}
              </h2>
              <p className="truncate text-xs text-ink-faint">{data.email ?? "no email on file"}</p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Badge value={`TIER ${data.tier}`} dot={false} />
            {!data.is_verified && (
              <Button variant="primary" disabled={busy} onClick={verify}>
                Verify
              </Button>
            )}
          </div>
        </div>

        {!data.is_verified && (
          <div className="mt-3">
            <Banner tone="attention">
              Built from an email signature and not yet confirmed. Until it is verified, the tier
              adjustment is withheld from pricing.
            </Banner>
          </div>
        )}
      </header>

      <div className="border-b border-rule px-5 py-3">
        <dl className="grid gap-x-8 sm:grid-cols-2">
          <Field label="Contact">{data.name}</Field>
          <Field label="Phone">{data.phone ?? "—"}</Field>
          <Field label="Code">{data.customer_code ?? "—"}</Field>
          <Field label="Delivers to">{data.default_delivery_location ?? "—"}</Field>
          <Field label="Payment terms">{data.payment_terms ?? "—"}</Field>
          <Field label="Status">{data.status}</Field>
        </dl>
      </div>

      <nav className="flex gap-1 border-b border-rule px-4">
        {(["history", "notes"] as const).map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium capitalize transition-colors ${
              tab === t
                ? "border-brand-soft text-brand-soft-ink"
                : "border-transparent text-ink-faint hover:text-ink"
            }`}
          >
            {t}
          </button>
        ))}
      </nav>

      <div className="flex-1 overflow-y-auto px-5 py-4">
        {tab === "history" ? <Timeline customerId={id} /> : <Notes customerId={id} />}
      </div>
    </div>
  );
}

export default function Customers() {
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<number | null>(null);

  const { data, error, loading, reload } = useApi<Page<Customer>>(
    `/customers${query({ search, limit: 200 })}`,
  );

  useEffect(() => {
    if (selected === null && data?.items.length) setSelected(data.items[0].id);
  }, [data, selected]);

  const unverified = (data?.items ?? []).filter((c) => !c.is_verified).length;

  return (
    <div className="flex h-[calc(100vh-7rem)] flex-col md:h-[calc(100vh-3.25rem)]">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-rule px-5 py-3">
        <div>
          <p className="text-sm text-ink-soft">
            {data ? `${data.total} on file` : "…"}
            {unverified > 0 && ` · ${unverified} unconfirmed`}
          </p>
        </div>
        <Input
          value={search}
          onChange={setSearch}
          placeholder="Search name, company or email"
          className="w-64"
        />
      </header>

      {error && <div className="p-4"><ErrorNote message={error} /></div>}

      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[20rem_1fr]">
        <Scroller
          className={`min-h-0 overflow-y-auto border-r border-rule ${
            selected ? "hidden lg:block" : "block"
          }`}
        >
          {loading && !data ? (
            <Loading />
          ) : data?.items.length ? (
            data.items.map((c) => (
              <button
                key={c.id}
                type="button"
                onClick={() => setSelected(c.id)}
                className={`flex w-full items-center gap-3 border-b border-rule px-3 py-2.5 text-left transition-colors ${
                  selected === c.id ? "bg-brand-wash" : "hover:bg-sunk"
                }`}
              >
                <Avatar name={c.company || c.name} />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] font-medium text-ink">
                    {c.company || c.name}
                  </p>
                  <p className="truncate text-xs text-ink-faint">{c.email ?? c.name}</p>
                </div>
                {!c.is_verified && (
                  <span
                    className="size-1.5 shrink-0 rounded-full bg-attention"
                    title="Unconfirmed"
                  />
                )}
              </button>
            ))
          ) : (
            <Empty message="No customers match." />
          )}
        </Scroller>

        <div
          className={`min-h-0 overflow-hidden bg-surface ${
            selected ? "block" : "hidden lg:block"
          }`}
        >
          {selected ? (
            <Detail id={selected} onChanged={reload} />
          ) : (
            <Empty message="Select a customer." />
          )}
        </div>
      </div>
    </div>
  );
}
