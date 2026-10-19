import { useMemo, useState } from "react";
import CardView from "../components/CardView";
import { ask } from "../engine/ask";
import { customerById } from "../engine/core";
import { moveQuote, nudgeQuote, quoteEnquiry, winBack } from "../engine/desk";
import { tap } from "../engine/respond";
import type { PipeQuote, Stage } from "../engine/types";
import { money, qty } from "../lib/format";
import type { Ctx, PageParams } from "./ctx";
import { IArrow, ISend, ISpark } from "./icons";
import { allQuotes } from "./select";
import { age, Check, GradeTag, Initials, PageHead, Panel, STAGES, StageTag, Tabs } from "./ui";

type View = "board" | "enquiries" | "winback";

export default function Sales({ ctx, params }: { ctx: Ctx; params: PageParams }) {
  const s = ctx.s;
  const w = s.world;
  const [view, setView] = useState<View>((params.tab as View) ?? "board");
  const [rep, setRep] = useState("all");
  const quotes = useMemo(() => allQuotes(s), [s]);
  const open = quotes.filter((q) => q.stage !== "won" && q.stage !== "lost");
  const won = quotes.filter((q) => q.stage === "won");
  const waiting = s.desk.enquiries.filter((e) => !e.quoted);
  const lapsed = w.customers.filter((c) => c.lastBuyDays > 30);

  return (
    <>
      <PageHead title="Sales" sub="Which enquiries and quotes need action today?">
        <button type="button" className="btn btn-go btn-sm" onClick={() => setView("enquiries")}>
          <ISpark /> Paste an enquiry
        </button>
      </PageHead>

      <div className="dk-stats">
        <div><span>Open quotes</span><b>{money(open.reduce((a, q) => a + q.value, 0))}</b><small>{open.length} quotes</small></div>
        <div><span>Won this week</span><b>{money(won.reduce((a, q) => a + q.value, 0))}</b><small className="good">{won.length} orders</small></div>
        <div><span>Win rate this month</span><b>24%</b><small>34 of {142 + s.seq.quote - 1187} quotes</small></div>
        <div><span>Average time to quote</span><b>7 min</b><small className="good">was 32 min before Oprisa</small></div>
        <div><span>Enquiries waiting</span><b className={waiting.some((e) => e.ageMin > 30) ? "neg" : ""}>{waiting.length}</b><small>{waiting.filter((e) => e.ageMin > 30).length} over 30 min</small></div>
      </div>

      <div className="dk-bar">
        <Tabs<View>
          value={view}
          onChange={setView}
          items={[
            { id: "board", label: "Quotes board", count: open.length },
            { id: "enquiries", label: "Enquiries", count: waiting.length },
            { id: "winback", label: "Win back", count: lapsed.length },
          ]}
        />
        {view === "board" && (
          <label className="dk-filter">
            Salesperson
            <select value={rep} onChange={(e) => setRep(e.target.value)}>
              <option value="all">Everyone</option>
              {w.team.sales.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </label>
        )}
      </div>

      {view === "board" && <Board ctx={ctx} quotes={rep === "all" ? quotes : quotes.filter((q) => q.rep === rep)} />}
      {view === "enquiries" && <Enquiries ctx={ctx} />}
      {view === "winback" && <WinBack ctx={ctx} />}
    </>
  );
}

function Board({ ctx, quotes }: { ctx: Ctx; quotes: PipeQuote[] }) {
  const s = ctx.s;
  const [over, setOver] = useState<Stage | null>(null);
  const drop = (no: string, stage: Stage) => {
    const q = quotes.find((x) => x.no === no);
    if (!q) return;
    if (q.msgId) {
      ctx.drawer({ type: "quote", no });
      return;
    }
    ctx.run(moveQuote(ctx.s, no, stage));
    if (stage === "won") ctx.toast(`${no} won · ${money(q.value)} — sales order ready to post`);
  };
  return (
    <div className="dk-board">
      {STAGES.map((st) => {
        const list = quotes.filter((q) => q.stage === st.id);
        return (
          <div
            key={st.id}
            className={`dk-col c-${st.id} ${over === st.id ? "over" : ""}`}
            onDragOver={(e) => {
              e.preventDefault();
              setOver(st.id);
            }}
            onDragLeave={() => setOver(null)}
            onDrop={(e) => {
              e.preventDefault();
              setOver(null);
              drop(e.dataTransfer.getData("text/plain"), st.id);
            }}
          >
            <div className="dk-col-h">
              <span>{st.label}</span>
              <span className="n">{list.length}</span>
              <b>{money(list.reduce((a, q) => a + q.value, 0))}</b>
            </div>
            <div className="dk-col-b">
              {list.map((q) => {
                const c = customerById(s.world, q.customerId);
                const quiet = (q.stage === "sent" || q.stage === "opened") && q.ageH >= 24;
                return (
                  <button
                    key={q.no}
                    type="button"
                    className={`dk-qc ${quiet ? "quiet" : ""}`}
                    draggable={!q.msgId}
                    onDragStart={(e) => e.dataTransfer.setData("text/plain", q.no)}
                    onClick={() => ctx.drawer({ type: "quote", no: q.no })}
                  >
                    <span className="top">
                      <span className="no">{q.no}</span>
                      <span className={`ag ${quiet ? "late" : ""}`}>{q.msgId && q.stage === "draft" ? "new" : age(q.ageH)}</span>
                    </span>
                    <b>{c.name}</b>
                    <small>{qty(q.qty, q.unit)} {q.product.replace(/\s*\(.*?\)\s*/g, " ").trim()}</small>
                    <span className="bot">
                      <b>{money(q.value)}</b>
                      <span className={`mg ${q.margin < s.world.limits.marginFloor ? "low" : ""}`}>{q.margin}%</span>
                      <Initials name={q.rep} size={20} />
                    </span>
                    {quiet && <span className="hint">No reply in {age(q.ageH)} — nudge?</span>}
                  </button>
                );
              })}
              {!list.length && <div className="dk-col-empty">Drop a quote here</div>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Enquiries({ ctx }: { ctx: Ctx }) {
  const s = ctx.s;
  const w = s.world;
  const [text, setText] = useState("");
  const [startNo, setStartNo] = useState<number | null>(null);
  const p1 = w.products[1]!;
  const sample = w.biz.language === "Hinglish" ? `${w.customers[7]!.contact} (${w.customers[7]!.name}): ${p1.qty[0]} ${p1.unit} ${p1.name} chahiye, Monday tak site pe` : `${w.customers[7]!.contact} (${w.customers[7]!.name}): Need ${p1.qty[0]} ${p1.unit} ${p1.name} at site by Monday`;
  const fresh = startNo === null ? [] : allQuotes(s).filter((q) => q.msgId && Number(q.no.slice(2)) > startNo);

  const price = (t: string) => {
    const clean = t.trim();
    if (!clean) return;
    const c = w.customers.find((x) => clean.toLowerCase().includes(x.name.toLowerCase()));
    setStartNo((v) => v ?? s.seq.quote);
    ctx.run(ask(ctx.s, "sales", /quote|rate|need|chahiye|bhav/i.test(clean) ? clean : `quote ${clean}`));
    ctx.toast(`Pricing it for ${c?.name ?? "the customer"} from Tally…`);
    setText("");
  };

  return (
    <div className="dk-grid2 wide-l">
      <Panel title="Waiting for a quote" sub="Read from email, WhatsApp and phone notes. Red after 30 minutes." pad={false}>
        <table className="dk-table">
          <thead>
            <tr><th>Waiting</th><th>Customer</th><th>What they asked</th><th /></tr>
          </thead>
          <tbody>
            {s.desk.enquiries.map((e) => {
              const c = customerById(w, e.customerId);
              return (
                <tr key={e.id} className={e.quoted ? "done" : ""}>
                  <td><span className={`dk-age ${!e.quoted && e.ageMin > 30 ? "late" : ""}`}>{e.quoted ? "quoted" : e.ageMin < 60 ? `${e.ageMin} min` : `${Math.round(e.ageMin / 60)} h`}</span></td>
                  <td>
                    <button type="button" className="dk-cell-link" onClick={() => ctx.drawer({ type: "customer", id: c.id })}>{c.name}</button>
                    <small>{e.channel} · <GradeTag g={c.grade} /></small>
                  </td>
                  <td className="quote">“{e.text}”</td>
                  <td className="r">
                    {e.quoted ? <span className="dk-ok">✓ In Draft</span> : (
                      <button type="button" className="btn btn-go btn-xs" onClick={() => { setStartNo((v) => v ?? s.seq.quote); ctx.run(quoteEnquiry(ctx.s, e.id)); }}>Quote it</button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Panel>

      <Panel title="Paste any enquiry" sub="WhatsApp, email or your own note. The agent finds the item, quantity and customer, then prices it.">
        <textarea className="dk-paste" rows={5} value={text} placeholder={sample} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && e.key === "Enter") price(text); }} aria-label="Enquiry text" />
        <div className="dk-paste-acts">
          <button type="button" className="btn btn-go btn-sm" onClick={() => price(text || sample)}>
            <ISpark /> {text ? "Make the quote" : "Try with this example"}
          </button>
          <small>Ctrl + Enter</small>
        </div>
        {fresh.length > 0 && (
          <div className="dk-fresh">
            {fresh.map((q) => (
              <button key={q.no} type="button" onClick={() => ctx.drawer({ type: "quote", no: q.no })}>
                <span className="dk-ok">✓</span>
                <span>
                  <b>{q.no} ready for {customerById(w, q.customerId).name}</b>
                  <small>{qty(q.qty, q.unit)} · {money(q.value)} with GST · margin {q.margin}%</small>
                </span>
                <IArrow />
              </button>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}

function WinBack({ ctx }: { ctx: Ctx }) {
  const w = ctx.s.world;
  const list = w.customers.filter((c) => c.lastBuyDays > 30).sort((a, b) => b.sales12m - a.sales12m);
  const [ticked, setTicked] = useState<Set<string>>(new Set(list.map((c) => c.id)));
  const [sent, setSent] = useState(false);
  return (
    <Panel
      title="Customers who stopped buying"
      sub="Regulars with no order in 30+ days. Today's rates with an order link usually brings 1 in 4 back."
      right={<button type="button" className="btn btn-go btn-sm" disabled={!ticked.size || sent} onClick={() => { ctx.run(winBack(ctx.s, [...ticked])); setSent(true); ctx.toast(`Today's rates sent to ${ticked.size} customers`); }}><ISend /> {sent ? "Sent" : `Send today's rates (${ticked.size})`}</button>}
      pad={false}
    >
      <table className="dk-table">
        <thead>
          <tr><th className="ck"><Check on={ticked.size === list.length} onChange={(v) => setTicked(new Set(v ? list.map((c) => c.id) : []))} label="Select all" /></th><th>Customer</th><th>Grade</th><th className="r">Last order</th><th className="r">12-month sales</th><th>Salesperson</th></tr>
        </thead>
        <tbody>
          {list.map((c) => (
            <tr key={c.id} onClick={() => ctx.drawer({ type: "customer", id: c.id })}>
              <td className="ck"><Check on={ticked.has(c.id)} onChange={(v) => setTicked((o) => { const n = new Set(o); if (v) n.add(c.id); else n.delete(c.id); return n; })} label={`Select ${c.name}`} /></td>
              <td><b>{c.name}</b><small>{c.contact} · {c.area}</small></td>
              <td><GradeTag g={c.grade} /></td>
              <td className="r bad">{c.lastBuyDays} days ago</td>
              <td className="r">{money(c.sales12m)}</td>
              <td>{c.rep}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

/* ---------------------------------------------------------------------------
   The quote drawer
   --------------------------------------------------------------------------- */

export function QuotePanel({ ctx, no }: { ctx: Ctx; no: string }) {
  const s = ctx.s;
  const q = allQuotes(s).find((x) => x.no === no);
  if (!q) return <div className="dk-dp"><h2>Quote not found</h2></div>;
  const c = customerById(s.world, q.customerId);
  const msg = q.msgId ? s.threads.sales.messages.find((m) => m.id === q.msgId) : undefined;
  const live = msg && !msg.chosen ? (msg.actions ?? []) : [];

  return (
    <div className="dk-dp">
      <span className="k">Quote · {q.rep}</span>
      <h2>{q.no} · {c.name}</h2>
      <div className="dk-dp-tags"><StageTag stage={q.stage} /><GradeTag g={c.grade} /><span className="muted">{q.stage === "draft" ? "Not sent yet" : `Last touched ${age(q.ageH)} ago`}</span></div>

      {msg?.card ? (
        <div className="dk-card-host"><CardView card={msg.card} onGo={() => {}} /></div>
      ) : (
        <div className="dk-facts">
          <div><span>Item</span><b>{qty(q.qty, q.unit)} {q.product}</b></div>
          <div><span>Value with GST</span><b>{money(q.value)}</b></div>
          <div className={q.margin < s.world.limits.marginFloor ? "warn" : ""}><span>Margin</span><b>{q.margin}% · floor {s.world.limits.marginFloor}%</b></div>
          <div><span>Customer pays</span><b>{c.grade === "A" ? "On time" : `Around day ${c.payDay}`}</b></div>
        </div>
      )}

      <div className="dk-steps">
        {(["draft", "sent", "opened", "talks", "won"] as Stage[]).map((st, i) => {
          const at = ["draft", "sent", "opened", "talks", "won"].indexOf(q.stage === "lost" ? "talks" : q.stage);
          return <span key={st} className={i <= at ? "on" : ""}>{STAGES.find((x) => x.id === st)!.label}</span>;
        })}
      </div>

      <div className="dk-dp-acts">
        {live.map((a) => (
          <button key={a.id + a.label} type="button" className={`btn ${a.primary ? "btn-go" : "btn-line"} btn-sm`} onClick={() => ctx.run(tap(ctx.s, "sales", msg!.id, a))}>{a.label}</button>
        ))}
        {!q.msgId && (q.stage === "sent" || q.stage === "opened" || q.stage === "talks") && (
          <>
            <button type="button" className="btn btn-go btn-sm" onClick={() => { ctx.run(nudgeQuote(ctx.s, q.no)); ctx.toast(`Nudge sent to ${c.contact}`); }}>Send a gentle nudge</button>
            <button type="button" className="btn btn-line btn-sm" onClick={() => { ctx.run(moveQuote(ctx.s, q.no, "won")); ctx.toast(`${q.no} won · ${money(q.value)}`); }}>Mark won</button>
            <button type="button" className="btn btn-line btn-sm" onClick={() => ctx.run(moveQuote(ctx.s, q.no, "lost"))}>Mark lost</button>
          </>
        )}
        {q.msgId && msg?.chosen && <p className="dk-fine">{msg.status ?? `Done: ${msg.chosen}`}</p>}
      </div>

      <div className="dk-dp-links">
        <button type="button" className="dk-link" onClick={() => ctx.drawer({ type: "customer", id: c.id })}>Open {c.name} <IArrow /></button>
        <button type="button" className="dk-link" onClick={() => ctx.chat("sales")}>Open Sales chat <IArrow /></button>
      </div>
    </div>
  );
}
