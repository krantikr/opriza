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

const SECTORS = [
  "Steel & metals",
  "Building materials",
  "Electrical supplies",
  "Industrial / MRO",
  "Auto parts",
  "Chemicals",
  "Pipes, valves & pumps",
  "Pharma distribution",
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

      {/* the brain diagram, in words */}
      <section>
        <div className="wrap">
          <Reveal className="brain">
            <div className="brain-in">
              <span>Tally</span>
              <span>Bank &amp; GST</span>
              <span>Email</span>
              <span>WhatsApp</span>
            </div>
            <div className="brain-arrow" aria-hidden="true">
              <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2}>
                <path d="M5 12h14M13 6l6 6-6 6" />
              </svg>
            </div>
            <div className="brain-core">Oprisa — the business brain</div>
            <div className="brain-arrow" aria-hidden="true">
              <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.2}>
                <path d="M5 12h14M13 6l6 6-6 6" />
              </svg>
            </div>
            <div className="brain-out">
              <span>Sales</span>
              <span>Collections</span>
              <span>Procurement</span>
              <span>Credit</span>
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
        <div className="wrap who-grid">
          <Reveal>
            <p className="eyebrow">Who it's for</p>
            <h2 className="h2" style={{ maxWidth: "16ch" }}>
              Inventory-heavy desks with negotiated prices and real receivables.
            </h2>
            <p className="lead" style={{ marginTop: 14 }}>
              We start with ₹100–500 Cr steel stockists and distributors — meaningful stock, working-capital pressure,
              salespeople juggling hundreds of customers on WhatsApp and email. The same shape repeats across B2B
              distribution, so the brain travels.
            </p>
          </Reveal>
          <Reveal delay={120}>
            <h4 className="sect-h">Sectors the model fits</h4>
            <div className="sectors">
              {SECTORS.map((s, i) => (
                <span key={s} className={`sect${i === 0 ? " sect-now" : ""}`}>
                  {s}
                  {i === 0 && <em>first</em>}
                </span>
              ))}
            </div>
          </Reveal>
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
