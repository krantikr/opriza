/* ---------------------------------------------------------------------------
   Pricing — no public numbers yet (pre-PMF). Framed as design-partner /
   early-access, with a clear "what you get" and a contact CTA.
   --------------------------------------------------------------------------- */

import { Link } from "react-router-dom";

import { Reveal, useSeo } from "./lib";

const INCLUDED = [
  "The Quotation Copilot, live from day one",
  "Tally, WhatsApp and Gmail connected in ~2 minutes",
  "Your pricing rules, margins and customer history — not a generic rate card",
  "Human approval on every quote; nothing sends on its own",
  "The morning brief as each new agent comes online",
  "Direct line to the founders — you shape what gets built next",
];

const FAQ = [
  {
    q: "Why no price on the page?",
    a: "We're onboarding a small set of design partners first. Pricing is set with each desk against the value it actually sees — orders won back, days of DSO removed — not a number pulled from the air.",
  },
  {
    q: "What does a design partner commit to?",
    a: "Connecting your real data, using it on live enquiries, and telling us the truth about what works. In return you get the product at design-partner terms and first say on the roadmap.",
  },
  {
    q: "Is my data safe with other desks on the platform?",
    a: "Each desk is isolated at the database level by row-level security — one desk can never read another's enquiries, customers or prices. It's enforced in the system, not left to application code.",
  },
  {
    q: "What do I need to start?",
    a: "A Tally/ERP you already run, a Gmail inbox where enquiries arrive, and a WhatsApp number. No new hardware, no migration.",
  },
];

export default function Pricing() {
  useSeo({
    title: "Pricing",
    description:
      "Oprisa is onboarding design partners now. Pricing is set per desk against the value it delivers — not a generic rate card. Request an early-access slot.",
    path: "/pricing",
  });

  return (
    <>
      <header className="page-head">
        <div className="wrap">
          <Reveal>
            <p className="eyebrow" style={{ color: "var(--saffron)" }}>
              Early access
            </p>
            <h1 className="page-title">Priced against what it's worth to your desk.</h1>
            <p className="page-sub">
              We're taking on a handful of design partners before setting public plans. You get the product early, at
              design-partner terms, and a real say in what we build next.
            </p>
          </Reveal>
        </div>
      </header>

      <section>
        <div className="wrap price-grid">
          <Reveal className="price-card">
            <span className="price-badge">Design partner</span>
            <div className="price-amount">
              Let's talk
              <span className="price-unit">numbers for your desk</span>
            </div>
            <p className="price-note">
              A short call to see your enquiry volume and where orders and cash are leaking — then terms that track the
              value, not a fixed licence.
            </p>
            <Link className="btn btn-go" to="/contact" style={{ width: "100%", justifyContent: "center" }}>
              Request a slot
            </Link>
          </Reveal>
          <Reveal delay={100}>
            <h3 className="incl-h">What's included</h3>
            <ul className="incl">
              {INCLUDED.map((it) => (
                <li key={it}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.6}>
                    <path d="M4 12.5l5 5 11-12" />
                  </svg>
                  {it}
                </li>
              ))}
            </ul>
          </Reveal>
        </div>
      </section>

      <section className="surface-band">
        <div className="wrap">
          <Reveal>
            <p className="eyebrow">Questions</p>
            <h2 className="h2">The things desks ask us first.</h2>
          </Reveal>
          <div className="faq">
            {FAQ.map((f, i) => (
              <Reveal key={f.q} delay={i * 60} className="faq-row">
                <h3>{f.q}</h3>
                <p>{f.a}</p>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <section className="closer-band">
        <div className="wrap closer">
          <Reveal>
            <h2 className="h2" style={{ color: "#fff", maxWidth: "20ch", margin: "0 auto 12px" }}>
              See the morning brief on your own numbers.
            </h2>
            <Link className="btn btn-go" to="/contact">
              Request access
            </Link>
          </Reveal>
        </div>
      </section>
    </>
  );
}
