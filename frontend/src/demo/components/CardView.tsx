import { quoteTotals } from "../engine/core";
import type { Card, Go } from "../engine/types";
import { money, qty, rate } from "../lib/format";

type Props = { card: Card; onGo: (go: Go) => void };

const STATUS: Record<string, { label: string; tone: string }> = {
  ready: { label: "Inside price band ✓", tone: "good" },
  sent: { label: "Sent to customer", tone: "info" },
  won: { label: "Accepted ✓", tone: "good" },
  held: { label: "On hold", tone: "neutral" },
  waiting: { label: "Waiting for approval", tone: "warn" },
};

export default function CardView({ card, onGo }: Props) {
  switch (card.kind) {
    case "brief":
      return (
        <div className="card">
          <div className="kgrid">
            {card.kpis.map((k) => (
              <div className="kp" key={k.label}>
                <div className="kl">{k.label}</div>
                <div className="kv">{k.value}</div>
                {k.note && <div className={`kn ${k.tone ?? ""}`}>{k.note}</div>}
              </div>
            ))}
          </div>
          <div className="ct" style={{ fontSize: 14, marginTop: 4 }}>Do these first</div>
          <ol className="todo">
            {card.todo.map((t, i) => (
              <li key={t.text}>
                <button type="button" onClick={() => onGo(t.go)}>
                  <span className="n">{i + 1}</span>
                  <span>{t.text}</span>
                  <span className="go" aria-hidden="true">›</span>
                </button>
              </li>
            ))}
          </ol>
        </div>
      );

    case "enquiry":
      return (
        <div className="card">
          <div className="ch">
            <span className="tag info">New enquiry</span>
            <span className="csub">{card.channel}</span>
          </div>
          <div className="ct">{card.customer}</div>
          <div className="draft">{card.text}</div>
          <div className="lines">
            {card.fields.map(([k, v]) => (
              <div className="ln" key={k}>
                <span className="l">{k}</span>
                <span>{v}</span>
              </div>
            ))}
          </div>
        </div>
      );

    case "quote": {
      const t = quoteTotals(card);
      const st = card.status === "ready" && !card.inBand ? { label: "Below margin floor", tone: "bad" } : STATUS[card.status]!;
      return (
        <div className="card">
          <div className="ch">
            <span className="ct" style={{ fontFamily: "var(--display)" }}>Quote {card.no}</span>
            <span className={`tag ${st.tone}`}>{st.label}</span>
          </div>
          <div className="csub">
            {card.customer} · grade {card.grade}
          </div>
          <div className="lines">
            {card.lines.map((l) => (
              <div className="ln" key={l.name}>
                <span>
                  {l.name}
                  <br />
                  <span className="csub num">
                    {qty(l.qty, l.unit)} × {rate(l.rate, l.unit)}
                  </span>
                </span>
                <span>{money(l.qty * l.rate)}</span>
              </div>
            ))}
            <div className="ln">
              <span className="l">Freight</span>
              <span>{money(card.freight)}</span>
            </div>
            <div className="ln">
              <span className="l">GST 18%</span>
              <span>{money(t.gst)}</span>
            </div>
            <div className="ln total">
              <span className="l">Total</span>
              <span className="cbig" style={{ fontSize: 18 }}>{money(t.total)}</span>
            </div>
          </div>
          <div className="why">
            <b>How I priced it</b>
            {card.lastRate && <span>Last rate to this customer {rate(card.lastRate, card.lines[0]!.unit)}</span>}
            <span>
              Margin {card.margin}% · {card.terms}
            </span>
          </div>
        </div>
      );
    }

    case "queue":
      return (
        <div className="card">
          <div className="ch">
            <span className="ct">Today's call list</span>
            <span className="cbig" style={{ fontSize: 17 }}>{money(card.total)}</span>
          </div>
          <div className="csub">Ranked by amount, days late and how each customer usually pays</div>
          <div>
            {card.rows.map((r, i) => (
              <div className="qrow" key={r.name}>
                <span className="rk">{i + 1}</span>
                <div className="mid">
                  <div className="nm">{r.name}</div>
                  <div className="csub">{r.hint}</div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <div className="num" style={{ fontWeight: 800 }}>{money(r.amount)}</div>
                  <span className={`tag ${r.tone}`}>{r.tag}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      );

    case "due":
      return (
        <div className="card">
          <div className="ch">
            <span className="ct">{card.name}</span>
            <span className={`tag ${card.grade === "A" ? "good" : card.grade === "B" ? "neutral" : "warn"}`}>Grade {card.grade}</span>
          </div>
          <div className="cbig">{money(card.amount)}</div>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <span className={`tag ${card.daysLate >= 15 ? "bad" : "warn"}`}>{card.daysLate} day{card.daysLate === 1 ? "" : "s"} late</span>
            <span className="csub">{card.bills} bills</span>
          </div>
          <div style={{ fontSize: 14 }}>{card.habit}</div>
          <div className="draft">
            <span className="csub" style={{ fontWeight: 700 }}>
              Message in {card.language} · goes with a statement link
            </span>
            <br />
            {card.draft}
          </div>
        </div>
      );

    case "reorder": {
      const pctLeft = Math.min(100, (card.daysLeft / 30) * 100);
      return (
        <div className="card">
          <div className="ch">
            <span className="ct">Reorder {card.product}</span>
            <span className="tag bad">{card.daysLeft} days left</span>
          </div>
          <div className="bar">
            <b style={{ width: `${pctLeft}%`, background: "var(--bad)" }} />
          </div>
          <div className="kgrid three">
            <div className="kp"><div className="kl">In stock</div><div className="kv">{qty(card.stock, card.unit)}</div></div>
            <div className="kp"><div className="kl">Sells per day</div><div className="kv">{qty(card.perDay, card.unit)}</div></div>
            <div className="kp"><div className="kl">Buy</div><div className="kv">{qty(card.suggest, card.unit)}</div></div>
          </div>
          <div className="csub">Last 3 buys: {card.lastBuys.map((b) => rate(b, card.unit)).join(" · ")}</div>
        </div>
      );
    }

    case "rates":
      return (
        <div className="card">
          <div className="ct">Rates for {qty(card.qty, card.unit)} {card.product}</div>
          <div className="tbl-wrap">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Supplier</th>
                  <th className="r">Rate</th>
                  <th className="r">Days</th>
                  <th className="r">On time</th>
                </tr>
              </thead>
              <tbody>
                {card.rows.map((r) => (
                  <tr key={r.supplier} className={r.best ? "best" : undefined}>
                    <td>
                      {r.supplier}
                      <span className="csub"> · {r.brand}</span>
                    </td>
                    <td className="r">{rate(r.rate, card.unit)}</td>
                    <td className="r">{r.days}</td>
                    <td className="r">{r.onTime}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="csub">{card.note}</div>
        </div>
      );

    case "idle":
      return (
        <div className="card">
          <div className="ch">
            <span className="ct">Idle stock · {card.product}</span>
            <span className="tag warn">{money(card.value)} locked</span>
          </div>
          <div className="kgrid three">
            <div className="kp"><div className="kl">Stock</div><div className="kv">{qty(card.qty, card.unit)}</div></div>
            <div className="kp"><div className="kl">Your cost</div><div className="kv">{rate(card.cost, card.unit)}</div></div>
            <div className="kp"><div className="kl">Market</div><div className="kv">{rate(card.market, card.unit)}</div></div>
          </div>
          <div style={{ fontSize: 14 }}>
            Not sold in {card.days} days. Offer <b className="num">{rate(card.offer, card.unit)}</b> to past buyers: {card.buyers.join(", ")} and 3 more.
          </div>
        </div>
      );

    case "cashweeks": {
      const max = Math.max(...card.weeks.flatMap((w) => [w.inflow, w.outflow]));
      return (
        <div className="card">
          <div className="ch">
            <span className="ct">Cash, next 4 weeks</span>
          </div>
          <div className="legend">
            <span style={{ ["--c" as string]: "var(--maroon-bar)" }}>Coming in</span>
            <span style={{ ["--c" as string]: "var(--quiet-bar)" }}>Going out</span>
          </div>
          <div className="cash" role="img" aria-label={card.weeks.map((w) => `${w.label}: net ${money(w.inflow - w.outflow)}`).join(", ")}>
            {card.weeks.map((w) => {
              const net = w.inflow - w.outflow;
              return (
                <div className="wk" key={w.label}>
                  <div className="pair">
                    <div className="pi" style={{ height: `${(w.inflow / max) * 100}%` }} title={`In ${money(w.inflow)}`} />
                    <div className="po" style={{ height: `${(w.outflow / max) * 100}%` }} title={`Out ${money(w.outflow)}`} />
                  </div>
                  <span className="csub">{w.label}</span>
                  <span className={`net ${net < 0 ? "neg" : ""}`}>{net < 0 ? "" : "+"}{money(net)}</span>
                </div>
              );
            })}
          </div>
          <div className="csub">Net cash each week</div>
        </div>
      );
    }

    case "alert":
      return (
        <div className={`alert ${card.tone}`}>
          <span className="ai" aria-hidden="true">{card.tone === "good" ? "✓" : card.tone === "info" ? "i" : "!"}</span>
          <div>
            <div className="at">{card.title}</div>
            <div className="ab">{card.body}</div>
          </div>
        </div>
      );

    case "table":
      return (
        <div className="card">
          {card.title && <div className="ct">{card.title}</div>}
          <div className="tbl-wrap">
            <table className="tbl">
              <thead>
                <tr>
                  {card.cols.map((c, i) => (
                    <th key={i} className={card.align?.[i] === "r" ? "r" : undefined}>{c}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {card.rows.map((row, ri) => (
                  <tr key={ri}>
                    {row.map((cell, i) => (
                      <td key={i} className={card.align?.[i] === "r" ? "r" : undefined}>{cell}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {card.footnote && <div className="csub">{card.footnote}</div>}
        </div>
      );

    case "bars": {
      const max = Math.max(...card.bars.map((b) => b.value), 1);
      const min = card.unit === "%" ? Math.min(...card.bars.map((b) => b.value)) * 0.8 : 0;
      return (
        <div className="card">
          <div className="ct">{card.title}</div>
          <div className="chart" role="img" aria-label={card.bars.map((b) => `${b.label} ${b.display}`).join(", ")}>
            {card.bars.map((b, i) => (
              <div className="col" key={`${b.label}${i}`}>
                <span className={`v ${i === card.highlight ? "hi" : ""}`}>{b.display}</span>
                <span className={`b ${i === card.highlight ? "hi" : ""}`} style={{ height: `${Math.max(3, ((b.value - min) / (max - min || 1)) * 85)}%` }} />
                <span className="x">{b.label}</span>
              </div>
            ))}
          </div>
          {card.footnote && <div className="csub">{card.footnote}</div>}
        </div>
      );
    }

    case "kpis":
      return (
        <div className="card">
          {card.title && <div className="ct">{card.title}</div>}
          <div className={`kgrid ${card.kpis.length % 3 === 0 ? "three" : ""}`}>
            {card.kpis.map((k) => (
              <div className="kp" key={k.label}>
                <div className="kl">{k.label}</div>
                <div className="kv" style={k.tone ? { color: `var(--${k.tone})` } : undefined}>{k.value}</div>
                {k.note && <div className="kn">{k.note}</div>}
              </div>
            ))}
          </div>
        </div>
      );

    case "score":
      return (
        <div className="card">
          <div className="ch">
            <span className="ct">{card.name}</span>
            <span className="tag warn">Moved from {card.from} to {card.grade}</span>
          </div>
          <div className="grades" role="img" aria-label={`Grade ${card.grade}, was ${card.from}`}>
            {(["A", "B", "C", "D"] as const).map((g) => (
              <span key={g} className={g === card.grade ? "now" : g === card.from ? "was" : undefined}>{g}</span>
            ))}
          </div>
          <div>
            {card.reasons.map((r) => (
              <div className="reason" key={r.text}>
                <span className={r.up ? "up" : "dn"} aria-hidden="true">{r.up ? "↑" : "↓"}</span>
                <span>{r.text}</span>
              </div>
            ))}
          </div>
          <div className="why">
            <b>Suggested</b>
            <span>{card.suggestion}</span>
          </div>
        </div>
      );

    case "won":
      return (
        <div className="card">
          <div className="ch">
            <span className="tag good">Order won</span>
            <span className="csub">{card.quoteNo}</span>
          </div>
          <div className="ct">{card.customer} accepted</div>
          <div className="cbig">{money(card.amount)}</div>
          <div className="csub">Quoted in {card.minutes} minutes, accepted from their link</div>
          {card.posted && <div className="status">✓ Sales order posted in Tally</div>}
        </div>
      );

    case "po":
      return (
        <div className="card">
          <div className="ch">
            <span className="ct" style={{ fontFamily: "var(--display)" }}>{card.no}</span>
            <span className={`tag ${card.status === "posted" ? "good" : card.status === "waiting" ? "warn" : "neutral"}`}>
              {card.status === "posted" ? "Posted in Tally" : card.status === "waiting" ? "Waiting for approval" : "Draft"}
            </span>
          </div>
          <div className="lines">
            <div className="ln"><span className="l">Supplier</span><span>{card.supplier}</span></div>
            <div className="ln"><span className="l">Item</span><span>{card.product}</span></div>
            <div className="ln"><span className="l">Quantity</span><span>{qty(card.qty, card.unit)}</span></div>
            <div className="ln"><span className="l">Rate</span><span>{rate(card.rate, card.unit)}</span></div>
            <div className="ln total"><span className="l">Total</span><span>{money(card.qty * card.rate)}</span></div>
          </div>
        </div>
      );
  }
}
