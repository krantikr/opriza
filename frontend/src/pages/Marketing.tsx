/* ---------------------------------------------------------------------------
   The public site at "/".

   Built from the product's own identity, not a separate one. The logo is a
   navy family around #18416B, the app's brand is #2563EB on slate, so this
   page lives there too - deeper ground, same blues, so a visitor who signs in
   lands somewhere that feels like the place they were just looking at.

   The copy is trade-agnostic: tDesk suits any desk that quotes from stock.
   The screenshots happen to show a steel desk because that is the demo data,
   and they are labelled as one worked example rather than the only market.
   Typography is the app's own Inter for text, with Archivo for display, so
   the two read as one company.

   Styles are scoped under `.mk` so nothing here reaches the desk's tokens and
   nothing of the desk's reaches this.

   Signed-in traders never see this - `App` sends them to the dashboard - so
   the daily habit of opening the root URL is unchanged.

   Motion is doing a job: the hero replays the actual 131 seconds between an
   enquiry landing and a quotation being ready, which is the single claim the
   product rests on. Everything resolves instantly under
   `prefers-reduced-motion`.
   --------------------------------------------------------------------------- */

import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

const SHOTS = {
  inbox: "/shot-inbox.webp",
  pricing: "/shot-pricing.webp",
  quotations: "/shot-quotations.webp",
  followups: "/shot-followups.webp",
  stock: "/shot-stock.webp",
  reports: "/shot-reports.webp",
  dashboard: "/shot-dashboard.webp",
};

const reduced = () =>
  typeof window !== "undefined" &&
  window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/* --- Motion primitives ---------------------------------------------------- */

function useReveal<T extends HTMLElement>(delay = 0) {
  const ref = useRef<T>(null);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    if (reduced()) {
      setShown(true);
      return;
    }
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          window.setTimeout(() => setShown(true), delay);
          io.disconnect();
        }
      },
      { threshold: 0.12, rootMargin: "0px 0px -70px 0px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [delay]);

  return { ref, shown };
}

function Reveal({
  children,
  delay = 0,
  className = "",
}: {
  children: React.ReactNode;
  delay?: number;
  className?: string;
}) {
  const { ref, shown } = useReveal<HTMLDivElement>(delay);
  return (
    <div ref={ref} className={`mk-rv${shown ? " mk-in" : ""} ${className}`.trim()}>
      {children}
    </div>
  );
}

function Count({ to, duration = 1500 }: { to: number; duration?: number }) {
  const { ref, shown } = useReveal<HTMLSpanElement>();
  const [n, setN] = useState(0);

  useEffect(() => {
    if (!shown) return;
    if (reduced()) {
      setN(to);
      return;
    }
    let raf = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      setN(to * (t === 1 ? 1 : 1 - Math.pow(2, -10 * t)));
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [shown, to, duration]);

  return <span ref={ref}>{Math.round(n).toLocaleString("en-IN")}</span>;
}

/* --- Hero sequence -------------------------------------------------------- */

const STEPS = [
  {
    label: "00:00",
    what: "The enquiry lands",
    detail: (
      <>
        <b>“IS2062 E250BR Plate 12 × 2000 × 6300 mm”</b> — 51.4 MT for a works in
        Rourkela, twentieth mail of the morning.
      </>
    ),
  },
  {
    label: "00:08",
    what: "Read, filed, justified",
    detail: (
      <>
        Logged as an enquiry at <b>95% confidence</b>, showing the sentence it judged
        on — so you can overrule it.
      </>
    ),
  },
  {
    label: "00:41",
    what: "Matched against your stock",
    detail: (
      <>
        Grade, thickness, width, length — checked against <b>every lot you hold</b>,
        with ageing and free-to-sell.
      </>
    ),
  },
  {
    label: "02:11",
    what: "Priced, drafted, waiting",
    detail: (
      <>
        Landed cost, freight, financing, margin — built line by line as{" "}
        <b>MS-002417</b> at ₹66,500/MT, reply written.
      </>
    ),
  },
];

function Sequence() {
  const [step, setStep] = useState(reduced() ? STEPS.length - 1 : -1);
  const [clock, setClock] = useState(reduced() ? 131.4 : 0);

  useEffect(() => {
    if (reduced()) return;
    let raf = 0;
    let timers: number[] = [];
    let cancelled = false;

    const run = () => {
      setStep(-1);
      setClock(0);
      timers = STEPS.map((_, i) =>
        window.setTimeout(() => !cancelled && setStep(i), 450 + i * 950),
      );
      const start = performance.now();
      const dur = 450 + STEPS.length * 950;
      const tick = (now: number) => {
        const t = Math.min(1, (now - start) / dur);
        setClock(131.4 * (1 - Math.pow(1 - t, 2)));
        if (t < 1 && !cancelled) raf = requestAnimationFrame(tick);
      };
      raf = requestAnimationFrame(tick);
      timers.push(window.setTimeout(run, dur + 7000));
    };

    run();
    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
      timers.forEach(clearTimeout);
    };
  }, []);

  const mm = String(Math.floor(clock / 60)).padStart(2, "0");
  const ss = String(Math.floor(clock % 60)).padStart(2, "0");

  return (
    <div className="mk-seq">
      <div className="mk-seq-head">
        <span className="mk-seq-title">
          <span className="mk-live" aria-hidden="true" />
          Enquiry to quotation
        </span>
        <span className="mk-seq-clock">
          {mm}:{ss}
        </span>
      </div>

      <div className="mk-seq-track" aria-hidden="true">
        <span
          className="mk-seq-fill"
          style={{ transform: `scaleX(${Math.min(1, clock / 131.4)})` }}
        />
      </div>

      {STEPS.map((s, i) => (
        <div key={s.label} className={`mk-step${i <= step ? " mk-on" : ""}`}>
          <div className="mk-step-t">{s.label}</div>
          <div>
            <div className="mk-step-what">{s.what}</div>
            <div className="mk-step-detail">{s.detail}</div>
          </div>
        </div>
      ))}

      <p className="mk-byhand">
        By hand: open the mail, find the sizes, check the stock sheet, work out the
        landed cost, type the quotation, remember to chase it.{" "}
        <b>Most desks take a day.</b>
      </p>
    </div>
  );
}

/* --- Product tour --------------------------------------------------------- */

const TOUR = [
  {
    key: "inbox",
    tab: "Inbox",
    eyebrow: "Enquiries",
    title: "It reads the mail, and shows its working.",
    body: "Enquiries, follow-ups, delivery questions and complaints are sorted the moment they arrive. Every decision carries its confidence and the reason behind it — the software argues its case rather than asking for trust.",
    points: [
      <>
        Quotation requests become <b>numbered quotations automatically</b>
      </>,
      <>A tab for what needs a reply, and it empties as you answer</>,
      <>Attachments and PDF enquiries read too, not just the mail body</>,
    ],
    shot: SHOTS.inbox,
    alt: "The tDesk inbox: an enquiry classified at 95% confidence, with the reason it was filed there and the quotation it created.",
  },
  {
    key: "pricing",
    tab: "Pricing",
    eyebrow: "Pricing",
    title: "Every rupee in the quote, and where it came from.",
    body: "The price is built in front of you: landed cost of the lot, transport, loading, financing against your credit terms, a risk buffer, then your target margin. Override any line and the reason is recorded against the quotation.",
    points: [
      <>
        Compare <b>up to three despatch locations side by side</b>
      </>,
      <>Pick the column you are sending; it locks once the quote goes out</>,
      <>Margin floors that warn before a line goes out under cost</>,
    ],
    shot: SHOTS.pricing,
    alt: "The pricing calculator showing the full cost build-up from landed cost through freight, financing and margin to the recommended quote price.",
  },
  {
    key: "quotations",
    tab: "Quotations",
    eyebrow: "The pipeline",
    title: "Every enquiry on one sheet, in the shape a trader reads.",
    body: "Grade, type, size, weight, make and price — one row per material, the way it appears on a stock sheet. Move a deal through received, sent, negotiation, delivery and payment from the same dropdown.",
    points: [
      <>
        Cards across the top show <b>what is stuck and why</b>
      </>,
      <>Priority customers and flagged grades highlighted on sight</>,
      <>Export the filtered view to Excel — what you see is what exports</>,
    ],
    shot: SHOTS.quotations,
    alt: "The quotations table: one row per material with grade, size, weight, price and a stage dropdown per deal.",
  },
  {
    key: "followups",
    tab: "Follow-ups",
    eyebrow: "Follow-ups",
    title: "Nothing goes cold because everyone assumed someone else called.",
    body: "The moment a quotation goes out it appears here, newest movement at the top, and it stays until the money is in. Open a row and the whole conversation is there with a follow-up already drafted.",
    points: [
      <>
        Grouped by <b>follow-up, negotiation, pending PO and payment</b> — with the
        quantity and value in each
      </>,
      <>A customer who replied and was never answered is the top row</>,
      <>Snooze to a date, or mark lost with the reason</>,
    ],
    shot: SHOTS.followups,
    alt: "The follow-ups board grouped by stage, showing tonnage and value per stage with the most recently active deal at the top.",
  },
  {
    key: "stock",
    tab: "Stock",
    eyebrow: "Stock",
    title: "Have, owe, free and short — not one misleading number.",
    body: "A single “in stock” figure is how a desk sells the same unit twice. tDesk keeps what you hold, what is already promised, what is genuinely free to sell, and what you are short.",
    points: [
      <>
        Load your existing sheet — <b>import straight from Excel</b>
      </>,
      <>Landed cost carried per lot, which is what pricing reads</>,
      <>Ageing on every lot, so slow stock is visible before it is a write-down</>,
    ],
    shot: SHOTS.stock,
    alt: "The stock screen showing 907 MT in stock, 52 MT to deliver and 855 MT free to sell, with cost per tonne on every lot.",
  },
  {
    key: "reports",
    tab: "Reports",
    eyebrow: "The numbers",
    title: "A trading P&L your accountant recognises.",
    body: "Enquiry to quotation to sale to gross profit, each line a subset of the one above it, with the definitions printed underneath. Compared against the previous period, exportable as PDF or Excel.",
    points: [
      <>Win rate on decided quotes — not flattered by the ones still open</>,
      <>
        <b>Gross margin per unit</b>, from the landed cost actually recorded
      </>,
      <>Stock value and what share has been sitting over 90 days</>,
    ],
    shot: SHOTS.reports,
    alt: "The trading period report showing enquiry, sales, gross profit and stock sections with definitions printed under each.",
  },
  {
    key: "dashboard",
    tab: "Dashboard",
    eyebrow: "Every morning",
    title: "Open it once and know where the day's money is.",
    body: "Quantity in, quantity quoted, quantity ordered — and the funnel showing exactly which step is losing it. By volume, by value, or by count, because traders think in all three.",
    points: [
      <>
        What is waiting on <b>you</b>, before anything else
      </>,
      <>Payment funnel: money shipped and still owed, by how soon it is due</>,
      <>This period against last, so a bad week is visible while it is still a week</>,
    ],
    shot: SHOTS.dashboard,
    alt: "The dashboard showing enquiries received, quotations provided and orders received in tonnes, with a sales funnel and trend chart.",
  },
];

function Screen({ src, alt, bleed = false }: { src: string; alt: string; bleed?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);

  function move(e: React.MouseEvent) {
    if (reduced() || !ref.current) return;
    const r = ref.current.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width - 0.5;
    const y = (e.clientY - r.top) / r.height - 0.5;
    ref.current.style.transform = `perspective(1600px) rotateY(${x * 2.4}deg) rotateX(${-y * 2.4}deg)`;
  }
  function leave() {
    if (ref.current) ref.current.style.transform = "";
  }

  return (
    <div
      className={`mk-screen${bleed ? " mk-bleed" : ""}`}
      ref={ref}
      onMouseMove={move}
      onMouseLeave={leave}
    >
      <div className="mk-chrome">
        <span className="mk-dot" />
        <span className="mk-dot" />
        <span className="mk-dot" />
        <span className="mk-url">tdesk.app</span>
      </div>
      <img src={src} alt={alt} loading="lazy" />
    </div>
  );
}

function Tour() {
  const [active, setActive] = useState(0);
  const t = TOUR[active];

  return (
    <div className="mk-tour">
      <div className="mk-tabs" role="tablist" aria-label="Product screens">
        {TOUR.map((s, i) => (
          <button
            key={s.key}
            type="button"
            role="tab"
            aria-selected={i === active}
            className={`mk-tab${i === active ? " mk-tab-on" : ""}`}
            onClick={() => setActive(i)}
          >
            {s.tab}
          </button>
        ))}
      </div>

      <div className="mk-tour-body" key={t.key}>
        <div className="mk-tour-copy">
          <span className="mk-eyebrow">{t.eyebrow}</span>
          <h3>{t.title}</h3>
          <p>{t.body}</p>
          <ul className="mk-points">
            {t.points.map((p, i) => (
              <li key={i}>{p}</li>
            ))}
          </ul>
        </div>
        <Screen src={t.shot} alt={t.alt} />
      </div>
    </div>
  );
}

/* --- Content -------------------------------------------------------------- */

const svg = (d: React.ReactNode) => (
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.7"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    {d}
  </svg>
);

const AUTOS = [
  {
    icon: svg(
      <>
        <path d="M4 5h16l1 7v6a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-6z" />
        <path d="M3 12h4l2 3h6l2-3h4" />
      </>,
    ),
    title: "Mail checked on your schedule",
    body: "Your inbox is polled through the working day and goes quiet after hours — set the window per desk.",
  },
  {
    icon: svg(
      <>
        <path d="M6 2h8l5 5v15a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z" />
        <path d="M14 2v5h5M9 13h6M9 17h4" />
      </>,
    ),
    title: "The reply is written for you",
    body: "A quotation email drafted in your house style, with the priced PDF attached — edit it or send it as it stands.",
  },
  {
    icon: svg(
      <>
        <path d="M18 8a6 6 0 1 0-12 0c0 7-3 8-3 8h18s-3-1-3-8" />
        <path d="M13.7 21a2 2 0 0 1-3.4 0" />
      </>,
    ),
    title: "Told the moment it matters",
    body: "A customer accepts, a complaint arrives, a big enquiry lands — pushed to your phone even with the site closed.",
  },
  {
    icon: svg(
      <>
        <path d="M3 8l9-5 9 5-9 5-9-5z" />
        <path d="M3 12l9 5 9-5M3 16l9 5 9-5" />
      </>,
    ),
    title: "Prices follow the stock sheet",
    body: "Re-import your stock and open quotations re-price themselves. Sent ones never move — they are the record of what you offered.",
  },
  {
    icon: svg(
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </>,
    ),
    title: "Past orders on the same screen",
    body: "What this buyer paid last time, and how much they took, shown while you are deciding today's rate.",
  },
  {
    icon: svg(
      <>
        <circle cx="9" cy="8" r="3.5" />
        <path d="M3 20a6 6 0 0 1 12 0M17 11a3 3 0 1 0-2-5.2M21 20a5 5 0 0 0-4-4.9" />
      </>,
    ),
    title: "A desk per branch",
    body: "Each office sees only its own mail, stock and quotations. Separated in the database itself, not by a filter.",
  },
];

const LEAKS = [
  {
    n: "01",
    problem: "The enquiry sat for two days",
    answer:
      "Mail is read the moment it arrives and turned into a priced, drafted quotation. A day of work is waiting for you when you open the screen.",
  },
  {
    n: "02",
    problem: "Quoted below cost, found out later",
    answer:
      "Every quote is built from the landed cost of the actual lot, plus freight, handling, financing and your margin floor — line by line, so nothing goes out on a guess.",
  },
  {
    n: "03",
    problem: "Nobody chased it",
    answer:
      "Every sent quotation sits on one board, newest movement first, with the money at risk against it. Nothing goes cold in somebody's inbox.",
  },
  {
    n: "04",
    problem: "Sold the tonne you had already promised",
    answer:
      "Stock is tracked as have, owe, free and short — so the number you quote against is the tonnage you can actually deliver.",
  },
];

export default function Marketing() {
  const navigate = useNavigate();
  const login = () => navigate("/sign-in");
  const [stuck, setStuck] = useState(false);

  useEffect(() => {
    const onScroll = () => setStuck(window.scrollY > 640);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <div className="mk">
      <style>{CSS}</style>

      <div className={`mk-nav${stuck ? " mk-nav-on" : ""}`}>
        <div className="mk-wrap mk-nav-in">
          <a className="mk-brand" href="#top">
            <img className="mk-mark" src="/logo-mark-light.png" alt="" />
            <span>tDesk</span>
          </a>
          <div className="mk-nav-links">
            <a href="#problem">Why</a>
            <a href="#tour">Product</a>
            <a href="#automation">Automation</a>
            <button type="button" className="mk-btn mk-primary mk-sm" onClick={login}>
              Log in
            </button>
          </div>
        </div>
      </div>

      {/* --- Hero ------------------------------------------------------- */}
      <header className="mk-hero" id="top">
        <div className="mk-grid-bg" aria-hidden="true" />
        <div className="mk-glow" aria-hidden="true" />

        <div className="mk-wrap">
          <div className="mk-masthead">
            <a className="mk-brand mk-a1" href="#top">
              <img className="mk-mark" src="/logo-mark-light.png" alt="" />
              <span>tDesk</span>
            </a>
            <nav className="mk-mast-right mk-a1">
              <span className="mk-mast-note">Quotation &amp; sales automation for traders</span>
              <button type="button" className="mk-btn mk-outline mk-sm" onClick={login}>
                Log in
              </button>
            </nav>
          </div>

          <div className="mk-hero-grid">
            <div className="mk-hero-copy">
              <div className="mk-pill mk-a2">
                <span className="mk-live" aria-hidden="true" />
                Quotations, priced and drafted before you open the mail
              </div>
              <h1 className="mk-a3">
                Your next enquiry
                <br />
                is already <em>quoted</em>.
              </h1>
              <p className="mk-sub mk-a4">
                tDesk reads the enquiry out of your inbox, matches it against your own
                stock, prices it on your own rules, and puts a finished quotation in
                front of you. <strong>You review and send.</strong>
              </p>
              <div className="mk-cta mk-a5">
                <button type="button" className="mk-btn mk-primary" onClick={login}>
                  Log in to your desk
                  <span className="mk-arrow" aria-hidden="true">
                    →
                  </span>
                </button>
                <a className="mk-btn mk-outline" href="#tour">
                  See the product
                </a>
              </div>
              <p className="mk-trust mk-a5">
                Runs on your existing inbox and stock sheet · Nothing sends without you
              </p>
            </div>

            <div className="mk-a4">
              <Sequence />
            </div>
          </div>
        </div>

        {/* The dashboard bleeds off the right edge: the product itself is the
            closing image of the hero, not a framed illustration below it. */}
        <div className="mk-hero-shot mk-a5">
          <Screen
            src={SHOTS.dashboard}
            alt="The tDesk dashboard showing tonnage received, quoted and ordered, with the sales funnel and payment funnel."
            bleed
          />
        </div>
      </header>

      {/* --- Metrics ---------------------------------------------------- */}
      <section className="mk-strip">
        <div className="mk-wrap mk-strip-in">
          <Reveal>
            <div className="mk-stat">
              <div className="mk-stat-fig">
                <Count to={131} />
                <span>s</span>
              </div>
              <div className="mk-stat-l">Enquiry to a priced quotation</div>
            </div>
          </Reveal>
          <Reveal delay={90}>
            <div className="mk-stat">
              <div className="mk-stat-fig">
                <Count to={907} />
                <span> MT</span>
              </div>
              <div className="mk-stat-l">Matched spec by spec, lot by lot</div>
            </div>
          </Reveal>
          <Reveal delay={180}>
            <div className="mk-stat">
              <div className="mk-stat-fig">
                <Count to={6} />
              </div>
              <div className="mk-stat-l">Stages, enquiry through payment</div>
            </div>
          </Reveal>
          <Reveal delay={270}>
            <div className="mk-stat">
              <div className="mk-stat-fig mk-good">
                <Count to={100} />
                <span>%</span>
              </div>
              <div className="mk-stat-l">Sent by a human, after review</div>
            </div>
          </Reveal>
        </div>
      </section>

      {/* --- Problem ---------------------------------------------------- */}
      <section className="mk-band" id="problem">
        <div className="mk-wrap">
          <Reveal className="mk-head">
            <span className="mk-eyebrow">Where the money goes</span>
            <h2>Deals are not lost on price. They are lost on the days in between.</h2>
            <p className="mk-lede">
              Every trading desk knows where the leaks are. None of it is a mystery — it
              is the work between an enquiry arriving and somebody finding time to
              answer it.
            </p>
          </Reveal>

          <div className="mk-leaks">
            {LEAKS.map((l, i) => (
              <Reveal key={l.n} delay={i * 80}>
                <div className="mk-leak">
                  <span className="mk-leak-n">{l.n}</span>
                  <div className="mk-leak-p">{l.problem}</div>
                  <p className="mk-leak-a">{l.answer}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* --- Tour ------------------------------------------------------- */}
      <section className="mk-band mk-dark" id="tour">
        <div className="mk-grid-bg" aria-hidden="true" />
        <div className="mk-wrap">
          <Reveal className="mk-head mk-centre">
            <span className="mk-eyebrow">The product</span>
            <h2>Seven screens, and the whole desk runs on them.</h2>
            <p className="mk-lede">
              Not a CRM you have to feed. The work arrives by email, and every screen is
              filled in before you open it.
            </p>
          </Reveal>
          <Reveal delay={100}>
            <Tour />
          </Reveal>
        </div>
      </section>

      {/* --- Automation ------------------------------------------------- */}
      <section className="mk-band" id="automation">
        <div className="mk-wrap">
          <Reveal className="mk-head">
            <span className="mk-eyebrow">Running quietly</span>
            <h2>The parts that work while nobody is looking.</h2>
            <p className="mk-lede">
              Automation that removes typing, not judgement. Every figure that reaches a
              customer has been approved by a person first.
            </p>
          </Reveal>

          <div className="mk-autos">
            {AUTOS.map((a, i) => (
              <Reveal key={a.title} delay={(i % 3) * 80}>
                <div className="mk-auto">
                  <div className="mk-auto-i" aria-hidden="true">
                    {a.icon}
                  </div>
                  <h4>{a.title}</h4>
                  <p>{a.body}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* --- Close ------------------------------------------------------ */}
      <section className="mk-close">
        <div className="mk-grid-bg" aria-hidden="true" />
        <div className="mk-glow mk-glow-b" aria-hidden="true" />
        <div className="mk-narrow">
          <Reveal>
            <span className="mk-eyebrow">See it on your own enquiries</span>
            <h2>
              Bring one week of your inbox. We will show you the quotations it would
              have written.
            </h2>
            <p className="mk-lede">
              No migration, no re-keying, and your existing stock sheet loads as it is.
              The fastest way to judge this is to point it at mail you have already
              answered.
            </p>
            <div className="mk-cta mk-centre">
              <button type="button" className="mk-btn mk-primary" onClick={login}>
                Log in to your desk
                <span className="mk-arrow" aria-hidden="true">
                  →
                </span>
              </button>
              <a className="mk-btn mk-outline" href="#tour">
                Review the product
              </a>
            </div>
          </Reveal>
        </div>

        <div className="mk-wrap mk-foot">
          <a className="mk-brand" href="#top">
            <img className="mk-mark" src="/logo-mark-light.png" alt="" />
            <span>tDesk</span>
          </a>
          <p>
            Screens show a demonstration desk with fictional buyers and prices — one worked example of a trade tDesk handles.
          </p>
        </div>
      </section>
    </div>
  );
}

const CSS = `
@import url('https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@75..125,400..800&display=swap');

.mk {
  /* Light: the app's own slate family, one step cooler. */
  --ground:   #FFFFFF;
  --raise:    #F8FAFC;
  --sunk:     #F1F5F9;
  --line:     #E2E8F0;
  --line-2:   #CBD5E1;
  --ink:      #0F172A;
  --ink-2:    #475569;
  --ink-3:    #94A3B8;

  --brand:    #2563EB;
  --brand-2:  #1D4ED8;
  --brand-3:  #60A5FA;
  --wash:     #EFF6FF;
  --navy:     #18416B;   /* straight from the logo */
  --good:     #059669;

  /* Dark sections, deeper than the app so signing in feels like stepping up. */
  --deep:     #070C16;
  --deep-2:   #0B1220;
  --deep-ink: #F8FAFC;
  --deep-2ink:#94A3B8;
  --deep-line:#1B2536;

  background: var(--ground);
  color: var(--ink);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  font-size: 16.5px;
  line-height: 1.6;
  min-height: 100vh;
  overflow-x: hidden;
  -webkit-font-smoothing: antialiased;
  letter-spacing: -0.005em;
}

@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) .mk {
    --ground:  #070C16;
    --raise:   #0D1524;
    --sunk:    #0B1220;
    --line:    #1B2536;
    --line-2:  #2A3648;
    --ink:     #F8FAFC;
    --ink-2:   #94A3B8;
    --ink-3:   #64748B;
    --brand:   #3B82F6;
    --brand-2: #60A5FA;
    --wash:    #0E1B33;
  }
}
:root[data-theme="dark"] .mk {
  --ground:  #070C16;
  --raise:   #0D1524;
  --sunk:    #0B1220;
  --line:    #1B2536;
  --line-2:  #2A3648;
  --ink:     #F8FAFC;
  --ink-2:   #94A3B8;
  --ink-3:   #64748B;
  --brand:   #3B82F6;
  --brand-2: #60A5FA;
  --wash:    #0E1B33;
}

.mk *, .mk *::before, .mk *::after { box-sizing: border-box; }

.mk h1, .mk h2, .mk h3, .mk h4 {
  font-family: Archivo, Inter, system-ui, sans-serif;
  font-variation-settings: "wdth" 108;
  text-wrap: balance;
  margin: 0;
  letter-spacing: -0.028em;
}

.mk-wrap   { width: min(1200px, 90vw); margin-inline: auto; }
.mk-narrow { width: min(760px, 90vw); margin-inline: auto; position: relative; }

.mk-eyebrow {
  display: block; font-size: 11.5px; font-weight: 600;
  letter-spacing: 0.14em; text-transform: uppercase; color: var(--brand);
}

/* --- Motion --- */
@keyframes mk-rise { from { opacity: 0; transform: translateY(20px); } to { opacity: 1; transform: none; } }
.mk-a1,.mk-a2,.mk-a3,.mk-a4,.mk-a5 { animation: mk-rise 0.78s cubic-bezier(0.16,1,0.3,1) both; }
.mk-a1 { animation-delay: 0.04s; }
.mk-a2 { animation-delay: 0.14s; }
.mk-a3 { animation-delay: 0.22s; }
.mk-a4 { animation-delay: 0.34s; }
.mk-a5 { animation-delay: 0.46s; }

.mk-rv { opacity: 0; transform: translateY(24px);
  transition: opacity 0.7s cubic-bezier(0.16,1,0.3,1), transform 0.7s cubic-bezier(0.16,1,0.3,1); }
.mk-rv.mk-in { opacity: 1; transform: none; }

/* --- Backdrops --- */
.mk-grid-bg {
  position: absolute; inset: 0; pointer-events: none;
  background-image:
    linear-gradient(to right, rgba(148,163,184,0.07) 1px, transparent 1px),
    linear-gradient(to bottom, rgba(148,163,184,0.07) 1px, transparent 1px);
  background-size: 72px 72px;
  mask-image: radial-gradient(120% 90% at 50% 0%, #000 35%, transparent 78%);
  -webkit-mask-image: radial-gradient(120% 90% at 50% 0%, #000 35%, transparent 78%);
}
.mk-glow {
  position: absolute; inset: 0; pointer-events: none;
  background:
    radial-gradient(760px 420px at 84% 4%, rgba(37,99,235,0.30), transparent 62%),
    radial-gradient(620px 380px at 8% 42%, rgba(24,65,107,0.35), transparent 66%);
}
.mk-glow-b { background: radial-gradient(720px 400px at 50% 100%, rgba(37,99,235,0.24), transparent 66%); }

/* --- Nav --- */
/* The bar crosses light and dark bands as you scroll, so it is always the
   dark glass rather than following the light theme's ground - a white bar
   sliding over the dark product section reads as a rendering fault. */
.mk-nav {
  position: fixed; inset: 0 0 auto 0; z-index: 50;
  background: rgba(7,12,22,0.90);
  backdrop-filter: saturate(160%) blur(20px);
  -webkit-backdrop-filter: saturate(160%) blur(20px);
  border-bottom: 1px solid rgba(255,255,255,0.07);
  box-shadow: 0 8px 30px -18px rgba(7,12,22,0.9);
  transform: translateY(-101%);
  transition: transform 0.44s cubic-bezier(0.16,1,0.3,1);
}
.mk-nav-on { transform: none; }
.mk-nav-in { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 10px 0; }
.mk-nav .mk-brand { color: #F8FAFC; }
.mk-nav-links { display: flex; align-items: center; gap: 26px; }
.mk-nav-links a {
  font-size: 14px; font-weight: 500; color: #94A3B8; text-decoration: none;
  transition: color 0.16s ease;
}
.mk-nav-links a:hover { color: #93C5FD; }
@media (max-width: 780px) { .mk-nav-links a { display: none; } }

/* --- Brand --- */
.mk-brand {
  display: inline-flex; align-items: center; gap: 10px; text-decoration: none;
  font-family: Archivo, Inter, sans-serif; font-variation-settings: "wdth" 112;
  font-weight: 700; font-size: 18px; letter-spacing: -0.02em; color: var(--deep-ink);
}
.mk-mark { width: 34px; height: 34px; object-fit: contain; display: block; flex: none; }
.mk-nav .mk-mark { width: 30px; height: 30px; }

/* --- Hero --- */
.mk-hero {
  position: relative; overflow: hidden;
  background: var(--deep); color: var(--deep-ink);
  padding: clamp(18px, 3vw, 32px) 0 0;
}
.mk-hero > * { position: relative; }
.mk-masthead {
  display: flex; align-items: center; justify-content: space-between;
  gap: 20px; flex-wrap: wrap; padding-bottom: clamp(40px, 7vw, 84px);
}
.mk-mast-right { display: flex; align-items: center; gap: 20px; }
.mk-mast-note { font-size: 13.5px; color: var(--deep-2ink); }
@media (max-width: 780px) { .mk-mast-note { display: none; } }

.mk-hero-grid {
  display: grid; grid-template-columns: minmax(0,1.02fr) minmax(0,0.98fr);
  gap: clamp(34px, 4.5vw, 62px); align-items: start;
  padding-bottom: clamp(46px, 6vw, 76px);
}
@media (max-width: 980px) { .mk-hero-grid { grid-template-columns: 1fr; } }

.mk-pill {
  display: inline-flex; align-items: center; gap: 9px;
  padding: 7px 15px 7px 11px; border-radius: 999px;
  border: 1px solid var(--deep-line); background: rgba(37,99,235,0.07);
  font-size: 12.5px; color: var(--deep-2ink); margin-bottom: 24px;
}
.mk-live {
  width: 6px; height: 6px; border-radius: 999px; background: var(--brand-3); flex: none;
  animation: mk-pulse 2.6s ease-out infinite;
}
@keyframes mk-pulse {
  0%   { box-shadow: 0 0 0 0 rgba(96,165,250,0.6); }
  70%  { box-shadow: 0 0 0 8px rgba(96,165,250,0); }
  100% { box-shadow: 0 0 0 0 rgba(96,165,250,0); }
}

.mk h1 {
  font-size: clamp(40px, 5.6vw, 70px); line-height: 1.02; font-weight: 700;
  font-variation-settings: "wdth" 112; letter-spacing: -0.035em;
}
.mk h1 em { font-style: normal; position: relative; white-space: nowrap;
  background: linear-gradient(96deg, var(--brand-3), #93C5FD);
  -webkit-background-clip: text; background-clip: text; color: transparent;
}
.mk h1 em::after {
  content: ""; position: absolute; left: 0; right: 0; bottom: -0.06em; height: 2px;
  background: linear-gradient(90deg, var(--brand), transparent);
  transform-origin: left; transform: scaleX(0);
  animation: mk-ul 0.9s cubic-bezier(0.16,1,0.3,1) 0.95s forwards;
}
@keyframes mk-ul { to { transform: scaleX(1); } }

.mk-sub {
  margin: 24px 0 0; font-size: clamp(17px, 1.9vw, 19px); line-height: 1.58;
  color: var(--deep-2ink); max-width: 33em;
}
.mk-sub strong { color: var(--deep-ink); font-weight: 600; }

.mk-cta { margin-top: 32px; display: flex; gap: 11px; flex-wrap: wrap; align-items: center; }
.mk-centre { justify-content: center; }
.mk-trust { margin: 16px 0 0; font-size: 12.5px; color: var(--ink-3); }
.mk-hero .mk-trust { color: #64748B; }

.mk-btn {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 13px 22px; border-radius: 8px; border: 1px solid transparent;
  font-family: Inter, sans-serif; font-size: 14.5px; font-weight: 600;
  letter-spacing: -0.01em; text-decoration: none; cursor: pointer;
  transition: transform 0.18s cubic-bezier(0.16,1,0.3,1), background 0.18s ease,
              border-color 0.18s ease, box-shadow 0.18s ease;
}
.mk-btn:focus-visible { outline: 2px solid var(--brand-3); outline-offset: 3px; }
.mk-primary {
  background: var(--brand); color: #fff;
  box-shadow: 0 1px 0 rgba(255,255,255,0.14) inset, 0 10px 26px -12px rgba(37,99,235,0.9);
}
.mk-primary:hover {
  background: var(--brand-2); transform: translateY(-2px);
  box-shadow: 0 1px 0 rgba(255,255,255,0.14) inset, 0 18px 34px -14px rgba(37,99,235,0.95);
}
.mk-arrow { transition: transform 0.2s ease; }
.mk-primary:hover .mk-arrow { transform: translateX(3px); }
.mk-outline { color: var(--deep-ink); border-color: var(--deep-line); background: rgba(255,255,255,0.02); }
.mk-outline:hover { border-color: #33415A; background: rgba(255,255,255,0.05); transform: translateY(-1px); }
.mk-sm { padding: 9px 16px; font-size: 13.5px; }

/* --- Sequence --- */
.mk-seq {
  border: 1px solid var(--deep-line); border-radius: 12px;
  background: linear-gradient(180deg, rgba(255,255,255,0.035), rgba(255,255,255,0.012));
  padding: 20px 22px 16px; box-shadow: 0 34px 70px -38px rgba(0,0,0,0.95);
}
.mk-seq-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.mk-seq-title {
  display: inline-flex; align-items: center; gap: 9px;
  font-size: 11.5px; font-weight: 600; letter-spacing: 0.13em;
  text-transform: uppercase; color: var(--deep-2ink);
}
.mk-seq-clock {
  font-family: ui-monospace, "SF Mono", Menlo, monospace; font-variant-numeric: tabular-nums;
  font-size: 14px; font-weight: 600; color: var(--brand-3);
}
.mk-seq-track { height: 2px; background: var(--deep-line); border-radius: 2px; margin: 13px 0 4px; overflow: hidden; }
.mk-seq-fill {
  display: block; height: 100%; transform-origin: left; transform: scaleX(0);
  background: linear-gradient(90deg, var(--brand), var(--brand-3));
}

.mk-step {
  display: grid; grid-template-columns: 54px 1fr; gap: 14px;
  padding: 13px 0; border-bottom: 1px solid var(--deep-line); align-items: start;
  opacity: 0.26; transform: translateY(5px);
  transition: opacity 0.5s ease, transform 0.5s cubic-bezier(0.16,1,0.3,1);
}
.mk-step:last-of-type { border-bottom: 0; }
.mk-step.mk-on { opacity: 1; transform: none; }
.mk-step-t {
  font-family: ui-monospace, "SF Mono", Menlo, monospace; font-variant-numeric: tabular-nums;
  font-size: 11.5px; color: var(--brand-3); padding-top: 2px;
}
.mk-step-what { font-size: 14.5px; font-weight: 600; color: var(--deep-ink); line-height: 1.35; }
.mk-step-detail { font-size: 13.5px; color: var(--deep-2ink); line-height: 1.5; margin-top: 3px; }
.mk-step-detail b { color: #CBD5E1; font-weight: 600; }
.mk-byhand {
  margin: 14px 0 0; padding-top: 13px; border-top: 1px dashed var(--deep-line);
  font-size: 13px; color: #64748B; line-height: 1.5;
}
.mk-byhand b { color: var(--deep-2ink); font-weight: 600; }

/* --- Hero screenshot, bleeding right --- */
/* The product laid back on its edge, sinking into the next section.

   A straight crop was tried first and read as a broken image: the app is
   white, so fading white into a dark ground leaves a hard grey seam whatever
   the mask does. Tilting it away instead gives the cut a reason to exist -
   the screen is receding, not severed - and the glow underneath carries the
   eye down into the stat strip. */
.mk-hero-shot {
  width: min(1240px, 92vw); margin: 0 auto;
  perspective: 2200px;
  max-height: clamp(210px, 30vh, 320px);
  position: relative;
}
.mk-hero-shot .mk-screen {
  transform: rotateX(28deg) scale(1.01);
  transform-origin: 50% 0%;
  border-radius: 14px 14px 0 0;
  box-shadow: 0 60px 90px -40px rgba(0,0,0,0.9), 0 0 0 1px rgba(148,163,184,0.10);
}
/* A soft floor light so the tilt reads as depth rather than a squashed image. */
.mk-hero-shot::after {
  content: ""; position: absolute; left: 8%; right: 8%; bottom: -26px; height: 120px;
  background: radial-gradient(60% 100% at 50% 0%, rgba(37,99,235,0.30), transparent 70%);
  filter: blur(14px); pointer-events: none;
}
@media (max-width: 980px) {
  .mk-hero-shot { max-height: clamp(150px, 24vh, 220px); }
  .mk-hero-shot .mk-screen { transform: rotateX(32deg) scale(1.03); }
}

/* --- Screens --- */
.mk-screen {
  background: #0D1524; border: 1px solid var(--deep-line);
  border-radius: 12px 12px 0 0; overflow: hidden;
  box-shadow: 0 40px 80px -34px rgba(0,0,0,0.8);
  transition: transform 0.3s cubic-bezier(0.16,1,0.3,1); will-change: transform;
}
.mk-screen:not(.mk-bleed) { border-radius: 12px; }
.mk-chrome { display: flex; align-items: center; gap: 7px; padding: 10px 14px; border-bottom: 1px solid var(--deep-line); }
.mk-dot { width: 9px; height: 9px; border-radius: 999px; background: #223046; }
.mk-url {
  margin-left: 10px; flex: 1; max-width: 260px; padding: 3px 12px; border-radius: 999px;
  background: rgba(255,255,255,0.045); color: #64748B;
  font-family: ui-monospace, Menlo, monospace; font-size: 10.5px;
}
.mk-screen img { display: block; width: 100%; height: auto; }

/* --- Stat strip --- */
.mk-strip {
  background: var(--deep-2); border-top: 1px solid var(--deep-line);
  position: relative; z-index: 2;
  box-shadow: 0 -30px 50px -20px var(--deep-2);
}
.mk-strip-in {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: clamp(20px, 3vw, 44px); padding: clamp(30px, 4vw, 46px) 0;
}
.mk-stat-fig {
  font-family: Archivo, Inter, sans-serif; font-variation-settings: "wdth" 112;
  font-variant-numeric: tabular-nums; font-size: clamp(30px, 3.6vw, 40px);
  font-weight: 700; line-height: 1; letter-spacing: -0.035em; color: var(--deep-ink);
}
.mk-stat-fig span { color: var(--brand-3); }
.mk-stat-fig.mk-good, .mk-stat-fig.mk-good span { color: #34D399; }
.mk-stat-l { margin-top: 10px; font-size: 13.5px; color: var(--deep-2ink); line-height: 1.45; }

/* --- Bands --- */
.mk-band { padding: clamp(66px, 8.5vw, 118px) 0; position: relative; }
.mk-band.mk-dark { background: var(--deep); color: var(--deep-ink); overflow: hidden; }
.mk-band.mk-dark > * { position: relative; }
.mk-band.mk-dark .mk-lede { color: var(--deep-2ink); }

.mk h2 {
  font-size: clamp(28px, 3.7vw, 44px); line-height: 1.08; font-weight: 700;
  font-variation-settings: "wdth" 108; letter-spacing: -0.03em;
}
.mk-lede { margin: 16px 0 0; font-size: clamp(16.5px, 1.8vw, 18.5px); color: var(--ink-2); max-width: 42em; line-height: 1.6; }
.mk-head { margin-bottom: clamp(38px, 5vw, 60px); }
.mk-head .mk-eyebrow { margin-bottom: 13px; }
.mk-centre { text-align: center; }
.mk-head.mk-centre .mk-lede { margin-inline: auto; }

/* --- Leaks --- */
.mk-leaks { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; background: var(--line); border: 1px solid var(--line); border-radius: 12px; overflow: hidden; }
.mk-leaks > * { height: 100%; }
.mk-leak { background: var(--ground); padding: 30px 26px 34px; height: 100%; transition: background 0.22s ease; }
@media (max-width: 1040px) { .mk-leaks { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 560px)  { .mk-leaks { grid-template-columns: 1fr; } }
.mk-leak:hover { background: var(--raise); }
.mk-leak-n {
  font-family: ui-monospace, Menlo, monospace; font-size: 12px; font-weight: 600;
  color: var(--brand); display: block; margin-bottom: 14px; letter-spacing: 0.04em;
}
.mk-leak-p { font-size: 18px; font-weight: 600; line-height: 1.3; color: var(--ink); margin-bottom: 11px; letter-spacing: -0.015em; }
.mk-leak-a { margin: 0; font-size: 15px; line-height: 1.58; color: var(--ink-2); }

/* --- Tour --- */
.mk-tabs {
  display: flex; gap: 4px; flex-wrap: wrap; justify-content: center;
  margin: 0 auto clamp(30px, 4vw, 48px); padding: 4px;
  border: 1px solid var(--deep-line); border-radius: 999px;
  background: rgba(255,255,255,0.03); width: fit-content;
}
.mk-tab {
  border: 0; background: transparent; cursor: pointer; padding: 9px 17px; border-radius: 999px;
  font-family: Inter, sans-serif; font-size: 13.5px; font-weight: 500; color: var(--deep-2ink);
  transition: background 0.2s ease, color 0.2s ease;
}
.mk-tab:hover { color: var(--deep-ink); }
.mk-tab-on, .mk-tab-on:hover { background: var(--brand); color: #fff; font-weight: 600; }
.mk-tab:focus-visible { outline: 2px solid var(--brand-3); outline-offset: 2px; }

.mk-tour-body {
  display: grid; grid-template-columns: minmax(0,0.8fr) minmax(0,1.2fr);
  gap: clamp(30px, 4vw, 56px); align-items: center;
  animation: mk-rise 0.55s cubic-bezier(0.16,1,0.3,1) both;
}
@media (max-width: 920px) { .mk-tour-body { grid-template-columns: 1fr; } }
.mk-tour-copy h3 {
  font-size: clamp(22px, 2.5vw, 30px); line-height: 1.14; font-weight: 700;
  font-variation-settings: "wdth" 108; letter-spacing: -0.026em; margin-top: 11px;
  color: var(--deep-ink);
}
.mk-tour-copy p { margin: 15px 0 0; color: var(--deep-2ink); font-size: 16px; line-height: 1.62; }

.mk-points { margin: 20px 0 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 11px; }
.mk-points li { position: relative; padding-left: 24px; font-size: 15px; line-height: 1.5; color: var(--deep-2ink); }
.mk-points li::before {
  content: ""; position: absolute; left: 0; top: 0.5em; width: 12px; height: 2px;
  background: var(--brand); border-radius: 2px;
}
.mk-points b { color: #E2E8F0; font-weight: 600; }

/* --- Automation --- */
.mk-autos { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; }
@media (max-width: 1000px) { .mk-autos { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 640px)  { .mk-autos { grid-template-columns: 1fr; } }
.mk-autos > * { height: 100%; }
.mk-auto {
  border: 1px solid var(--line); border-radius: 12px; padding: 26px 24px 28px;
  background: var(--ground); height: 100%;
  transition: transform 0.24s cubic-bezier(0.16,1,0.3,1), box-shadow 0.24s ease, border-color 0.24s ease;
}
.mk-auto:hover {
  transform: translateY(-3px); border-color: var(--brand);
  box-shadow: 0 20px 40px -26px rgba(15,23,42,0.4);
}
.mk-auto-i {
  width: 38px; height: 38px; display: grid; place-items: center; border-radius: 9px;
  background: var(--wash); color: var(--brand); margin-bottom: 16px;
}
.mk-auto-i svg { width: 19px; height: 19px; }
.mk-auto h4 { font-size: 16px; font-weight: 600; line-height: 1.3; margin-bottom: 7px; letter-spacing: -0.015em; font-family: Inter, sans-serif; }
.mk-auto p { margin: 0; font-size: 14.5px; line-height: 1.56; color: var(--ink-2); }

/* --- Close --- */
.mk-close {
  background: var(--deep); color: var(--deep-ink);
  padding: clamp(70px, 8.5vw, 116px) 0 0; text-align: center;
  position: relative; overflow: hidden;
}
.mk-close > * { position: relative; }
.mk-close h2 { color: var(--deep-ink); }
.mk-close .mk-lede { color: var(--deep-2ink); margin-inline: auto; }
.mk-foot {
  margin-top: clamp(56px, 7vw, 88px); padding: 26px 0 30px;
  border-top: 1px solid var(--deep-line);
  display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap;
}
.mk-foot p { margin: 0; font-size: 12.5px; color: #64748B; }

@media (prefers-reduced-motion: reduce) {
  .mk *, .mk *::before, .mk *::after { animation: none !important; transition: none !important; }
  .mk-rv { opacity: 1 !important; transform: none !important; }
  .mk-step { opacity: 1 !important; transform: none !important; }
  .mk h1 em::after { transform: scaleX(1) !important; }
}
`;
