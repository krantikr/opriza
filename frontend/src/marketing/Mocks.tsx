/* ---------------------------------------------------------------------------
   In-brand mock product screens.

   The real desk UI is navy/blue and clashes inside the warm maroon marketing
   skin, and three of the five agents aren't built yet. So each agent gets a
   purpose-drawn mock here — a small, clean "app window" in the Oprisa palette
   that shows the one view that agent is about. These are illustrations, not
   screenshots; they never claim to be the running product.
   --------------------------------------------------------------------------- */

import type { ReactNode } from "react";

function Window({ title, children, chip }: { title: string; children: ReactNode; chip?: string }) {
  return (
    <div className="mock">
      <div className="mock-bar">
        <span className="mock-dot" />
        <span className="mock-dot" />
        <span className="mock-dot" />
        <span className="mock-title">{title}</span>
        {chip && <span className="mock-chip">{chip}</span>}
      </div>
      <div className="mock-body">{children}</div>
    </div>
  );
}

/* --- 1. Sales / Quotation engine ------------------------------------------ */
export function MockSales() {
  return (
    <Window title="Quotation" chip="Draft ready">
      <div className="m-quote">
        <div className="m-quote-head">
          <div>
            <div className="m-line m-strong">ABC Infra — 20 MT TMT</div>
            <div className="m-line m-dim">12mm Fe500D · delivery Pune · by 15 Oct</div>
          </div>
          <div className="m-price">
            ₹56,200<span>/MT</span>
          </div>
        </div>
        <div className="m-rows">
          {[
            ["Base purchase price", "₹52,400"],
            ["Freight to Pune", "₹1,280"],
            ["Customer past margin", "3.1%"],
            ["Market rate today", "₹56,900"],
          ].map(([k, v]) => (
            <div className="m-row" key={k}>
              <span>{k}</span>
              <span className="m-val">{v}</span>
            </div>
          ))}
        </div>
        <div className="m-approve">
          <span className="m-margin">Margin 3.1% · ₹2,520/MT</span>
          <span className="m-btn">Approve &amp; send</span>
        </div>
      </div>
    </Window>
  );
}

/* --- 2. Collections / Receivables engine ---------------------------------- */
export function MockCollections() {
  const rows = [
    ["ABC Infra", "₹42L", "12 days late", "now", "hot"],
    ["Mehta Constructions", "₹21L", "8 days", "today", "warm"],
    ["Shree Builders", "₹15L", "5 days", "Thu", "cool"],
  ];
  return (
    <Window title="Collections — today's chase list" chip="₹78L overdue">
      <div className="m-list">
        {rows.map(([name, amt, age, when, tone]) => (
          <div className="m-item" key={name as string}>
            <span className={`m-pip m-${tone}`} />
            <span className="m-name">{name}</span>
            <span className="m-amt">{amt}</span>
            <span className="m-age">{age}</span>
            <span className="m-when">{when}</span>
          </div>
        ))}
      </div>
      <div className="m-note">Ranked by amount, ageing and how each one actually pays.</div>
    </Window>
  );
}

/* --- 3. Procurement / Demand engine --------------------------------------- */
export function MockProcurement() {
  return (
    <Window title="Procurement — what to order" chip="3 to reorder">
      <div className="m-proc">
        <div className="m-proc-row m-proc-urgent">
          <div>
            <div className="m-strong">12mm Fe500D</div>
            <div className="m-dim">6 days of cover left</div>
          </div>
          <div className="m-proc-act">
            <span className="m-flag">Reorder</span>
            <span className="m-dim">40 MT · Jindal ₹51,900</span>
          </div>
        </div>
        <div className="m-proc-row">
          <div>
            <div className="m-strong">8mm Fe500D</div>
            <div className="m-dim">11 days of cover</div>
          </div>
          <div className="m-proc-act">
            <span className="m-flag m-soft">Soon</span>
            <span className="m-dim">25 MT · Tata ₹53,100</span>
          </div>
        </div>
        <div className="m-proc-row m-proc-idle">
          <div>
            <div className="m-strong">MS Plates 10mm</div>
            <div className="m-dim">Idle 100 days · liquidate</div>
          </div>
          <div className="m-proc-act">
            <span className="m-flag m-green">3 buyers</span>
            <span className="m-dim">Patel, Kumar, Sai</span>
          </div>
        </div>
      </div>
    </Window>
  );
}

/* --- 4. Document manager -------------------------------------------------- */
export function MockDocuments() {
  const docs = [
    ["Purchase order", "120.00 MT", "done"],
    ["Dispatch note", "119.70 MT", "done"],
    ["Weighbridge", "119.62 MT", "done"],
    ["Invoice", "119.62 MT", "match"],
  ];
  return (
    <Window title="Documents — order MS-002417" chip="Reconciled">
      <div className="m-docs">
        {docs.map(([name, qty, state], i) => (
          <div className="m-doc" key={name as string}>
            <span className="m-doc-ico">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} width={16} height={16}>
                <path d="M7 3h7l5 5v13H7z" />
                <path d="M14 3v5h5" />
              </svg>
            </span>
            <span className="m-doc-name">{name}</span>
            <span className="m-doc-qty">{qty}</span>
            <span className={`m-doc-state ${state === "match" ? "m-doc-match" : ""}`}>
              {state === "match" ? "✓ matches" : "✓"}
            </span>
            {i < docs.length - 1 && <span className="m-doc-link" aria-hidden="true" />}
          </div>
        ))}
      </div>
      <div className="m-note">PO → dispatch → weighbridge → invoice, reconciled to the kilo.</div>
    </Window>
  );
}

/* --- 5. Branch manager / reports ------------------------------------------ */
export function MockReports() {
  const bars = [38, 52, 46, 61, 55, 72, 68];
  return (
    <Window title="Yesterday at a glance" chip="Mon, 11 Oct">
      <div className="m-kpis">
        <div className="m-kpi">
          <span className="m-kpi-v">₹4.2 Cr</span>
          <span className="m-kpi-k">Sales</span>
        </div>
        <div className="m-kpi">
          <span className="m-kpi-v">₹78L</span>
          <span className="m-kpi-k">Overdue</span>
        </div>
        <div className="m-kpi">
          <span className="m-kpi-v">12</span>
          <span className="m-kpi-k">Quotes</span>
        </div>
      </div>
      <div className="m-chart" role="img" aria-label="Seven-day sales trend, rising">
        {bars.map((h, i) => (
          <span key={i} className="m-bar" style={{ height: `${h}%` }} />
        ))}
      </div>
      <div className="m-note">Sales, collections and stock — one glance, every morning.</div>
    </Window>
  );
}
