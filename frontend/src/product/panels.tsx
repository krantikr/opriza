import { useEffect, useState } from "react";

import { api } from "../api/client";
import { IChat, ISend } from "../demo/desk/icons";
import { Empty, GradeTag, Tabs } from "../demo/desk/ui";
import type { Grade } from "../demo/engine/types";
import { Spark, Status } from "./bits";
import { useDesk } from "./ctx";
import { day, money, qty, rate, stamp, STATUS_LABEL, useData, type CustomerDetail, type ItemDetail, type QuoteDetail } from "./data";

/* ---------------------------------------------------------------------------
   Customer
   --------------------------------------------------------------------------- */

type CTab = "overview" | "bills" | "quotes" | "activity";

export function CustomerPanel({ id }: { id: number }) {
  const ctx = useDesk();
  const { data: c } = useData<CustomerDetail>(`/app/customers/${id}`);
  const [tab, setTab] = useState<CTab>("overview");
  const [promise, setPromise] = useState(false);
  if (!c) return <Empty title="Loading…" />;
  const p = c.profile;
  const party = c.party;
  const isSupplier = party.kind === "supplier";
  return (
    <div className="dk-dp">
      <span className="k">{isSupplier ? "Supplier" : "Customer"}{party.since ? ` since ${party.since.slice(0, 4)}` : ""} · {party.area ?? party.city ?? ""} · {party.credit_days} days credit</span>
      <h2>{party.name}</h2>
      <div className="dk-dp-tags">
        {p && <GradeTag g={p.grade as Grade} />}
        {p?.previous_grade && p.previous_grade !== p.grade && <span className="dk-pill warn">was {p.previous_grade}</span>}
        <span className="muted">{party.contact} · {party.phone}{party.email ? ` · ${party.email}` : ""}</span>
      </div>

      {p && (
        <div className="dk-kgrid">
          <div><span>Owes now</span><b className={p.overdue > 1 ? "neg" : ""}>{money(p.outstanding)}</b><small>{p.overdue > 1 ? `${money(p.overdue)} overdue · oldest ${p.oldest} d` : "Nothing overdue"}</small></div>
          <div><span>12-month sales</span><b>{money(p.sales_12m)}</b><small>Last order {day(p.last_order_on)}{p.gap ? ` · usually every ${Math.round(p.gap)} d` : ""}</small></div>
          <div><span>Pays</span><b>{p.avg_days_late < 1 ? "On time" : `${Math.round(p.avg_days_late)} days late`}</b><small>Usually {p.usual_pay_day} days after the bill</small></div>
          <div><span>Credit limit</span><b>{party.credit_limit ? money(party.credit_limit) : "None"}</b><small>Suggested {p.suggested_limit ? money(p.suggested_limit) : "—"}</small></div>
        </div>
      )}

      {!isSupplier && (
        <div className="dk-dp-acts">
          {p && p.outstanding > 1 && (
            <button type="button" className="btn btn-go btn-sm" onClick={() => void ctx.act(() => api.post(`/app/customers/${party.id}/statement`), `Statement link sent to ${party.contact ?? party.name}`)}>
              <ISend /> Send statement
            </button>
          )}
          {p && p.overdue > 1 && !promise && <button type="button" className="btn btn-line btn-sm" onClick={() => setPromise(true)}>Log a promise</button>}
          <button type="button" className="btn btn-line btn-sm" onClick={() => ctx.go("sales", { paste: "", party: String(party.id) })}>New enquiry</button>
          <button type="button" className="btn btn-ghost-d btn-sm" onClick={() => { ctx.drawer(null); ctx.chat("ask", `Tell me about ${party.name}`); }}><IChat size={16} /> Ask about them</button>
        </div>
      )}
      {promise && <PromiseForm partyId={party.id} suggested={p?.overdue} onDone={() => setPromise(false)} />}

      <Tabs<CTab> value={tab} onChange={setTab} items={[
        { id: "overview", label: "Overview" }, { id: "bills", label: "Open bills", count: c.bills.length },
        { id: "quotes", label: "Quotes", count: c.quotes.length }, { id: "activity", label: "Activity", count: c.messages.length + c.promises.length },
      ]} />

      {tab === "overview" && (
        <div className="dk-dp-sec">
          {p && (
            <>
              <h3>Why grade {p.grade}</h3>
              <ul className="dk-reasons">{p.reasons.map((r) => <li key={r} className={/late|overdue|No order|Moved/.test(r) ? "down" : "up"}>{r}</li>)}</ul>
            </>
          )}
          {c.memories.length > 0 && (
            <>
              <h3>What the agents remember</h3>
              <ul className="dk-mini">
                {c.memories.map((m) => (
                  <li key={m.id} className={m.valid_to ? "muted" : ""}>{m.content}{m.valid_to ? ` (until ${day(m.valid_to)})` : ""} <small className="muted">· {m.source}</small></li>
                ))}
              </ul>
            </>
          )}
          <h3>Recent bills and receipts</h3>
          <table className="dk-table compact">
            <tbody>
              {c.vouchers.slice(0, 8).map((v) => (
                <tr key={v.number}><td>{v.type === "sales" ? "Bill" : "Receipt"} {v.number}</td><td>{day(v.date)}</td><td className="r num">{money(v.amount)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {tab === "bills" && (
        c.bills.length ? (
          <table className="dk-table compact">
            <thead><tr><th>Bill</th><th>Date</th><th>Due</th><th className="r">Pending</th><th>Status</th></tr></thead>
            <tbody>
              {c.bills.map((b) => (
                <tr key={b.id}>
                  <td>{b.ref}</td><td>{day(b.date)}</td><td>{day(b.due)}</td><td className="r num">{money(b.pending)}</td>
                  <td className={b.days_late > 0 ? (b.days_late >= 15 ? "bad" : "warn") : "muted"}>{b.days_late > 0 ? `${b.days_late} days late` : "Not due"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <Empty title="No open bills" />
      )}
      {tab === "quotes" && (
        <ul className="dk-list">
          {c.quotes.map((q) => (
            <li key={q.id}>
              <button type="button" className="dk-list-main" onClick={() => ctx.drawer({ type: "quote", id: q.id })}>
                <span><b>{q.number} · {money(q.total)}</b><small>{day(q.created_at)}</small></span>
              </button>
              <Status s={q.status} />
            </li>
          ))}
          {!c.quotes.length && <li className="dk-list-empty">No quotes yet.</li>}
        </ul>
      )}
      {tab === "activity" && (
        <ul className="dk-feed">
          {c.promises.map((x) => (
            <li key={`p${x.id}`}><span><b>Promise</b> {money(x.amount)} for {day(x.due_date)} · {STATUS_LABEL[x.status] ?? x.status}</span></li>
          ))}
          {c.messages.map((m) => (
            <li key={`m${m.id}`}><span><b>{m.purpose}</b> by {m.channel} — {m.body}</span><time>{stamp(m.created_at)}</time></li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function PromiseForm({ partyId, suggested, onDone }: { partyId: number; suggested?: number; onDone: () => void }) {
  const ctx = useDesk();
  const today = ctx.me.business?.now?.slice(0, 10) ?? new Date().toISOString().slice(0, 10);
  const [amount, setAmount] = useState(suggested ? String(Math.round(suggested)) : "");
  const [date, setDate] = useState(() => {
    const d = new Date(today);
    d.setDate(d.getDate() + 3);
    return d.toISOString().slice(0, 10);
  });
  return (
    <form className="op-inline-form" onSubmit={(e) => {
      e.preventDefault();
      void ctx.act(() => api.post("/app/promises", { party_id: partyId, amount: Number(amount), due_date: date, source: "call" }), "Promise logged. Collections will check on the day.").then((r) => r && onDone());
    }}>
      <label><span>They will pay</span><input inputMode="numeric" value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^\d.]/g, ""))} required /></label>
      <label><span>On</span><input type="date" value={date} min={today} onChange={(e) => setDate(e.target.value)} required /></label>
      <button type="submit" className="btn btn-go btn-sm" disabled={!Number(amount)}>Save promise</button>
      <button type="button" className="btn btn-ghost-d btn-sm" onClick={onDone}>Cancel</button>
    </form>
  );
}

/* ---------------------------------------------------------------------------
   Quote
   --------------------------------------------------------------------------- */

export function QuotePanel({ id }: { id: number }) {
  const ctx = useDesk();
  const { data: q, reload } = useData<QuoteDetail>(`/app/quotes/${id}`);
  const [rates, setRates] = useState<Record<number, string>>({});
  useEffect(() => setRates({}), [q?.id]);
  if (!q) return <Empty title="Loading…" />;
  const editable = q.status === "draft" || q.status === "pending_approval";
  const changed = Object.keys(rates).length > 0;
  const save = () =>
    ctx.act(() => api.post<{ status: string; approvals: number[] }>(`/app/quotes/${q.id}/rates`, { rates: Object.fromEntries(Object.entries(rates).map(([k, v]) => [k, Number(v)])) }),
      (r) => (r.approvals.length ? "Sent for the owner's approval." : r.status === "sent" ? "Quote sent to the customer." : "Saved.")).then(() => reload());
  const mark = (outcome: "won" | "lost") => ctx.act(() => api.post(`/app/quotes/${q.id}/outcome`, { outcome }), outcome === "won" ? "Marked won." : "Marked lost.");
  return (
    <div className="dk-dp">
      <span className="k">Quote · {stamp(q.created_at)}</span>
      <h2>{q.number} · {q.party}</h2>
      <div className="dk-dp-tags">
        <Status s={q.status} />
        <span className="muted">Valid till {day(q.valid_until)} · margin {q.margin.toFixed(1)}%</span>
      </div>
      {q.enquiry && (
        <div className="dk-dp-sec">
          <h3>Their enquiry ({q.enquiry.channel.replace("_", " ")}, {stamp(q.enquiry.received_at)})</h3>
          <p className="op-quote-text">“{q.enquiry.text}”</p>
        </div>
      )}
      <table className="dk-table compact">
        <thead><tr><th>Item</th><th className="r">Qty</th><th className="r">Rate</th><th className="r">Last rate</th><th className="r">Margin</th></tr></thead>
        <tbody>
          {q.lines.map((ln) => (
            <tr key={ln.id}>
              <td>{ln.item}</td>
              <td className="r num">{qty(ln.qty, ln.unit)}</td>
              <td className="r num">
                {editable ? (
                  <input className="op-rate" aria-label={`Rate for ${ln.item}`} value={rates[ln.id] ?? String(ln.rate)} onChange={(e) => setRates((r) => ({ ...r, [ln.id]: e.target.value.replace(/[^\d.]/g, "") }))} />
                ) : rate(ln.rate)}
              </td>
              <td className="r num muted">{ln.last_rate ? rate(ln.last_rate) : "—"}</td>
              <td className={`r num ${ln.margin < 3 ? "bad" : ""}`}>{ln.margin.toFixed(1)}%</td>
            </tr>
          ))}
          <tr><td colSpan={3} className="muted">Freight</td><td /><td className="r num">{money(q.freight)}</td></tr>
          <tr><td colSpan={3} className="muted">GST</td><td /><td className="r num">{money(q.tax)}</td></tr>
          <tr><td colSpan={3}><b>Total</b></td><td /><td className="r num"><b>{money(q.total)}</b></td></tr>
        </tbody>
      </table>
      <div className="dk-dp-acts">
        {editable && <button type="button" className="btn btn-go btn-sm" onClick={() => void save()}>{changed ? "Save and send" : "Send"}</button>}
        {["sent", "opened", "negotiating"].includes(q.status) && (
          <>
            <button type="button" className="btn btn-go btn-sm" onClick={() => void mark("won")}>Mark won</button>
            <button type="button" className="btn btn-line btn-sm" onClick={() => void mark("lost")}>Mark lost</button>
          </>
        )}
        <button type="button" className="btn btn-ghost-d btn-sm" onClick={() => ctx.drawer({ type: "customer", id: q.party_id })}>Open customer</button>
      </div>
      <div className="dk-dp-sec">
        <h3>What happened</h3>
        <ul className="dk-feed">
          {q.timeline.map((e, i) => <li key={i}><span><b>{e.type.replace(".", " ")}</b> · {e.source.replace("_", " ")}</span><time>{stamp(e.at)}</time></li>)}
          {q.links.map((l, i) => <li key={`l${i}`}><span><b>Link</b> {l.opened ? `opened ${stamp(l.opened)}` : "not opened yet"}{l.responded ? ` · answered ${stamp(l.responded)}` : ""}</span></li>)}
          {q.messages.map((m) => <li key={m.id}><span><b>{m.purpose}</b> by {m.channel}{m.to ? ` to ${m.to}` : ""} — {m.body}</span><time>{stamp(m.created_at)}</time></li>)}
        </ul>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------------------
   Item
   --------------------------------------------------------------------------- */

export function ItemPanel({ id }: { id: number }) {
  const ctx = useDesk();
  const { data: it } = useData<ItemDetail>(`/app/items/${id}`);
  if (!it) return <Empty title="Loading…" />;
  const m = it.metrics;
  const sale = it.prices.map((p) => p.sale ?? 0).filter(Boolean);
  const buy = it.prices.map((p) => p.purchase ?? 0).filter(Boolean);
  return (
    <div className="dk-dp">
      <span className="k">{it.item.group} · GST {it.item.gst}% · list {rate(it.item.list, it.item.unit)}</span>
      <h2>{it.item.name}</h2>
      <div className="dk-dp-tags">
        {m && <Status s={m.status} />}
        {it.item.aliases.length > 0 && <span className="muted">Customers say: {it.item.aliases.slice(0, 6).join(", ")}</span>}
      </div>
      {m && (
        <div className="dk-kgrid">
          <div><span>In stock</span><b>{qty(m.stock, it.item.unit)}</b><small>{money(m.value)} at cost</small></div>
          <div><span>Sells</span><b>{qty(m.per_day, it.item.unit)}/day</b><small>{qty(m.sold_7d, it.item.unit)} last 7 days</small></div>
          <div><span>Days left</span><b className={m.status === "reorder" ? "neg" : ""}>{m.days_left ?? "—"}</b><small>{m.status === "idle" ? `No sale for ${m.idle_days} days` : "At the last 28 days' pace"}</small></div>
          <div><span>Last 28 days</span><b>{qty(m.sold_28d, it.item.unit)}</b><small>sold</small></div>
        </div>
      )}
      <div className="dk-dp-acts">
        <button type="button" className="btn btn-ghost-d btn-sm" onClick={() => { ctx.drawer(null); ctx.chat("ask", `Stock of ${it.item.name}`); }}><IChat size={16} /> Ask about it</button>
      </div>
      <div className="dk-dp-sec">
        <h3>Selling rate, last 4 months</h3>
        <Spark points={sale} label="Weekly average selling rate" />
        {buy.length > 1 && (<><h3>Buying rate</h3><Spark points={buy} tone="var(--info)" label="Weekly average buying rate" /></>)}
        <h3>Supplier rates</h3>
        <table className="dk-table compact">
          <tbody>
            {it.supplier_quotes.map((s, i) => <tr key={i}><td>{s.supplier}</td><td className="r num">{rate(s.rate)}</td><td>{s.days} days</td><td className="muted">{day(s.received_at)}</td></tr>)}
            {!it.supplier_quotes.length && <tr><td className="muted">No rate requests yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
