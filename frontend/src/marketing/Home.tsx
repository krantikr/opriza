/* ---------------------------------------------------------------------------
   Home — the landing page. Leads with the vision (the morning brief on
   WhatsApp), then grounds it in what actually ships today: real screenshots of
   the Quotation Copilot desk.
   --------------------------------------------------------------------------- */

import { Link } from "react-router-dom";

import { CountUp, Phone, Reveal, useSeo } from "./lib";
import { MockCollections, MockDocuments, MockProcurement, MockReports, MockSales } from "./Mocks";

const AGENTS = [
  {
    no: "01",
    live: true,
    when: "",
    title: "Sales agent",
    engine: "Quotation engine",
    body: "Captures requests across WhatsApp, email and calls, and prices each one accurately — against your stock, freight, payment terms and the customer's own history.",
    mock: <MockSales />,
  },
  {
    no: "02",
    live: false,
    when: "Months 3–4",
    title: "Collections agent",
    engine: "Receivables engine",
    body: "Runs your collection process so cash comes in on time — prioritising follow-ups by amount, ageing and payment behaviour, and forecasting what you'll actually collect.",
    mock: <MockCollections />,
  },
  {
    no: "03",
    live: false,
    when: "Months 5–6",
    title: "Procurement agent",
    engine: "Demand engine",
    body: "Keeps supply at the right time and the right price — liquidating aging stock, flagging stock-out risk, and timing replenishment before you run short.",
    mock: <MockProcurement />,
  },
  {
    no: "04",
    live: false,
    when: "Later",
    title: "Document manager",
    engine: "",
    body: "Easy access and sharing of every document — PO, dispatch, weighbridge, invoice, test certificates — reconciled against each other and sent to the right people.",
    mock: <MockDocuments />,
  },
  {
    no: "05",
    live: false,
    when: "Later",
    title: "Branch manager",
    engine: "",
    body: "Accurate, insightful business reports — a daily, weekly and monthly snapshot of sales, collections, stock and payables, with the actions that matter surfaced.",
    mock: <MockReports />,
  },
];

const BRIEF = [
  { html: "<b>Good morning, Mr Sharma.</b> Here’s your day:", max: "96%" },
  {
    lbl: "Sales",
    cls: "b-sales",
    html: 'Yesterday <span class="num">₹4.2 Cr</span>. <b>12</b> quotes sent. Follow up: Gupta Steel, Raj Infra.',
  },
  {
    lbl: "Collections",
    cls: "b-coll",
    html: '<span class="num">₹78L</span> overdue, 3 parties. Chase <b>ABC Infra</b> first — <span class="num">₹42L</span>, pays ~12 days late.',
  },
  {
    lbl: "Stock",
    cls: "b-stock",
    html: 'Reorder <b>12mm Fe500D</b> — 6 days of cover left. MS plates idle 100 days; 3 buyers ready.',
  },
  {
    lbl: "Cash flow",
    cls: "b-cash",
    html: '<span class="num">₹3.6 Cr</span> due to suppliers this week. XYZ’s <span class="num">₹18L</span> may slip — chase today.',
  },
];

const VERBS = [
  { tag: "Sales", h: "Quote every enquiry in 5 minutes", p: "RFQs from WhatsApp, email and calls become priced quotes — margin checked, ready to send." },
  { tag: "Collections", h: "Know whom to chase, every day", p: "A ranked call list by amount, ageing and how each customer actually pays." },
  { tag: "Stock", h: "No stock-outs, no dead stock", p: "Reorder before you run short; surface aging material and the buyers for it." },
  { tag: "Cash flow", h: "See who'll pay late, early", p: "A weekly cash forecast built from each customer's real payment history." },
];

const ChipIcon = ({ kind }: { kind: "tally" | "wa" | "mail" }) => {
  if (kind === "wa")
    return (
      <svg viewBox="0 0 24 24" fill="currentColor" width={15} height={15}>
        <path d="M12 2a10 10 0 00-8.6 15l-1.3 4.8 5-1.3A10 10 0 1012 2z" />
      </svg>
    );
  if (kind === "mail")
    return (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} width={15} height={15}>
        <rect x="3" y="5" width="18" height="14" rx="2" />
        <path d="M3 7l9 6 9-6" />
      </svg>
    );
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} width={15} height={15}>
      <rect x="4" y="3" width="16" height="18" rx="2" />
      <path d="M8 8h8M8 12h8M8 16h5" />
    </svg>
  );
};

export default function Home() {
  useSeo({
    title: "Oprisa",
    description:
      "Oprisa runs the back office of a steel distributor — sales, collections, stock and cash flow — and reports it every morning on WhatsApp. Quote every enquiry in 5 minutes.",
    path: "/",
  });

  return (
    <>
      {/* ---------- HERO ---------- */}
      <header className="hero-top">
        <div className="wrap hero-grid">
          <div className="hero-copy">
            <p className="kicker reveal in">The AI that runs your back office</p>
            <h1>
              Your whole business,
              <span className="em">on WhatsApp.</span>
            </h1>
            <p className="hero-sub">
              Sales, collections, stock and cash flow — handled for you, and reported every morning in the one app you
              already open first.
            </p>
            <div className="cta-row">
              <Link className="btn btn-go" to="/product">
                See how it works
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.4}>
                  <path d="M5 12h14M13 6l6 6-6 6" />
                </svg>
              </Link>
              <Link className="btn btn-ghost-light" to="/contact">
                Request access
              </Link>
            </div>
            <div className="connect">
              <span>Connects in 2 minutes to</span>
              <span className="connect-chip">
                <ChipIcon kind="tally" />
                Tally
              </span>
              <span className="connect-chip">
                <ChipIcon kind="wa" />
                WhatsApp
              </span>
              <span className="connect-chip">
                <ChipIcon kind="mail" />
                Gmail
              </span>
            </div>
          </div>
          <div className="hero-phone">
            <Phone lines={BRIEF} />
          </div>
        </div>
      </header>

      {/* ---------- VERBS ---------- */}
      <div className="band">
        <div className="wrap verbs">
          {VERBS.map((v, i) => (
            <Reveal key={v.tag} delay={i * 80} className="verb">
              <span className="verb-tag">{v.tag}</span>
              <h3>{v.h}</h3>
              <p>{v.p}</p>
            </Reveal>
          ))}
        </div>
      </div>

      {/* ---------- THE AGENTS ---------- */}
      <section>
        <div className="wrap">
          <Reveal>
            <p className="eyebrow">One brain, one agent at a time</p>
            <h2 className="h2" style={{ maxWidth: "18ch" }}>
              Five agents that run the desk. The first one's already working.
            </h2>
            <p className="lead" style={{ marginTop: 14 }}>
              Each agent owns one job a promoter holds in their head — and reports into the same morning brief, so the
              whole business arrives in one thread instead of seven screens.
            </p>
          </Reveal>

          <div className="agents">
            {AGENTS.map((a, i) => (
              <Reveal key={a.no} className={`agent${i % 2 ? " rev" : ""}`}>
                <div className="agent-copy">
                  <div className="agent-no">
                    {a.no}
                    <span className={`st ${a.live ? "live" : "soon"}`}>{a.live ? "Live" : a.when}</span>
                  </div>
                  <h3>{a.title}</h3>
                  {a.engine && <p className="engine">{a.engine}</p>}
                  <p>{a.body}</p>
                </div>
                <div className="agent-mock">{a.mock}</div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ---------- ASK ANYTHING ---------- */}
      <section className="surface-band">
        <div className="wrap ask">
          <Reveal>
            <p className="eyebrow">Every morning, 8:00 AM</p>
            <h2 className="h2">It opens the day for you, then answers whatever you ask next.</h2>
            <div className="qa">
              <div className="qa-row">
                <div className="qa-q">"Make a quote for ABC Infra — 20 MT TMT"</div>
                <div className="qa-a">
                  Priced at <span className="num">₹56,200/MT</span> (3.1% margin) against your stock and ABC's past rates —
                  draft waiting in your inbox.
                </div>
              </div>
              <div className="qa-row">
                <div className="qa-q">"Who should I follow up with today?"</div>
                <div className="qa-a">
                  Three parties, <span className="num">₹78L</span> overdue — ABC Infra <span className="num">₹42L</span>{" "}
                  first; it pays ~12 days late, so now is right.
                </div>
              </div>
              <div className="qa-row">
                <div className="qa-q">"Will I be short on cash next week?"</div>
                <div className="qa-a">
                  Yes — <span className="num">₹80L</span> short if XYZ Builders slips its <span className="num">₹18L</span>.
                  Chase it today and you're clear.
                </div>
              </div>
            </div>
          </Reveal>
          <Reveal delay={120} className="ask-phone">
            <Phone
              status="Business account"
              startInView
              lines={[
                { html: "<b>You:</b> Make a quote for ABC Infra — 20 MT TMT", cls: "user", max: "88%" },
                {
                  lbl: "Sales",
                  cls: "b-sales",
                  html: 'Ready: <span class="num">₹56,200/MT</span>, 3.1% margin. Draft in your inbox — approve to send.',
                },
                { html: "<b>You:</b> Who should I follow up with today?", cls: "user", max: "88%" },
                {
                  lbl: "Collections",
                  cls: "b-coll",
                  html: '3 parties, <span class="num">₹78L</span>. Start with <b>ABC Infra</b> — <span class="num">₹42L</span>.',
                },
              ]}
            />
          </Reveal>
        </div>
      </section>

      {/* ---------- OUTCOMES ---------- */}
      <section>
        <div className="wrap">
          <Reveal>
            <p className="eyebrow">Why it pays for itself</p>
            <h2 className="h2">The maths of a slow quote and a late rupee.</h2>
          </Reveal>
          <div className="outs">
            <Reveal delay={60} className="out">
              <div className="out-big">
                <CountUp to={5} prefix="2–" />
                <span className="u">orders/mo</span>
              </div>
              <h3>Fewer lost deals</h3>
              <p>Faster replies and follow-ups win back enquiries that used to go cold while you were on site.</p>
            </Reveal>
            <Reveal delay={140} className="out">
              <div className="out-big">
                <svg className="out-trend" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.6} aria-hidden="true">
                  <path d="M5 8l7 8 7-8" />
                </svg>
                <CountUp to={5} />
                <span className="u">days faster</span>
              </div>
              <h3>Cash in sooner</h3>
              <p>Collecting on time pulls your receivables days (DSO) down — chasing the right customer at the right moment, week on week.</p>
            </Reveal>
            <Reveal delay={220} className="out">
              <div className="out-big">
                <CountUp to={100} />
                <span className="u">days</span>
              </div>
              <h3>No stock left to rot</h3>
              <p>Aging material is flagged with the buyers most likely to take it — before it ties up your capital.</p>
            </Reveal>
          </div>
        </div>
      </section>

      {/* ---------- CLOSER ---------- */}
      <section className="closer-band">
        <div className="wrap closer">
          <Reveal>
            <p className="eyebrow" style={{ color: "var(--saffron)" }}>
              Built for ₹100–500 Cr distributors
            </p>
            <h2 className="h2" style={{ color: "#fff", maxWidth: "18ch", margin: "0 auto 12px" }}>
              Stop holding the whole business in your head.
            </h2>
            <p style={{ color: "#eacfc3", maxWidth: "42ch", margin: "0 auto 26px", fontSize: 16 }}>
              Connect Tally, WhatsApp and Gmail once. Tomorrow morning, read the brief instead of chasing it.
            </p>
            <Link className="btn btn-go" to="/contact">
              Request a design-partner slot
            </Link>
          </Reveal>
        </div>
      </section>
    </>
  );
}
