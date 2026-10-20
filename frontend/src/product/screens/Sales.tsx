import { useEffect, useMemo, useState } from "react";

import { api } from "../../api/client";
import { Empty, PageHead, Panel, Tabs } from "../../demo/desk/ui";
import { Status } from "../bits";
import { useDesk } from "../ctx";
import { day, money, stamp, time, useData, type CustomerRow, type Sales as SalesData } from "../data";

type T = "enquiries" | "board" | "list";

const COLUMNS: { id: string; label: string; match: string[]; cls: string }[] = [
  { id: "wait", label: "Waiting for you", match: ["pending_approval", "draft"], cls: "c-talks" },
  { id: "sent", label: "Sent", match: ["sent"], cls: "c-sent" },
  { id: "opened", label: "Opened", match: ["opened", "negotiating"], cls: "c-opened" },
  { id: "won", label: "Won", match: ["won"], cls: "c-won" },
  { id: "lost", label: "Lost or expired", match: ["lost", "expired"], cls: "c-lost" },
];

export default function Sales() {
  const ctx = useDesk();
  const { data } = useData<SalesData>("/app/sales", 30000);
  const [tab, setTab] = useState<T>((ctx.params.tab as T) ?? (ctx.params.paste !== undefined ? "enquiries" : "board"));
  if (!data) return <Empty title="Loading…" />;
  const waiting = data.enquiries.filter((e) => ["new", "waiting", "needs_review"].includes(e.status));
  return (
    <>
      <PageHead title="Sales" sub={<>Every enquiry priced from the customer's last rate and today's market, sent as a link, and followed up. <b>{money(data.stats.open_value)}</b> in open quotes.</>} />
      <div className="dk-stats">
        <div><span>Open quotes</span><b>{money(data.stats.open_value)}</b><small>{data.quotes.filter((q) => ["sent", "opened", "negotiating"].includes(q.status)).length} quotes</small></div>
        <div><span>Win rate, 30 days</span><b>{data.stats.win_rate === null ? "—" : `${data.stats.win_rate}%`}</b><small>{money(data.stats.won_value)} won</small></div>
        <div><span>Quotes, 30 days</span><b>{data.stats.quotes_30d}</b><small>from enquiries and the team</small></div>
        <div><span>Enquiry to quote</span><b>{data.stats.avg_minutes_to_quote === null ? "—" : `${data.stats.avg_minutes_to_quote} min`}</b><small>average</small></div>
      </div>
      <Tabs value={tab} onChange={setTab} items={[
        { id: "board", label: "Quotes" },
        { id: "enquiries", label: "Enquiries", count: waiting.length },
        { id: "list", label: "All quotes", count: data.quotes.length },
      ]} />
      {tab === "enquiries" && <Enquiries data={data} />}
      {tab === "board" && (
        <div className="dk-board">
          {COLUMNS.map((c) => {
            const list = data.quotes.filter((q) => c.match.includes(q.status));
            return (
              <div key={c.id} className={`dk-col ${c.cls}`}>
                <div className="dk-col-h"><span>{c.label}</span><span className="n">{list.length}</span><small>{money(list.reduce((a, q) => a + q.total, 0))}</small></div>
                <div className="dk-col-b">
                  {list.slice(0, 30).map((q) => (
                    <button key={q.id} type="button" className={`dk-qc ${c.id === "lost" ? "quiet" : ""}`} onClick={() => ctx.drawer({ type: "quote", id: q.id })}>
                      <span className="top"><span className="no">{q.number}</span><span className="ag">{day(q.created_at)}</span></span>
                      <b>{q.party}</b>
                      <span className="bot"><b>{money(q.total)}</b><span className={`mg ${q.margin < 3 ? "low" : ""}`}>{q.margin.toFixed(1)}%</span></span>
                      {q.status === "sent" && q.nudged_at && <span className="hint">Nudged {day(q.nudged_at)}, not opened</span>}
                      {q.status === "opened" && q.opened_at && <span className="hint">Opened {day(q.opened_at)} {time(q.opened_at)}</span>}
                    </button>
                  ))}
                  {!list.length && <div className="dk-col-empty">None</div>}
                </div>
              </div>
            );
          })}
        </div>
      )}
      {tab === "list" && (
        <Panel pad={false}>
          <table className="dk-table">
            <thead><tr><th>Quote</th><th>Customer</th><th>Created</th><th className="r">Value</th><th className="r">Margin</th><th>Status</th></tr></thead>
            <tbody>
              {data.quotes.map((q) => (
                <tr key={q.id} onClick={() => ctx.drawer({ type: "quote", id: q.id })}>
                  <td><b>{q.number}</b></td><td>{q.party}</td><td>{stamp(q.created_at)}</td>
                  <td className="r num">{money(q.total)}</td><td className={`r num ${q.margin < 3 ? "bad" : ""}`}>{q.margin.toFixed(1)}%</td><td><Status s={q.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}
    </>
  );
}

function Enquiries({ data }: { data: SalesData }) {
  const ctx = useDesk();
  const [text, setText] = useState(ctx.params.paste ?? "");
  const [party, setParty] = useState<number | null>(ctx.params.party ? Number(ctx.params.party) : null);
  const [find, setFind] = useState("");
  const [channel, setChannel] = useState("whatsapp_paste");
  const { data: matches } = useData<CustomerRow[]>(find.trim().length >= 2 ? `/app/customers?q=${encodeURIComponent(find.trim())}` : null);
  const { data: picked } = useData<{ party: { name: string } }>(party ? `/app/customers/${party}` : null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (ctx.params.party) setParty(Number(ctx.params.party)); }, [ctx.params.party]);

  const submit = async () => {
    setBusy(true);
    const r = await ctx.act(
      () => api.post<{ quote: string | null; quote_id: number | null; approval_id: number | null; approval_reason: string | null; status: string }>(
        "/app/enquiries", { party_id: party, text, channel }),
      (r) => (r.quote ? `Quote ${r.quote} sent to the customer.` : r.approval_id ? `Priced. Waiting for the owner: ${r.approval_reason}` : "The Sales agent couldn't read it; it's in the sales Inbox."),
    );
    setBusy(false);
    if (r) {
      setText("");
      if (r.quote_id) ctx.drawer({ type: "quote", id: r.quote_id });
    }
  };
  const list = useMemo(() => data.enquiries, [data]);
  return (
    <div className="dk-grid2 wide-l">
      <Panel title="Enquiries" sub="Newest first. The Sales agent prices each one as it arrives." pad={false}>
        <ul className="dk-list">
          {list.map((e) => (
            <li key={e.id}>
              <button type="button" className="dk-list-main" onClick={() => (e.quote ? ctx.drawer({ type: "quote", id: e.quote.id }) : e.party_id && ctx.drawer({ type: "customer", id: e.party_id }))}>
                <span className="dk-age">{time(e.received_at)}</span>
                <span>
                  <b>{e.party ?? "Unknown sender"} <small className="muted">· {day(e.received_at)} · {e.channel.replace("_", " ")}</small></b>
                  <small>“{e.text}”</small>
                </span>
              </button>
              {e.quote ? <Status s={e.quote.status} /> : <Status s={e.status} />}
            </li>
          ))}
          {!list.length && <li className="dk-list-empty">No enquiries yet.</li>}
        </ul>
      </Panel>
      <Panel title="Paste an enquiry" sub="From WhatsApp, a call or an email. The Sales agent reads it and quotes in your rules.">
        <div className="op-form">
          <label className="op-field">
            <span>Customer</span>
            {party && picked ? (
              <div className="op-picked"><b>{picked.party.name}</b><button type="button" className="dk-link" onClick={() => setParty(null)}>Change</button></div>
            ) : (
              <>
                <input type="search" value={find} onChange={(e) => setFind(e.target.value)} placeholder="Type a customer name" />
                {matches && matches.length > 0 && (
                  <ul className="op-suggest">
                    {matches.slice(0, 6).map((m) => <li key={m.party_id}><button type="button" onClick={() => { setParty(m.party_id); setFind(""); }}>{m.name} <small>{m.area} · grade {m.grade}</small></button></li>)}
                  </ul>
                )}
              </>
            )}
          </label>
          <label className="op-field">
            <span>What they asked for</span>
            <textarea className="dk-paste" rows={4} value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. Bhai 12 MT 12mm saria ka rate do, delivery Hinjewadi" />
          </label>
          <label className="op-field">
            <span>Came in by</span>
            <select value={channel} onChange={(e) => setChannel(e.target.value)}>
              <option value="whatsapp_paste">WhatsApp (pasted)</option>
              <option value="phone_note">Phone call</option>
              <option value="email">Email</option>
            </select>
          </label>
          <div className="dk-paste-acts">
            <button type="button" className="btn btn-go btn-sm" disabled={busy || !party || text.trim().length < 3} onClick={() => void submit()}>{busy ? "Pricing…" : "Price and send"}</button>
            <small>Inside your margin and discount rules it goes straight to the customer. Outside them it waits for the owner.</small>
          </div>
        </div>
      </Panel>
    </div>
  );
}
