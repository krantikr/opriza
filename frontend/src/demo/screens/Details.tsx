import { useState } from "react";
import { INDUSTRIES, industryById } from "../data/industries";
import { PROBLEMS } from "../data/problems";
import type { Business, Language, RevenueBand } from "../engine/types";

const BANDS: { id: RevenueBand; label: string }[] = [
  { id: "50-100", label: "₹50–100 Cr" },
  { id: "100-250", label: "₹100–250 Cr" },
  { id: "250-500", label: "₹250–500 Cr" },
  { id: "500+", label: "₹500 Cr+" },
];
const TEAMS = ["Under 10", "10–25", "25–50", "50+"];

type Props = {
  biz: Business;
  onChange: (b: Business) => void;
  onBack: () => void;
  onStart: () => void;
};

const CHAT_OF: Record<string, { name: string; letter: string; bg: string; fg: string }> = {
  sales: { name: "Sales & Quote", letter: "Q", bg: "#2b5c8a", fg: "#fff" },
  collect: { name: "Collections", letter: "C", bg: "#e8a33d", fg: "#3a1a05" },
  stock: { name: "Stock & Purchase", letter: "S", bg: "#17684a", fg: "#fff" },
  cash: { name: "Cash", letter: "₹", bg: "#4e100e", fg: "#fff" },
  ask: { name: "Ask Oprisa", letter: "A", bg: "#231c18", fg: "#fff" },
  score: { name: "Customer Score", letter: "G", bg: "#5a4a3e", fg: "#fff" },
  brief: { name: "Today's brief + Approvals", letter: "B", bg: "#8a2420", fg: "#fff" },
};

export default function Details({ biz, onChange, onBack, onStart }: Props) {
  const [tried, setTried] = useState(false);
  const set = <K extends keyof Business>(k: K, v: Business[K]) => onChange({ ...biz, [k]: v });
  const missing = {
    company: !biz.company.trim(),
    owner: !biz.owner.trim(),
    city: !biz.city.trim(),
  };
  const ok = !missing.company && !missing.owner && !missing.city;
  const pack = industryById(biz.industry);

  const chats = Array.from(new Set(["brief", ...biz.problems.map((id) => PROBLEMS.find((p) => p.id === id)?.thread ?? "ask")]));

  const start = () => {
    setTried(true);
    if (ok) onStart();
  };

  return (
    <div className="setup">
      <header className="setup-hero">
        <div className="in">
          <div className="setup-top">
            <div className="mark">Oprisa<i>.</i></div>
            <div className="steps" aria-label="Step 2 of 2">
              <b>1</b> <span className="sl">Problems</span> <span className="sep" /> <b className="on">2</b> <span className="sl cur">Your business</span>
            </div>
          </div>
          <h1>
            Tell us about your business. <span>We'll fill the demo with it.</span>
          </h1>
          <p>Customers, items, rates and dues will be sample data shaped like your trade. Nothing is saved or sent.</p>
        </div>
      </header>

      <main className="setup-body">
        <div className="details">
          <form
            id="details-form"
            className="form"
            noValidate
            onSubmit={(e) => {
              e.preventDefault();
              start();
            }}
          >
            <div className="field wide">
              <label htmlFor="company">Company name</label>
              <input id="company" className="input" value={biz.company} onChange={(e) => set("company", e.target.value)} placeholder="e.g. Shree Balaji Steels" autoComplete="organization" aria-invalid={tried && missing.company} />
              {tried && missing.company && <span className="err">Enter your company name.</span>}
            </div>
            <div className="field">
              <label htmlFor="owner">Your name</label>
              <input id="owner" className="input" value={biz.owner} onChange={(e) => set("owner", e.target.value)} placeholder="e.g. Kranti Karan" autoComplete="name" aria-invalid={tried && missing.owner} />
              {tried && missing.owner && <span className="err">Enter your name.</span>}
            </div>
            <div className="field">
              <label htmlFor="city">City</label>
              <input id="city" className="input" value={biz.city} onChange={(e) => set("city", e.target.value)} placeholder="e.g. Pune" autoComplete="address-level2" aria-invalid={tried && missing.city} />
              {tried && missing.city && <span className="err">Enter your city.</span>}
            </div>
            <div className="field wide">
              <label htmlFor="industry">What you sell</label>
              <select id="industry" className="select" value={biz.industry} onChange={(e) => set("industry", e.target.value)}>
                {INDUSTRIES.map((i) => (
                  <option key={i.id} value={i.id}>{i.label}</option>
                ))}
              </select>
              <small>{pack.note}. Sample items: {pack.products.slice(0, 3).map((p) => p.name).join(", ")}.</small>
            </div>
            <div className="field wide">
              <span id="rev-l" style={{ fontWeight: 700, fontSize: 14 }}>Yearly sales</span>
              <div className="seg" role="group" aria-labelledby="rev-l">
                {BANDS.map((b) => (
                  <button key={b.id} type="button" aria-pressed={biz.revenue === b.id} onClick={() => set("revenue", b.id)}>{b.label}</button>
                ))}
              </div>
            </div>
            <div className="field wide">
              <span id="team-l" style={{ fontWeight: 700, fontSize: 14 }}>Team size</span>
              <div className="seg" role="group" aria-labelledby="team-l">
                {TEAMS.map((t) => (
                  <button key={t} type="button" aria-pressed={biz.team === t} onClick={() => set("team", t)}>{t}</button>
                ))}
              </div>
            </div>
            <div className="field">
              <span id="tally-l" style={{ fontWeight: 700, fontSize: 14 }}>Tally version</span>
              <div className="seg" role="group" aria-labelledby="tally-l">
                {(["TallyPrime", "Tally.ERP 9"] as const).map((t) => (
                  <button key={t} type="button" aria-pressed={biz.tally === t} onClick={() => set("tally", t)}>{t}</button>
                ))}
              </div>
            </div>
            <div className="field">
              <span id="lang-l" style={{ fontWeight: 700, fontSize: 14 }}>Reminder language</span>
              <div className="seg" role="group" aria-labelledby="lang-l">
                {(["English", "Hinglish"] as Language[]).map((l) => (
                  <button key={l} type="button" aria-pressed={biz.language === l} onClick={() => set("language", l)}>{l}</button>
                ))}
              </div>
            </div>
          </form>

          <aside className="preview" aria-label="What your demo will include">
            <h3>Your demo will open with</h3>
            <div className="pv-list">
              {chats.map((id) => {
                const c = CHAT_OF[id]!;
                return (
                  <div className="pv-row" key={id}>
                    <span className="av sm" style={{ background: c.bg, color: c.fg }} aria-hidden="true">{c.letter}</span>
                    <span>
                      <b>{c.name}</b>
                      <br />
                      <span className="sub">{id === "brief" ? "Your morning summary and anything waiting for you" : "Busy with today's work, on top of your list"}</span>
                    </span>
                  </div>
                );
              })}
            </div>
            <div>
              <div className="csub" style={{ marginBottom: 6 }}>Because you picked</div>
              <div className="chipset">
                {biz.problems.map((id) => (
                  <span key={id} className="tagchip">{PROBLEMS.find((p) => p.id === id)?.short}</span>
                ))}
              </div>
            </div>
            <div className="csub">Every other chat is there too. Tap buttons, or type questions like "who owes me the most?".</div>
          </aside>
        </div>
      </main>

      <footer className="setup-foot">
        <div className="in">
          <div className="foot-actions" style={{ width: "100%" }}>
            <button type="button" className="btn btn-line" onClick={onBack}>← Back</button>
            <span className="spacer" aria-hidden="true" />
            <button type="submit" form="details-form" className="btn btn-go">Start my demo →</button>
          </div>
        </div>
      </footer>
    </div>
  );
}
