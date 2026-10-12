/* ---------------------------------------------------------------------------
   Product — how the Quotation Copilot actually works, step by step, with the
   real desk screens. Honest about the human-approval gate.
   --------------------------------------------------------------------------- */

import { Link } from "react-router-dom";

import { Phone, Reveal, useSeo } from "./lib";

const STEPS = [
  {
    n: "01",
    tag: "Capture",
    h: "Every enquiry, from every channel",
    p: "A WhatsApp message, a forwarded email, a photo of a hand-written list. Oprisa reads it and pulls out what matters — product, grade, size, quantity, destination, delivery date — into one structured request.",
    shot: "/shot-inbox.webp",
    alt: "Inbox turning a free-text enquiry into a structured quote request",
  },
  {
    n: "02",
    tag: "Price",
    h: "Priced to win the order and hold the margin",
    p: "Not a rate card. Oprisa weighs this customer's past prices, current market rates, your inventory cost, freight and payment terms — then proposes a number with the margin shown, so you decide with the full picture.",
    shot: "/shot-pricing.webp",
    alt: "Pricing engine showing margin, freight and customer history",
  },
  {
    n: "03",
    tag: "Approve",
    h: "Nothing sends without you",
    p: "The quote is drafted, formatted and ready. You read it, adjust if you want, and send — or don't. There is no path in the product that sends on its own. The human stays in the loop by design.",
    shot: "/shot-quotations.webp",
    alt: "A drafted quotation awaiting human approval",
  },
  {
    n: "04",
    tag: "Follow up",
    h: "The deal doesn't go cold",
    p: "Sent quotes are tracked. Oprisa reminds you who hasn't replied, drafts the nudge in the customer's own context, and tells you which dormant buyers are worth a call this week.",
    shot: "/shot-followups.webp",
    alt: "Follow-up queue tracking sent quotes and reminders",
  },
];

export default function Product() {
  useSeo({
    title: "Product",
    description:
      "How Oprisa's Quotation Copilot works: capture any enquiry, price it against your stock and the customer's history, approve the draft, and follow up — with a human in the loop at every send.",
    path: "/product",
  });

  return (
    <>
      <header className="page-head">
        <div className="wrap">
          <Reveal>
            <p className="eyebrow" style={{ color: "var(--saffron)" }}>
              The Quotation Copilot · live today
            </p>
            <h1 className="page-title">From a messy enquiry to a priced quote in five minutes.</h1>
            <p className="page-sub">
              This is the first of Oprisa's agents, and it's working now. Here is exactly what happens between an enquiry
              landing and a quotation being ready to send.
            </p>
          </Reveal>
        </div>
      </header>

      <section>
        <div className="wrap steps">
          {STEPS.map((s, i) => (
            <Reveal key={s.n} delay={40} className={`step${i % 2 ? " step-rev" : ""}`}>
              <div className="step-copy">
                <div className="step-num">{s.n}</div>
                <span className="verb-tag">{s.tag}</span>
                <h3 className="step-h">{s.h}</h3>
                <p className="step-p">{s.p}</p>
              </div>
              <div className="step-shot">
                <img src={s.shot} alt={s.alt} loading="lazy" />
              </div>
            </Reveal>
          ))}
        </div>
      </section>

      {/* the morning brief, again — it's the payoff of all four steps */}
      <section className="surface-band">
        <div className="wrap ask">
          <Reveal>
            <p className="eyebrow">And then, every morning</p>
            <h2 className="h2">The work above becomes one message you actually read.</h2>
            <p className="lead" style={{ marginTop: 14 }}>
              Quoting is the first agent. As collections, stock and cash flow come online, each one reports into the same
              morning brief — so the whole business arrives in a single thread, not seven dashboards.
            </p>
            <Link className="btn btn-dark" to="/about" style={{ marginTop: 22 }}>
              See the full roadmap
            </Link>
          </Reveal>
          <Reveal delay={120} className="ask-phone">
            <Phone
              lines={[
                { html: "<b>Good morning.</b> 3 enquiries came in overnight — all quoted and waiting for you.", max: "96%" },
                { lbl: "Sales", cls: "b-sales", html: 'Gupta Steel — <span class="num">₹51,900/MT</span>, 2.8% margin.' },
                { lbl: "Sales", cls: "b-sales", html: 'Raj Infra — <span class="num">₹54,100/MT</span>, 3.4% margin.' },
                { lbl: "Follow-up", cls: "b-coll", html: 'Patel Fabricators hasn’t replied to Tuesday’s quote. Nudge drafted.' },
              ]}
            />
          </Reveal>
        </div>
      </section>

      <section className="closer-band">
        <div className="wrap closer">
          <Reveal>
            <h2 className="h2" style={{ color: "#fff", maxWidth: "20ch", margin: "0 auto 12px" }}>
              Put your quoting on autopilot — you keep the final word.
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
