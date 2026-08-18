import { useState } from "react";

import { query, useApi } from "../api/client";
import type { Customer, Page } from "../api/types";
import { Card, Empty, ErrorNote, Field, Loading } from "../components/ui";

export default function Customers() {
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<number | null>(null);

  const { data, error, loading } = useApi<Page<Customer>>(
    `/customers${query({ search, limit: 200 })}`,
  );
  const { data: detail } = useApi<Customer>(selected ? `/customers/${selected}` : null);

  const unverified = (data?.items ?? []).filter((c) => !c.is_verified).length;

  return (
    <div className="space-y-4 p-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-ink-900">Customers</h1>
          <p className="text-sm text-ink-500">
            {data ? `${data.total} on file` : "…"}
            {unverified > 0 && ` · ${unverified} unconfirmed`}
          </p>
        </div>
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search name, company or email"
          className="w-72 rounded-lg border border-ink-300 bg-white px-3 py-1.5 text-sm"
        />
      </header>

      {error && <ErrorNote message={error} />}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="overflow-hidden lg:col-span-2">
          {loading && !data ? (
            <Loading />
          ) : !data || data.items.length === 0 ? (
            <Empty
              message={
                search
                  ? "No customers match."
                  : "No customers yet — they appear here as enquiries arrive."
              }
            />
          ) : (
            <div className="-m-4 max-h-[70vh] overflow-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 border-b border-ink-200 bg-ink-50 text-left text-xs uppercase tracking-wide text-ink-500">
                  <tr>
                    <th className="px-4 py-2 font-medium">Company</th>
                    <th className="px-4 py-2 font-medium">Contact</th>
                    <th className="px-4 py-2 font-medium">Location</th>
                    <th className="px-4 py-2 font-medium">Tier</th>
                    <th className="px-4 py-2 font-medium">Source</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink-100">
                  {data.items.map((customer) => (
                    <tr
                      key={customer.id}
                      onClick={() => setSelected(customer.id)}
                      className={`cursor-pointer hover:bg-ink-50 ${
                        selected === customer.id ? "bg-ink-100" : ""
                      }`}
                    >
                      <td className="px-4 py-2 font-medium">{customer.company ?? "—"}</td>
                      <td className="px-4 py-2 text-ink-700">
                        {customer.name}
                        <span className="block text-xs text-ink-500">{customer.email}</span>
                      </td>
                      <td className="px-4 py-2">{customer.default_delivery_location ?? "—"}</td>
                      <td className="px-4 py-2">{customer.tier}</td>
                      <td className="px-4 py-2">
                        {customer.is_verified ? (
                          <span className="text-xs text-ink-500">Confirmed</span>
                        ) : (
                          <span className="inline-flex items-center rounded-md bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800 ring-1 ring-inset ring-amber-200">
                            From email
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card title={detail ? detail.company ?? detail.name : "Select a customer"}>
          {!detail ? (
            <p className="text-sm text-ink-500">
              Pick a customer to see their contact details. A sender nobody has on file is
              added here automatically on their first enquiry, marked{" "}
              <span className="font-medium">From email</span> until someone confirms them.
              Importing <span className="font-mono text-xs">customers.xlsx</span> marks a
              record confirmed and fills in tier and payment terms.
            </p>
          ) : (
            <dl>
              <Field label="Contact">{detail.name}</Field>
              <Field label="Email">{detail.email ?? "—"}</Field>
              <Field label="Phone">{detail.phone ?? "—"}</Field>
              <Field label="Tier">{detail.tier}</Field>
              <Field label="Payment terms">{detail.payment_terms ?? "—"}</Field>
              <Field label="Default delivery">{detail.default_delivery_location ?? "—"}</Field>
              <Field label="Record">
                {detail.is_verified
                  ? "Confirmed"
                  : "Created from an email signature — tier and payment terms are defaults, not agreed figures."}
              </Field>
            </dl>
          )}
        </Card>
      </div>
    </div>
  );
}
