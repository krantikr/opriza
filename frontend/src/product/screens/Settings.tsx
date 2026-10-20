import { useState } from "react";

import { api } from "../../api/client";
import { PageHead, Panel } from "../../demo/desk/ui";
import { useDesk } from "../ctx";
import { day, money, stamp, time, useData, type CustomerRow } from "../data";

export default function Settings() {
  const ctx = useDesk();
  const me = ctx.me;
  const biz = me.business!;
  return (
    <>
      <PageHead title="Settings" sub="Your business, where the books come from, and how the agents run." />
      <div className="dk-grid2">
        <Panel title="Business">
          <div className="dk-facts">
            <div><span>Name</span><b>{me.organisation?.name}</b></div>
            <div><span>Trade and city</span><b>{biz.trade} · {biz.city}</b></div>
            <div><span>Language for messages</span><b>{biz.language}</b></div>
            <div><span>Tally</span><b>{biz.tally_version}</b></div>
            <div><span>Bank balance (from Tally)</span><b>{money(biz.bank_balance)}</b></div>
          </div>
        </Panel>
        <Panel title="Where the books come from">
          <div className="dk-facts">
            <div><span>Source</span><b>{biz.mock ? "Sample books (mock Tally)" : "Tally XML connector"}</b></div>
            <div><span>Last sync</span><b>{biz.last_sync_at ? stamp(biz.last_sync_at) : "—"} · {biz.last_sync_status ?? "—"}</b></div>
            {biz.last_sync_error && <div className="warn"><span>Last error</span><b>{biz.last_sync_error}</b></div>}
            <div><span>Business clock</span><b>{biz.as_of ? `Held at ${day(biz.now)} ${time(biz.now)} (sample data)` : "Real time"}</b></div>
          </div>
          <div className="dk-preview-acts">
            <button type="button" className="btn btn-line btn-sm" onClick={() => void ctx.act(() => api.post<{ status: string }>("/app/sync"), (r) => `Sync ${r.status}.`)}>Sync now</button>
            <button type="button" className="btn btn-line btn-sm" onClick={() => void ctx.act(() => api.post<{ jobs: string[]; events: number }>("/app/tick"), (r) => r.jobs.length ? `Ran ${r.jobs.join(", ")}.` : `Nothing due; handled ${r.events} events.`)}>Run due agent jobs</button>
          </div>
          <p className="dk-fine">To connect a real Tally: set this desk's source to <code>tally_xml</code> with the connector address. Nothing else changes; see docs/agents/RUNBOOK.md.</p>
        </Panel>
      </div>
      <div className="dk-grid2">
        <Panel title="How the agents run">
          <div className="dk-facts">
            <div><span>Brain</span><b>{me.brain === "llm" ? "Language model via OpenRouter, rules as fallback" : "Rules (no model calls)"}</b></div>
            <div><span>Messages to customers</span><b>{me.channel === "live" ? "Sent by email / SMS" : "Outbox only (nothing leaves)"}</b></div>
          </div>
          <p className="dk-fine">Set <code>AGENT_BRAIN</code> (rules, llm or auto) and <code>AGENT_CHANNEL</code> (outbox or live) in the server's .env.</p>
        </Panel>
        <Panel title="Team" pad={false}>
          <ul className="dk-list">
            {me.team.map((t) => <li key={t.id}><span className="dk-list-main static"><span><b>{t.name}</b><small>{t.desk_role}</small></span></span></li>)}
          </ul>
        </Panel>
      </div>
      {biz.mock && <Simulator />}
    </>
  );
}

/** Mock desks only: make Tally or a customer do something, and watch the agents react. */
function Simulator() {
  const ctx = useDesk();
  const [find, setFind] = useState("");
  const { data: matches } = useData<CustomerRow[]>(find.trim().length >= 2 ? `/app/customers?q=${encodeURIComponent(find.trim())}` : null);
  const [party, setParty] = useState<CustomerRow | null>(null);
  const [amount, setAmount] = useState("");
  const [rate, setRate] = useState("");
  const sim = (body: Record<string, unknown>, done: (r: any) => string) => ctx.act(() => api.post("/app/simulate", body), done);
  return (
    <Panel title="Try it: make something happen" sub="Sample data only. These go through the same paths a live desk uses, so the agents react as they would.">
      <div className="op-sim">
        <div>
          <h3>A payment arrives in Tally</h3>
          {party ? (
            <div className="op-picked"><b>{party.name}</b> <small>owes {money(party.outstanding)}</small><button type="button" className="dk-link" onClick={() => setParty(null)}>Change</button></div>
          ) : (
            <>
              <input type="search" value={find} onChange={(e) => setFind(e.target.value)} placeholder="Customer name" aria-label="Customer" />
              {matches && <ul className="op-suggest">{matches.slice(0, 5).map((m) => <li key={m.party_id}><button type="button" onClick={() => { setParty(m); setAmount(String(Math.round(m.overdue || m.outstanding))); }}>{m.name} <small>owes {money(m.outstanding)}</small></button></li>)}</ul>}
            </>
          )}
          <div className="op-row">
            <input inputMode="numeric" value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^\d.]/g, ""))} placeholder="Amount" aria-label="Amount" />
            <button type="button" className="btn btn-go btn-sm" disabled={!party || !Number(amount)}
              onClick={() => party && void sim({ kind: "receipt", party_id: party.party_id, amount: Number(amount) }, (r) => `Receipt ${r.receipt} synced. Collections, Score and Cash have reacted.`)}>
              Post receipt
            </button>
          </div>
        </div>
        <div>
          <h3>A supplier answers a rate request</h3>
          <div className="op-row">
            <input inputMode="numeric" value={rate} onChange={(e) => setRate(e.target.value.replace(/[^\d.]/g, ""))} placeholder="Rate" aria-label="Rate" />
            <button type="button" className="btn btn-go btn-sm" disabled={!Number(rate)} onClick={() => void sim({ kind: "supplier_rate", rate: Number(rate) }, () => "Rate received. The Stock agent compares and drafts a PO when two are in.")}>Send rate</button>
          </div>
        </div>
        <div>
          <h3>Move the clock</h3>
          <p className="dk-fine">Runs whatever comes due: the 8 am brief, 9 am reminders, nudges on quotes nobody opened.</p>
          <div className="op-row">
            <button type="button" className="btn btn-line btn-sm" onClick={() => void sim({ kind: "advance", hours: 4 }, (r) => `It's now ${time(r.now)}. ${r.jobs.length ? `Ran ${r.jobs.join(", ")}.` : "Nothing was due."}`)}>+4 hours</button>
            <button type="button" className="btn btn-line btn-sm" onClick={() => void sim({ kind: "advance", hours: 24 }, (r) => `It's now ${day(r.now)}. ${r.jobs.length ? `Ran ${r.jobs.join(", ")}.` : "Nothing was due."}`)}>+1 day</button>
          </div>
        </div>
      </div>
    </Panel>
  );
}
