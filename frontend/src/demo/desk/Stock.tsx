import { useState } from "react";
import { askRates, makePo, reorderQty, supplierRates, tapLatest } from "../engine/desk";
import type { Card } from "../engine/types";
import { money, qty, rate } from "../lib/format";
import type { Ctx } from "./ctx";
import { IChat, ISend } from "./icons";
import { stockRows } from "./select";
import { Empty, Meter, PageHead, Panel, Tabs } from "./ui";

type View = "health" | "rates" | "pos" | "idle";

type PoCard = Extract<Card, { kind: "po" }>;

/** Purchase orders the Stock agent has made in this demo, newest first, plus
 *  last week's delivery that it already matched. */
function purchaseOrders(ctx: Ctx) {
  const s = ctx.s;
  const w = s.world;
  const made = s.threads.stock.messages
    .filter((m) => m.card?.kind === "po")
    .map((m) => m.card as PoCard)
    .reverse();
  const p1 = w.products[1]!;
  const s0 = w.suppliers[0]!;
  const older: (PoCard & { received: string })[] = [
    { kind: "po", no: "PO-0871", supplier: s0.name, product: p1.name, qty: Math.round(p1.perDay * 25), unit: p1.unit, rate: p1.lastBuys[0]!, status: "posted", received: "Received · quantity and rate match the bill" },
  ];
  return { made, older };
}

export default function Stock({ ctx }: { ctx: Ctx }) {
  const s = ctx.s;
  const w = s.world;
  const rows = stockRows(s);
  const atRisk = rows.filter((r) => r.status === "reorder");
  const [view, setView] = useState<View>("health");
  const [pick, setPick] = useState(atRisk[0]?.i ?? 0);
  const pos = purchaseOrders(ctx);
  const waitingPos = s.approvals.filter((a) => a.type === "Purchase order" && a.status === "waiting").length;

  const reorderAll = () => {
    for (const r of atRisk) {
      const best = supplierRates(ctx.s, r.i).find((x) => x.best)!;
      ctx.run(makePo(ctx.s, r.i, best.idx));
    }
    ctx.toast(`${atRisk.length} PO${atRisk.length === 1 ? "" : "s"} drafted at the best rate`);
  };

  return (
    <>
      <PageHead title="Stock & Purchase" sub="What should we buy, from whom, and what is sitting idle?">
        <button type="button" className="btn btn-go btn-sm" disabled={!atRisk.length} onClick={reorderAll}>
          Reorder items at risk ({atRisk.length})
        </button>
      </PageHead>

      <div className="dk-stats">
        <div><span>Stock value</span><b>{money(w.kpi.stockValue)}</b><small>{w.products.length} main items</small></div>
        <div><span>Items at risk</span><b className={atRisk.length ? "neg" : ""}>{atRisk.length}</b><small>Under {s.desk.rules.reorderDays} days of stock</small></div>
        <div><span>Stuck in idle stock</span><b>{money(w.kpi.idleValue)}</b><small>Unsold 60+ days</small></div>
        <div><span>To suppliers, 30 days</span><b>{money(w.kpi.payables30)}</b><small>{w.kpi.payablesCount} suppliers</small></div>
        <div><span>POs waiting for you</span><b>{waitingPos}</b><small>Above {w.team.purchase}'s {money(w.limits.poLimit)} limit</small></div>
      </div>

      <div className="dk-bar">
        <Tabs<View>
          value={view}
          onChange={setView}
          items={[
            { id: "health", label: "Stock health", count: rows.length },
            { id: "rates", label: "Compare rates" },
            { id: "pos", label: "Purchase orders", count: pos.made.length + pos.older.length },
            { id: "idle", label: "Idle stock", count: rows.filter((r) => r.status === "idle").length },
          ]}
        />
      </div>

      {view === "health" && (
        <Panel pad={false}>
          <table className="dk-table">
            <thead>
              <tr>
                <th>Item</th><th className="r">In stock</th><th className="r">Sells a day</th><th>Days left</th><th className="r">Reorder at</th><th className="r">Value</th><th>Status</th><th />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.i} onClick={() => ctx.drawer({ type: "product", idx: r.i })}>
                  <td><b>{r.p.name}</b><small>Last bought at {rate(r.p.lastBuys[0]!, r.p.unit)}</small></td>
                  <td className="r num">{qty(r.p.stock, r.p.unit)}</td>
                  <td className="r num">{r.status === "idle" ? "—" : qty(r.p.perDay, r.p.unit)}</td>
                  <td>{r.status === "idle" ? <span className="muted">No sale in 100 days</span> : <span className="dk-late"><Meter value={r.days} max={45} tone={r.status === "reorder" ? "bad" : r.status === "watch" ? "warn" : "good"} /><span>{r.days} d</span></span>}</td>
                  <td className="r num">{r.status === "idle" ? "—" : qty(Math.round(r.p.perDay * s.desk.rules.reorderDays), r.p.unit)}</td>
                  <td className="r num">{money(r.value)}</td>
                  <td><span className={`dk-status s-${r.status}`}>{r.status === "reorder" ? "Reorder now" : r.status === "watch" ? "Watch" : r.status === "idle" ? "Idle" : "OK"}</span></td>
                  <td className="r" onClick={(e) => e.stopPropagation()}>
                    {r.status === "reorder" && (
                      <button type="button" className="btn btn-go btn-xs" onClick={() => { setPick(r.i); setView("rates"); }}>Compare rates</button>
                    )}
                    {r.status === "idle" && (
                      <button type="button" className="btn btn-line btn-xs" onClick={() => setView("idle")}>See offer</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}

      {view === "rates" && <Rates ctx={ctx} pick={pick} setPick={setPick} />}

      {view === "pos" && (
        <Panel pad={false} title="Purchase orders" sub="Every PO goes to Tally only after it is approved">
          <table className="dk-table">
            <thead><tr><th>PO</th><th>Supplier</th><th>Item</th><th className="r">Value</th><th>Status</th></tr></thead>
            <tbody>
              {pos.made.map((p) => (
                <tr key={p.no}>
                  <td><b>{p.no}</b></td>
                  <td>{p.supplier}</td>
                  <td>{qty(p.qty, p.unit)} {p.product}<small>{rate(p.rate, p.unit)}</small></td>
                  <td className="r num">{money(p.qty * p.rate)}</td>
                  <td>{p.status === "waiting" ? <span className="dk-status s-watch">Waiting for approval</span> : <span className="dk-status s-ok">Sent · in Tally</span>}</td>
                </tr>
              ))}
              {pos.older.map((p) => (
                <tr key={p.no}>
                  <td><b>{p.no}</b></td>
                  <td>{p.supplier}</td>
                  <td>{qty(p.qty, p.unit)} {p.product}<small>{rate(p.rate, p.unit)}</small></td>
                  <td className="r num">{money(p.qty * p.rate)}</td>
                  <td><span className="dk-status s-ok">{p.received}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
          {!pos.made.length && <p className="dk-fine">New POs you make from Stock health or Compare rates show up here.</p>}
        </Panel>
      )}

      {view === "idle" && <Idle ctx={ctx} />}
    </>
  );
}

function Rates({ ctx, pick, setPick }: { ctx: Ctx; pick: number; setPick: (i: number) => void }) {
  const s = ctx.s;
  const w = s.world;
  const rows = stockRows(s).filter((r) => r.status !== "idle");
  const p = w.products[pick]!;
  const list = supplierRates(s, pick);
  const q = reorderQty(s, pick);
  const best = list.find((x) => x.best)!;
  const worst = Math.max(...list.map((x) => x.rate));
  return (
    <div className="dk-grid2 wide-l">
      <Panel
        title={`Supplier rates · ${p.name}`}
        sub={`For ${qty(q, p.unit)} (30 days of sales) · from each supplier's last rate and today's market`}
        right={<button type="button" className="btn btn-line btn-sm" onClick={() => ctx.run(askRates(ctx.s, pick))}><ISend /> Ask today's rates</button>}
        pad={false}
      >
        <div className="dk-filters">
          <div className="dk-chips" role="group" aria-label="Item">
            {rows.map((r) => (
              <button key={r.i} type="button" aria-pressed={pick === r.i} onClick={() => setPick(r.i)}>{r.short}</button>
            ))}
          </div>
        </div>
        <table className="dk-table">
          <thead><tr><th>Supplier</th><th className="r">Rate</th><th className="r">Order value</th><th className="r">Delivers in</th><th className="r">On time</th><th /></tr></thead>
          <tbody>
            {list.map((r) => (
              <tr key={r.idx} className={r.best ? "best" : ""}>
                <td><b>{r.supplier}</b><small>{r.brand}{r.best ? " · best value" : ""}</small></td>
                <td className="r num">{rate(r.rate, p.unit)}</td>
                <td className="r num">{money(r.rate * q)}</td>
                <td className="r num">{r.days} days</td>
                <td className={`r num ${r.onTime < 90 ? "warn" : ""}`}>{r.onTime}%</td>
                <td className="r">
                  <button type="button" className={`btn ${r.best ? "btn-go" : "btn-line"} btn-xs`} onClick={() => ctx.run(makePo(ctx.s, pick, r.idx))}>Make PO</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
      <Panel title="Why this supplier">
        <p className="dk-sugg">
          <b>{best.supplier}</b> is {rate(worst - best.rate, p.unit)} cheaper than the costliest quote and delivers on time {best.onTime}% of the time. On {qty(q, p.unit)} that saves {money((worst - best.rate) * q)}.
        </p>
        <ul className="dk-reasons">
          <li className="up">Cheapest supplier with 90%+ on-time delivery</li>
          <li>Your last buy: {rate(p.lastBuys[0]!, p.unit)} · before that {rate(p.lastBuys[1] ?? p.lastBuys[0]!, p.unit)}</li>
          <li className={best.rate * q > w.limits.poLimit ? "down" : "up"}>
            {best.rate * q > w.limits.poLimit ? `Above ${w.team.purchase}'s ${money(w.limits.poLimit)} limit — goes to you for approval` : `Inside ${w.team.purchase}'s ${money(w.limits.poLimit)} limit — goes straight to the supplier`}
          </li>
        </ul>
      </Panel>
    </div>
  );
}

function Idle({ ctx }: { ctx: Ctx }) {
  const s = ctx.s;
  const w = s.world;
  const msg = [...s.threads.stock.messages].reverse().find((m) => m.card?.kind === "idle");
  const card = msg?.card?.kind === "idle" ? msg.card : null;
  if (!card) return <Empty title="Nothing idle." />;
  const sent = !!msg?.chosen;
  return (
    <div className="dk-grid2 wide-l">
      <Panel title={`${card.product} · ${card.days} days without a sale`} sub={`${qty(card.qty, card.unit)} worth ${money(card.value)} at cost`}>
        <div className="dk-kgrid four">
          <div><span>Your cost</span><b>{rate(card.cost, card.unit)}</b></div>
          <div><span>Market today</span><b>{rate(card.market, card.unit)}</b></div>
          <div><span>Suggested offer</span><b className="pos">{rate(card.offer, card.unit)}</b><small>2% over cost</small></div>
          <div><span>Cash it frees</span><b>{money(card.qty * card.offer)}</b><small>If all of it sells</small></div>
        </div>
        <h3 className="dk-h3">Likely buyers — they bought it before</h3>
        <ul className="dk-list">
          {card.buyers.map((b) => {
            const c = w.customers.find((x) => x.name === b);
            return (
              <li key={b}>
                <button type="button" className="dk-list-main" onClick={() => c && ctx.drawer({ type: "customer", id: c.id })}>
                  <span><b>{b}</b><small>{c ? `Last order ${c.lastBuyDays} days ago · grade ${c.grade}` : ""}</small></span>
                </button>
              </li>
            );
          })}
        </ul>
        <div className="dk-dp-acts">
          <button type="button" className="btn btn-go btn-sm" disabled={sent} onClick={() => { ctx.run(tapLatest(ctx.s, "stock", "send-offer")); ctx.toast("Offer sent to 6 past buyers"); }}>
            <ISend /> {sent ? "Offer sent" : "Send offer to 6 past buyers"}
          </button>
          <button type="button" className="btn btn-ghost-d btn-sm" onClick={() => ctx.chat("stock")}><IChat size={16} /> Change the price in chat</button>
        </div>
      </Panel>
      <Panel title="How it works">
        <ul className="dk-reasons">
          <li>Each buyer gets a link with the offer price, valid 3 days</li>
          <li>Replies come to the Stock chat and to Inbox</li>
          <li>Booking an order posts the sales order to Tally after your yes</li>
        </ul>
      </Panel>
    </div>
  );
}

/* ---------------------------------------------------------------------------
   Drawer: one item
   --------------------------------------------------------------------------- */

export function ProductPanel({ ctx, idx }: { ctx: Ctx; idx: number }) {
  const s = ctx.s;
  const r = stockRows(s).find((x) => x.i === idx)!;
  const p = r.p;
  const best = supplierRates(s, idx).find((x) => x.best)!;
  const q = reorderQty(s, idx);
  const idle = r.status === "idle";
  return (
    <div className="dk-dp">
      <span className="k">Item · from Tally</span>
      <h2>{p.name}</h2>
      <div className="dk-dp-tags">
        <span className={`dk-status s-${r.status}`}>{r.status === "reorder" ? "Reorder now" : r.status === "watch" ? "Watch" : idle ? "Idle" : "OK"}</span>
        <span className="muted">Also called: {p.alias.join(", ")}</span>
      </div>
      <div className="dk-kgrid">
        <div><span>In stock</span><b>{qty(p.stock, p.unit)}</b><small>{money(r.value)} at cost</small></div>
        <div><span>Days left</span><b className={r.status === "reorder" ? "neg" : ""}>{idle ? "—" : `${r.days} days`}</b><small>{idle ? "No sale in 100 days" : `Sells ${qty(p.perDay, p.unit)} a day`}</small></div>
        <div><span>Selling rate</span><b>{rate(p.rate, p.unit)}</b><small>Cost {rate(p.cost, p.unit)}</small></div>
        <div><span>Margin</span><b>{(((p.rate - p.cost) / p.rate) * 100).toFixed(1)}%</b><small>Last buys {p.lastBuys.slice(0, 3).map((x) => rate(x, p.unit)).join(", ")}</small></div>
      </div>
      {!idle && (
        <>
          <div className="dk-dp-sec">
            <h3>Agent's suggestion</h3>
            <p className="dk-sugg">
              Order {qty(q, p.unit)} from <b>{best.supplier}</b> at {rate(best.rate, p.unit)} ({money(best.rate * q)}). That covers 30 days of sales; it arrives in {best.days} days.
            </p>
          </div>
          <div className="dk-dp-acts">
            <button type="button" className="btn btn-go btn-sm" onClick={() => ctx.run(makePo(ctx.s, idx, best.idx))}>Make PO from {best.brand}</button>
            <button type="button" className="btn btn-line btn-sm" onClick={() => { ctx.drawer(null); ctx.go("stock"); }}>Compare all rates</button>
            <button type="button" className="btn btn-ghost-d btn-sm" onClick={() => { ctx.drawer(null); ctx.chat("ask", `Stock of ${p.name}`); }}><IChat size={16} /> Ask about it</button>
          </div>
        </>
      )}
      {idle && (
        <div className="dk-dp-acts">
          <button type="button" className="btn btn-go btn-sm" onClick={() => { ctx.drawer(null); ctx.go("stock"); }}>See the offer plan</button>
        </div>
      )}
    </div>
  );
}
