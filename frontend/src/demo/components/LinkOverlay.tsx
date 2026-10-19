import { useEffect, useState, type ReactNode } from "react";
import { customerById, quoteTotals, type QuoteCard } from "../engine/core";
import type { DemoState, UiEffect } from "../engine/types";
import { addDays, dayDate, inr, money, qty, rate, shortDate } from "../lib/format";
import { IconLock } from "./Icons";

export type LinkView = Extract<UiEffect, { type: "customerQuote" | "customerStatement" | "supplierRate" }>;

type Props = {
  view: LinkView;
  state: DemoState;
  onClose: () => void;
  onAcceptQuote: (thread: LinkView & { type: "customerQuote" }) => void;
  onPromise: (customerId: string, amount: number, date: string) => void;
  onSupplierRate: (supplier: string, value: number) => void;
};

function Frame({ url, who, children, onClose }: { url: string; who: string; children: ReactNode; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="overlay" role="dialog" aria-modal="true" aria-label={`${who} view`} onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", maxHeight: "100%" }}>
        <div className="phone">
          <div className="phone-screen">
            <div className="urlbar">
              <IconLock />
              <span>{url}</span>
              <b>{who}</b>
            </div>
            <div className="pbody">{children}</div>
          </div>
        </div>
        <div className="overlay-note">This is what your {who.toLowerCase().replace("'s phone", "")} sees. No app or login needed.</div>
        <button type="button" className="btn btn-ghost btn-sm overlay-close" onClick={onClose}>Back to Oprisa</button>
      </div>
    </div>
  );
}

export default function LinkOverlay({ view, state, onClose, onAcceptQuote, onPromise, onSupplierRate }: Props) {
  const w = state.world;
  const [done, setDone] = useState(false);
  const [pickDate, setPickDate] = useState(0);
  const [pickAmt, setPickAmt] = useState(1);
  const [supRate, setSupRate] = useState("");

  if (view.type === "customerQuote") {
    const q = state.threads[view.thread].messages.find((m) => m.id === view.msgId)?.card as QuoteCard | undefined;
    if (!q) return null;
    const t = quoteTotals(q);
    const accepted = done || q.status === "won";
    return (
      <Frame url={`oprisa.link/q/${q.no.replace("Q-", "")}`} who="Customer's phone" onClose={onClose}>
        <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
          <div style={{ width: 46, height: 46, borderRadius: 12, background: "#f1dcd0", color: "#6d1a17", fontWeight: 900, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "var(--display)" }}>
            {w.biz.company.slice(0, 1).toUpperCase()}
          </div>
          <div>
            <div style={{ fontWeight: 800, fontSize: 17 }}>{w.biz.company}</div>
            <div className="csub">{w.pack.label} · {w.biz.city}</div>
          </div>
        </div>
        <div className="pcard">
          <div className="csub">Quotation for {q.customer}</div>
          <div className="ch" style={{ marginTop: 2 }}>
            <span style={{ fontFamily: "var(--display)", fontWeight: 800, fontSize: 19 }}>{q.no}</span>
            <span className="tag warn">Valid till {shortDate(addDays(w.today, 2))}</span>
          </div>
          <div className="lines" style={{ marginTop: 6 }}>
            {q.lines.map((l) => (
              <div className="ln" key={l.name}>
                <span>{l.name}<br /><span className="csub num">{qty(l.qty, l.unit)} × {rate(l.rate, l.unit)}</span></span>
                <span>{inr(l.qty * l.rate)}</span>
              </div>
            ))}
            <div className="ln"><span className="l">Freight</span><span>{inr(q.freight)}</span></div>
            <div className="ln"><span className="l">GST 18%</span><span>{inr(t.gst)}</span></div>
            <div className="ln total"><span className="l">Total</span><span style={{ fontFamily: "var(--display)" }}>{inr(t.total)}</span></div>
          </div>
          <div className="csub" style={{ marginTop: 6 }}>{q.terms} · 30 days credit</div>
        </div>
        {!accepted ? (
          <>
            <button type="button" className="pbtn" onClick={() => { setDone(true); onAcceptQuote(view); }}>Accept quote</button>
            <div style={{ display: "flex", gap: 10 }}>
              <button type="button" className="pbtn2" style={{ flex: 1 }}>Ask for a change</button>
              <button type="button" className="pbtn2" style={{ flex: 1 }}>Call {w.team.sales[0]}</button>
            </div>
          </>
        ) : (
          <div className="done">
            <b>Accepted. Thank you!</b>
            {w.team.sales[0]} will confirm the dispatch date today.
          </div>
        )}
        <div className="csub" style={{ textAlign: "center" }}>Download PDF · Powered by Oprisa</div>
      </Frame>
    );
  }

  if (view.type === "customerStatement") {
    const c = customerById(w, view.customerId);
    const dates = [3, 6, 10].map((n) => dayDate(addDays(w.today, n)));
    const amounts = [c.outstanding, Math.round(c.outstanding / 2 / 1e4) * 1e4];
    return (
      <Frame url={`oprisa.link/s/${c.id}${c.name.split(" ")[0]!.toLowerCase()}`} who="Customer's phone" onClose={onClose}>
        <div>
          <div className="csub">Statement from {w.biz.company}</div>
          <div style={{ fontFamily: "var(--display)", fontWeight: 800, fontSize: 19 }}>{c.name}</div>
        </div>
        <div className="pcard">
          <div className="lines">
            {c.bills.map((b) => (
              <div className="ln" key={b.no}>
                <span>{b.no} · {shortDate(b.date)}<br /><span className="csub">{b.daysLate > 0 ? `${b.daysLate} day${b.daysLate === 1 ? "" : "s"} overdue` : b.daysLate === 0 ? "due today" : `due in ${-b.daysLate} day${b.daysLate === -1 ? "" : "s"}`}</span></span>
                <span>{inr(b.amount)}</span>
              </div>
            ))}
            <div className="ln total"><span className="l">Total due</span><span style={{ fontFamily: "var(--display)" }}>{inr(c.outstanding)}</span></div>
          </div>
        </div>
        {!done ? (
          <>
            <div style={{ fontWeight: 800 }}>When can you pay?</div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {dates.map((d, i) => (
                <button key={d} type="button" className="opt" aria-pressed={pickDate === i} onClick={() => setPickDate(i)}>{d}</button>
              ))}
            </div>
            <div style={{ fontWeight: 800 }}>How much?</div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {amounts.map((a, i) => (
                <button key={a} type="button" className="opt" aria-pressed={pickAmt === i} onClick={() => setPickAmt(i)}>{money(a)}{i === 0 ? " (full)" : ""}</button>
              ))}
            </div>
            <button
              type="button"
              className="pbtn"
              onClick={() => {
                setDone(true);
                onPromise(c.id, amounts[pickAmt]!, dates[pickDate]!);
              }}
            >
              Confirm {money(amounts[pickAmt]!)} on {dates[pickDate]}
            </button>
          </>
        ) : (
          <div className="done">
            <b>Thank you, noted</b>
            {money(amounts[pickAmt]!)} on {dates[pickDate]}. We'll remind you the day before.
          </div>
        )}
        <div className="csub" style={{ textAlign: "center" }}>Pay by bank transfer or cheque as usual · Powered by Oprisa</div>
      </Frame>
    );
  }

  // Supplier's rate page
  const p = w.products.find((x) => x.name === view.product) ?? w.products[0]!;
  const s = w.suppliers[0]!;
  const q = Math.round(p.perDay * 30);
  return (
    <Frame url="oprisa.link/r/5521" who="Supplier's phone" onClose={onClose}>
      <div>
        <div className="csub">Rate request from {w.biz.company}</div>
        <div style={{ fontFamily: "var(--display)", fontWeight: 800, fontSize: 19 }}>{s.name}</div>
      </div>
      <div className="pcard">
        <div className="lines">
          <div className="ln"><span className="l">Item</span><b>{p.name}</b></div>
          <div className="ln"><span className="l">Quantity</span><b>{qty(q, p.unit)}</b></div>
          <div className="ln"><span className="l">Deliver to</span><b>{w.biz.city} godown</b></div>
          <div className="ln"><span className="l">Needed by</span><b>{shortDate(addDays(w.today, 7))}</b></div>
        </div>
      </div>
      {!done ? (
        <form
          style={{ display: "flex", flexDirection: "column", gap: 12 }}
          onSubmit={(e) => {
            e.preventDefault();
            const v = Number(supRate.replace(/[^\d.]/g, "")) || p.lastBuys[0]!;
            setDone(true);
            onSupplierRate(s.name, v);
          }}
        >
          <div className="field">
            <label htmlFor="suprate" style={{ fontWeight: 700, fontSize: 14 }}>Your rate per {p.unit} (₹, before GST)</label>
            <input id="suprate" inputMode="decimal" placeholder={String(Math.round(p.lastBuys[0]!))} value={supRate} onChange={(e) => setSupRate(e.target.value)} />
          </div>
          <button type="submit" className="pbtn">Send my rate</button>
        </form>
      ) : (
        <div className="done">
          <b>Rate sent</b>
          You'll hear back today.
        </div>
      )}
      <div className="csub" style={{ textAlign: "center" }}>No login needed · Powered by Oprisa</div>
    </Frame>
  );
}
