import { useEffect, useState, type ReactNode } from "react";
import { useParams } from "react-router-dom";

import { api } from "../api/client";
import "../demo/demo.css";
import "./product.css";
import { day, inr, money, qty, rate } from "./data";

/* ---------------------------------------------------------------------------
   /l/:token - what a customer or supplier opens from a message.
   No login: the token is the credential. One page per purpose: a quote to
   accept, a statement or early-payment request to pick a date on, a rate
   request to answer, an offer, a purchase order to confirm.
   --------------------------------------------------------------------------- */

type Line = { item: string; qty: number; unit: string; rate: number };
interface View {
  purpose: "quote" | "statement" | "early_pay" | "rfq" | "offer" | "po";
  company: string; party: string; contact: string; expired: boolean; responded: boolean; response: Record<string, any> | null;
  quote?: { number: string; status: string; valid_until: string | null; total: number; subtotal: number; tax: number; freight: number; lines: Line[]; credit_days: number };
  statement?: { total: number; overdue: number; bills: { ref: string; date: string; due: string; amount: number; days_late: number }[]; dates: string[] };
  rfq?: { item: string; unit: string; qty: number; status: string; city: string | null };
  offer?: { item: string; unit: string; price: number; list: number; available: number | null };
  po?: { number: string; status: string; total: number; lines: Line[] };
}

export default function LinkPage() {
  const { token = "" } = useParams();
  const [v, setV] = useState<View | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);

  useEffect(() => {
    api.get<View>(`/links/${token}`).then(setV).catch((e: Error) => setErr(e.message || "This link is not valid."));
  }, [token]);
  useEffect(() => {
    document.title = v ? `${v.company} · ${TITLE[v.purpose]}` : "Oprisa";
  }, [v]);

  const send = async (body: Record<string, unknown>, thanks: string) => {
    setBusy(true);
    setErr(null);
    try {
      await api.post(`/links/${token}`, body);
      setDone(thanks);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="odemo">
      <div className="op-link">
        <div className="phone-screen">
          <div className="pbody">
            {!v && !err && <div className="csub">Opening…</div>}
            {!v && err && <div className="pcard"><b>{err}</b><div className="csub">Please ask the sender for a new link.</div></div>}
            {v && (
              <>
                <div>
                  <div className="csub">{TITLE[v.purpose]} from {v.company}</div>
                  <div className="op-link-name">{v.party}</div>
                </div>
                <Body v={v} busy={busy} done={done} send={send} />
                {err && <div className="op-link-err" role="alert">{err}</div>}
              </>
            )}
            <div className="csub op-center">No login needed · Powered by Oprisa</div>
          </div>
        </div>
      </div>
    </div>
  );
}

const TITLE: Record<View["purpose"], string> = {
  quote: "Quotation", statement: "Statement", early_pay: "Payment request", rfq: "Rate request", offer: "Stock offer", po: "Purchase order",
};

type BodyProps = { v: View; busy: boolean; done: string | null; send: (b: Record<string, unknown>, thanks: string) => Promise<void> };

function Body({ v, busy, done, send }: BodyProps) {
  const closed = v.expired ? "This link has expired. Please ask us for a new one." : null;
  const answered = done ?? (v.responded ? earlier(v) : null);
  const finish = answered ? <div className="done"><b>Thank you</b>{answered}</div> : closed ? <div className="pcard"><b>{closed}</b></div> : null;

  if (v.purpose === "quote" && v.quote) return <QuoteBody v={v} q={v.quote} finish={finish} busy={busy} send={send} />;
  if ((v.purpose === "statement" || v.purpose === "early_pay") && v.statement) return <StatementBody v={v} s={v.statement} finish={finish} busy={busy} send={send} />;
  if (v.purpose === "rfq" && v.rfq) return <RfqBody r={v.rfq} finish={finish} busy={busy} send={send} />;
  if (v.purpose === "offer" && v.offer) return <OfferBody o={v.offer} finish={finish} busy={busy} send={send} />;
  if (v.purpose === "po" && v.po) {
    return (
      <>
        <div className="pcard">
          <div className="ch">{v.po.number}</div>
          <Lines lines={v.po.lines} />
          <div className="ln total"><span className="l">Total</span><span className="op-link-total">{inr(v.po.total)}</span></div>
        </div>
        {finish ?? <button type="button" className="pbtn" disabled={busy} onClick={() => void send({ action: "confirm" }, "Order confirmed. We'll expect delivery as agreed.")}>Confirm this order</button>}
      </>
    );
  }
  return <div className="pcard">Nothing to show.</div>;
}

function earlier(v: View): string {
  const r = v.response ?? {};
  if (r.action === "accept") return "You accepted this quote. We'll be in touch about dispatch.";
  if (r.action === "decline") return "You declined this quote.";
  if (r.action === "change") return "We have your request and will send a revised quote.";
  if (r.action === "promise") return `You said you'll pay ${money(Number(r.amount))} on ${day(r.due)}.`;
  if (r.rate) return `You sent a rate of ${rate(Number(r.rate))}.`;
  if (r.qty) return `You asked for ${r.qty}. We'll confirm shortly.`;
  return "We have your answer.";
}

function Lines({ lines }: { lines: Line[] }) {
  return (
    <div className="lines">
      {lines.map((l, i) => (
        <div className="ln" key={i}>
          <span>{l.item}<br /><span className="csub num">{qty(l.qty, l.unit)} × {rate(l.rate, l.unit)}</span></span>
          <span>{inr(l.qty * l.rate)}</span>
        </div>
      ))}
    </div>
  );
}

function QuoteBody({ v, q, finish, busy, send }: { v: View; q: NonNullable<View["quote"]>; finish: ReactNode; busy: boolean; send: BodyProps["send"] }) {
  const [mode, setMode] = useState<"" | "change" | "decline">("");
  const [note, setNote] = useState("");
  const settled = ["won", "lost", "expired"].includes(q.status);
  return (
    <>
      <div className="pcard">
        <div className="ch">
          <span>{q.number}</span>
          {q.valid_until && <span className="tag warn">Valid till {day(q.valid_until)}</span>}
        </div>
        <Lines lines={q.lines} />
        <div className="lines">
          {q.freight > 0 && <div className="ln"><span className="l">Freight</span><span>{inr(q.freight)}</span></div>}
          <div className="ln"><span className="l">GST</span><span>{inr(q.tax)}</span></div>
          <div className="ln total"><span className="l">Total</span><span className="op-link-total">{inr(q.total)}</span></div>
        </div>
        <div className="csub">{q.credit_days ? `${q.credit_days} days credit` : "Payment on delivery"}{v.contact ? ` · for ${v.contact}` : ""}</div>
      </div>
      {finish ?? (settled ? <div className="pcard">This quote is {q.status}.</div> : mode === "" ? (
        <>
          <button type="button" className="pbtn" disabled={busy} onClick={() => void send({ action: "accept" }, "Quote accepted. We'll confirm dispatch shortly.")}>Accept quote</button>
          <div className="op-row">
            <button type="button" className="pbtn2" onClick={() => setMode("change")}>Ask for a change</button>
            <button type="button" className="pbtn2" onClick={() => setMode("decline")}>Not now</button>
          </div>
        </>
      ) : (
        <form className="op-link-form" onSubmit={(e) => {
          e.preventDefault();
          void send(mode === "change" ? { action: "change", note } : { action: "decline", reason: note },
            mode === "change" ? "We'll send you a revised quote." : "Noted. Thank you for letting us know.");
        }}>
          <div className="field">
            <label htmlFor="note">{mode === "change" ? "What should we change? (rate, quantity, delivery)" : "Any reason? (optional)"}</label>
            <input id="note" value={note} onChange={(e) => setNote(e.target.value)} autoFocus />
          </div>
          <button type="submit" className="pbtn" disabled={busy || (mode === "change" && !note.trim())}>{mode === "change" ? "Send request" : "Decline quote"}</button>
          <button type="button" className="pbtn2" onClick={() => setMode("")}>Back</button>
        </form>
      ))}
    </>
  );
}

function StatementBody({ v, s, finish, busy, send }: { v: View; s: NonNullable<View["statement"]>; finish: ReactNode; busy: boolean; send: BodyProps["send"] }) {
  const amounts = [...new Set([s.total, s.overdue > 1 && s.overdue < s.total ? s.overdue : 0, Math.round(s.total / 2 / 1e3) * 1e3].filter((x) => x > 0))];
  const [d, setD] = useState(0);
  const [a, setA] = useState(0);
  return (
    <>
      {v.purpose === "early_pay" && (
        <div className="pcard">We'd be grateful if you could clear some of this a little early this month. Pick whatever works for you.</div>
      )}
      <div className="pcard">
        <div className="lines">
          {s.bills.map((b) => (
            <div className="ln" key={b.ref}>
              <span>{b.ref} · {day(b.date)}<br /><span className="csub">{b.days_late > 0 ? `${b.days_late} day${b.days_late === 1 ? "" : "s"} overdue` : `due ${day(b.due)}`}</span></span>
              <span>{inr(b.amount)}</span>
            </div>
          ))}
          <div className="ln total"><span className="l">Total due</span><span className="op-link-total">{inr(s.total)}</span></div>
        </div>
      </div>
      {finish ?? (
        <>
          <b>When can you pay?</b>
          <div className="op-opts">
            {s.dates.slice(0, 5).map((x, i) => <button key={x} type="button" className="opt" aria-pressed={d === i} onClick={() => setD(i)}>{day(x)}</button>)}
          </div>
          <b>How much?</b>
          <div className="op-opts">
            {amounts.map((x, i) => <button key={x} type="button" className="opt" aria-pressed={a === i} onClick={() => setA(i)}>{money(x)}{i === 0 ? " (full)" : ""}</button>)}
          </div>
          <button type="button" className="pbtn" disabled={busy || !amounts.length}
            onClick={() => void send({ action: "promise", date: s.dates[d], amount: amounts[a] }, `${money(amounts[a]!)} on ${day(s.dates[d])}. We'll remind you the day before.`)}>
            Confirm {money(amounts[a] ?? 0)} on {day(s.dates[d])}
          </button>
        </>
      )}
      <div className="csub op-center">Pay by bank transfer or cheque as usual.</div>
    </>
  );
}

function RfqBody({ r, finish, busy, send }: { r: NonNullable<View["rfq"]>; finish: ReactNode; busy: boolean; send: BodyProps["send"] }) {
  const [val, setVal] = useState("");
  const [days, setDays] = useState("3");
  return (
    <>
      <div className="pcard">
        <div className="lines">
          <div className="ln"><span className="l">Item</span><b>{r.item}</b></div>
          <div className="ln"><span className="l">Quantity</span><b>{qty(r.qty, r.unit)}</b></div>
          {r.city && <div className="ln"><span className="l">Deliver to</span><b>{r.city} godown</b></div>}
        </div>
      </div>
      {finish ?? (r.status === "closed" ? <div className="pcard">This request is closed. Thank you.</div> : (
        <form className="op-link-form" onSubmit={(e) => {
          e.preventDefault();
          const n = Number(val.replace(/[^\d.]/g, ""));
          void send({ rate: n, days: Number(days) || 3 }, `Rate of ${rate(n, r.unit)} sent. You'll hear back today.`);
        }}>
          <div className="field">
            <label htmlFor="rate">Your rate per {r.unit} (₹, before GST)</label>
            <input id="rate" inputMode="decimal" value={val} onChange={(e) => setVal(e.target.value)} autoFocus />
          </div>
          <div className="field">
            <label htmlFor="days">Delivery in (days)</label>
            <input id="days" inputMode="numeric" value={days} onChange={(e) => setDays(e.target.value.replace(/\D/g, ""))} />
          </div>
          <button type="submit" className="pbtn" disabled={busy || !Number(val.replace(/[^\d.]/g, ""))}>Send my rate</button>
        </form>
      ))}
    </>
  );
}

function OfferBody({ o, finish, busy, send }: { o: NonNullable<View["offer"]>; finish: ReactNode; busy: boolean; send: BodyProps["send"] }) {
  const [val, setVal] = useState("");
  return (
    <>
      <div className="pcard">
        <div className="lines">
          <div className="ln"><span className="l">Item</span><b>{o.item}</b></div>
          <div className="ln"><span className="l">Offer price</span><b>{rate(o.price, o.unit)}</b></div>
          {o.list > o.price && <div className="ln"><span className="l">Usual price</span><s>{rate(o.list, o.unit)}</s></div>}
          {o.available != null && <div className="ln"><span className="l">Available</span><b>{qty(o.available, o.unit)}</b></div>}
        </div>
      </div>
      {finish ?? (
        <form className="op-link-form" onSubmit={(e) => {
          e.preventDefault();
          const n = Number(val.replace(/[^\d.]/g, ""));
          void send({ qty: n }, `${qty(n, o.unit)} reserved for you. We'll confirm shortly.`);
        }}>
          <div className="field">
            <label htmlFor="qty">How much would you like? ({o.unit})</label>
            <input id="qty" inputMode="decimal" value={val} onChange={(e) => setVal(e.target.value)} />
          </div>
          <button type="submit" className="pbtn" disabled={busy || !Number(val.replace(/[^\d.]/g, ""))}>Reserve</button>
        </form>
      )}
    </>
  );
}
