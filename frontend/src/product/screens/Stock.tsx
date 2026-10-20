import { useState } from "react";

import { Empty, PageHead, Panel, Tabs } from "../../demo/desk/ui";
import { Status } from "../bits";
import { useDesk } from "../ctx";
import { day, money, qty, rate, stamp, useData, type Stock as Data } from "../data";

type T = "items" | "orders" | "rates";

export default function Stock() {
  const ctx = useDesk();
  const { data } = useData<Data>("/app/stock", 30000);
  const [tab, setTab] = useState<T>("items");
  const [filter, setFilter] = useState<"all" | "reorder" | "watch" | "idle">("all");
  if (!data) return <Empty title="Loading…" />;
  const items = filter === "all" ? data.items : data.items.filter((i) => i.status === filter);
  return (
    <>
      <PageHead title="Stock & Purchase" sub={<>Days of stock from the last 28 days of sales. <b>{data.totals.reorder}</b> to reorder · <b>{money(data.totals.idle)}</b> idle · {money(data.totals.value)} in stock.</>} />
      <Tabs value={tab} onChange={setTab} items={[
        { id: "items", label: "Items", count: data.items.length },
        { id: "orders", label: "Purchase orders", count: data.purchase_orders.filter((p) => p.status === "sent").length },
        { id: "rates", label: "Rate requests", count: data.rfqs.length },
      ]} />
      {tab === "items" && (
        <Panel pad={false}>
          <div className="dk-chips op-pad" role="group" aria-label="Filter">
            {(["all", "reorder", "watch", "idle"] as const).map((f) => (
              <button key={f} type="button" aria-pressed={filter === f} onClick={() => setFilter(f)}>
                {f === "all" ? "All" : f[0]!.toUpperCase() + f.slice(1)} {f !== "all" && `(${data.items.filter((i) => i.status === f).length})`}
              </button>
            ))}
          </div>
          <table className="dk-table">
            <thead><tr><th>Item</th><th>Status</th><th className="r">In stock</th><th className="r">Sells / day</th><th className="r">Days left</th><th className="r">Value</th><th>Last sale</th></tr></thead>
            <tbody>
              {items.map((i) => (
                <tr key={i.item_id} className={i.status === "reorder" ? "short" : ""} onClick={() => ctx.drawer({ type: "item", id: i.item_id })}>
                  <td><b>{i.name}</b><small>{i.group}</small></td>
                  <td><Status s={i.status} /></td>
                  <td className="r num">{qty(i.stock, i.unit)}</td>
                  <td className="r num">{i.per_day ? qty(i.per_day, i.unit) : "—"}</td>
                  <td className={`r num ${i.status === "reorder" ? "bad" : i.status === "watch" ? "warn" : ""}`}>{i.days_left ?? "—"}</td>
                  <td className="r num">{money(i.value)}</td>
                  <td className="muted">{i.status === "idle" ? `${i.idle_days} days ago` : day(i.last_sale_on)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}
      {tab === "orders" && (
        <Panel pad={false}>
          <table className="dk-table">
            <thead><tr><th>PO</th><th>Supplier</th><th>Items</th><th className="r">Total</th><th>Created</th><th>Status</th></tr></thead>
            <tbody>
              {data.purchase_orders.map((p) => (
                <tr key={p.id}>
                  <td><b>{p.number}</b></td><td>{p.supplier}</td>
                  <td>{p.lines.map((l) => `${qty(l.qty, l.unit)} ${l.item} @ ${rate(l.rate)}`).join(", ")}</td>
                  <td className="r num">{money(p.total)}</td><td>{stamp(p.created_at)}</td><td><Status s={p.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}
      {tab === "rates" && (
        <div className="dk-stack">
          {data.rfqs.map((r) => (
            <Panel key={r.id} title={`${r.item} · ${qty(r.qty, r.unit)}`} sub={`Asked ${stamp(r.created_at)} · ${r.quotes.length} rates in`}>
              <table className="dk-table compact">
                <thead><tr><th>Supplier</th><th className="r">Rate</th><th>Delivery</th><th>Received</th></tr></thead>
                <tbody>
                  {r.quotes.map((q, i) => (
                    <tr key={i} className={i === 0 ? "best" : ""}><td>{q.supplier}</td><td className="r num">{rate(q.rate, r.unit)}</td><td>{q.days} days</td><td>{stamp(q.received_at)}</td></tr>
                  ))}
                  {!r.quotes.length && <tr><td className="muted" colSpan={4}>Waiting for suppliers to reply on their links.</td></tr>}
                </tbody>
              </table>
            </Panel>
          ))}
          {!data.rfqs.length && <div className="dk-panel"><Empty title="No open rate requests" sub="The Stock agent asks suppliers when an item drops below your reorder line." /></div>}
        </div>
      )}
    </>
  );
}
