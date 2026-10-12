/* ---------------------------------------------------------------------------
   About — the bigger Oprisa vision: one AI brain for asset-heavy B2B
   distributors, built one agent at a time. The roadmap is honest about what's
   live (Quotation) vs. what's next.
   --------------------------------------------------------------------------- */

import { Link } from "react-router-dom";

import { Reveal, useSeo } from "./lib";

const ROADMAP = [
  {
    wh: "Months 1–2 · built",
    h: "Quotation Copilot",
    p: "Enquiry in, priced quote out — against your stock, your margins, your customer's history. You approve before anything sends.",
    now: true,
  },
  {
    wh: "Months 3–4 · next",
    h: "Collections Copilot",
    p: "The daily chase list, promise-to-pay tracking and reminders, drafted in each customer's own context.",
  },
  {
    wh: "Months 5–6",
    h: "Procurement Copilot",
    p: "What to buy, when and from whom — demand forecast, stock-out risk, and supplier quotes compared for you.",
  },
  {
    wh: "Later",
    h: "Credit & capital",
    p: "Real payment behaviour becomes a scorecard lenders trust — so working-capital limits grow with you.",
  },
];

const SOURCES = ["Tally / ERP", "Bank & GST", "Email", "WhatsApp"];
const OUTPUTS = ["Sales", "Collections", "Procurement", "Credit"];

/** The same shape — stock, negotiated prices, fragmented customers,
 *  receivables — repeats across B2B distribution. Each card names the one
 *  thing that leaks there, so the fit is concrete rather than a logo wall. */
const SECTORS = [
  {
    name: "Steel & metals",
    note: "Thousands of SKUs by grade and size; quotes negotiated per customer, per day.",
    stat: "20,000+ stockists",
    now: true,
  },
  {
    name: "Building materials",
    note: "Cement, pipes, tiles, plywood — distributor to dealer to site, 20,000+ SKUs a desk.",
    stat: "Project-led demand",
  },
  {
    name: "Electrical supplies",
    note: "Huge SKU counts, frequent project quotes, constant brand substitution on price.",
    stat: "High quote volume",
  },
  {
    name: "Auto parts",
    note: "OEM to distributor to garage, deep catalogues, fast-moving negotiated pricing.",
    stat: "Deep catalogues",
  },
  {
    name: "Industrial / MRO",
    note: "Bearings, motors, tools — steel-like flows at an even higher SKU count.",
    stat: "Very high SKU count",
  },
  {
    name: "Pharma distribution",
    note: "Highly fragmented, local-distributor dominated, with expiry and credit pressure.",
    stat: "65,000+ distributors",
  },
];

export default function About() {
  useSeo({
    title: "About & roadmap",
    description:
      "Oprisa is one AI brain for asset-heavy B2B distributors — sales, collections, procurement and credit — built one agent at a time, starting with steel. See the vision and roadmap.",
    path: "/about",
  });

  return (
    <>
      <header className="page-head">
        <div className="wrap">
          <Reveal>
            <p className="eyebrow" style={{ color: "var(--saffron)" }}>
              The bigger picture
            </p>
            <h1 className="page-title">One brain for a distribution business. Added one agent at a time.</h1>
            <p className="page-sub">
              A steel distributor runs on information held in one person's head — who to sell to, at what price, who to
              chase, what to reorder, who'll pay late. Oprisa connects Tally, WhatsApp and Gmail into a single brain that
              holds it instead, and acts on it.
            </p>
          </Reveal>
        </div>
      </header>

      {/* the brain diagram */}
      <section>
        <div className="wrap">
          <Reveal className="brain">
            <div className="brain-col">
              <span className="brain-head">Connects to</span>
              {SOURCES.map((s) => (
                <span className="brain-node" key={s}>
                  {s}
                </span>
              ))}
            </div>
            <div className="brain-arrow" aria-hidden="true">
              <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                <path d="M4 12h15M13 6l6 6-6 6" />
              </svg>
            </div>
            <div className="brain-core">
              <span className="brain-core-mark">
                <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7}>
                  <path d="M12 3a4 4 0 00-4 4 3.5 3.5 0 00-2 6.3A3.5 3.5 0 008 20a4 4 0 008 0 3.5 3.5 0 002-6.7A3.5 3.5 0 0016 7a4 4 0 00-4-4z" />
                  <path d="M12 3v18M8 7h0M16 7h0M6 13.3h0M18 13.3h0" />
                </svg>
              </span>
              <span className="brain-core-name">Oprisa</span>
              <span className="brain-core-sub">one business brain</span>
            </div>
            <div className="brain-arrow" aria-hidden="true">
              <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
                <path d="M4 12h15M13 6l6 6-6 6" />
              </svg>
            </div>
            <div className="brain-col">
              <span className="brain-head">Acts on</span>
              {OUTPUTS.map((s) => (
                <span className="brain-node brain-node-out" key={s}>
                  {s}
                </span>
              ))}
            </div>
          </Reveal>
        </div>
      </section>

      {/* roadmap */}
      <section className="road">
        <div className="wrap road-inner">
          <Reveal>
            <p className="eyebrow" style={{ color: "var(--saffron)" }}>
              We start where the money leaks first
            </p>
            <h2 className="h2" style={{ color: "#fff" }}>
              Quoting today. Collections, procurement and credit next.
            </h2>
          </Reveal>
          <div className="track">
            {ROADMAP.map((s, i) => (
              <Reveal key={s.h} delay={i * 80} className={`stop${s.now ? " now" : ""}`}>
                <div className="stop-wh">{s.wh}</div>
                <h3>{s.h}</h3>
                <p>{s.p}</p>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* who it's for / sectors */}
      <section className="surface-band">
        <div className="wrap">
          <Reveal>
            <p className="eyebrow">Who it's for</p>
            <h2 className="h2" style={{ maxWidth: "20ch" }}>
              Inventory-heavy desks with negotiated prices and real receivables.
            </h2>
            <p className="lead" style={{ marginTop: 14 }}>
              We start with ₹100–500 Cr steel stockists and distributors — meaningful stock, working-capital pressure,
              salespeople juggling hundreds of customers on WhatsApp and email. The same shape repeats across B2B
              distribution, so the brain travels.
            </p>
          </Reveal>
          <div className="sector-grid">
            {SECTORS.map((s, i) => (
              <Reveal key={s.name} delay={i * 50} className={`sector-card${s.now ? " on" : ""}`}>
                <div className="sector-top">
                  <span className="sector-name">{s.name}</span>
                  {s.now && <span className="sector-tag">Starting here</span>}
                </div>
                <p className="sector-note">{s.note}</p>
                <span className="sector-stat">{s.stat}</span>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <section className="closer-band">
        <div className="wrap closer">
          <Reveal>
            <h2 className="h2" style={{ color: "#fff", maxWidth: "20ch", margin: "0 auto 12px" }}>
              Help shape the brain for your trade.
            </h2>
            <Link className="btn btn-go" to="/contact">
              Become a design partner
            </Link>
          </Reveal>
        </div>
      </section>
    </>
  );
}
