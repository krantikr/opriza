import { PROBLEMS } from "../data/problems";

const AGENT_NAME: Record<string, { name: string; bg: string; fg: string; letter: string }> = {
  brief: { name: "Approvals + brief", bg: "#8a2420", fg: "#fff", letter: "B" },
  sales: { name: "Sales & Quote", bg: "#2b5c8a", fg: "#fff", letter: "Q" },
  collect: { name: "Collections", bg: "#e8a33d", fg: "#3a1a05", letter: "C" },
  stock: { name: "Stock & Purchase", bg: "#17684a", fg: "#fff", letter: "S" },
  cash: { name: "Cash", bg: "#4e100e", fg: "#fff", letter: "₹" },
  ask: { name: "Ask Oprisa", bg: "#231c18", fg: "#fff", letter: "A" },
  score: { name: "Customer Score", bg: "#5a4a3e", fg: "#fff", letter: "G" },
};

type Props = { selected: string[]; onChange: (ids: string[]) => void; onNext: () => void };

export default function Problems({ selected, onChange, onNext }: Props) {
  const toggle = (id: string) => onChange(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);
  return (
    <div className="setup">
      <header className="setup-hero">
        <div className="in">
          <div className="setup-top">
            <div className="mark">Oprisa<i>.</i></div>
            <div className="steps" aria-label="Step 1 of 2">
              <b className="on">1</b> <span className="sl cur">Problems</span> <span className="sep" /> <b>2</b> <span className="sl">Your business</span>
            </div>
          </div>
          <h1>
            What slows your business down? <span>Pick all that apply.</span>
          </h1>
          <p>We'll build a working demo of Oprisa around these, with sample data for your trade. It takes about a minute.</p>
        </div>
      </header>

      <main className="setup-body">
        <div className="prob-grid">
          {PROBLEMS.map((p) => {
            const on = selected.includes(p.id);
            const a = AGENT_NAME[p.thread]!;
            return (
              <button key={p.id} type="button" className="prob" aria-pressed={on} onClick={() => toggle(p.id)}>
                <span className="box" aria-hidden="true">✓</span>
                <span>
                  <span className="pt" style={{ display: "block" }}>{p.title}</span>
                  <span className="pd" style={{ display: "block" }}>{p.detail}</span>
                  <span className="pa">
                    <i style={{ background: a.bg, color: a.fg }} aria-hidden="true">{a.letter}</i>
                    Handled by {a.name}
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      </main>

      <footer className="setup-foot">
        <div className="in">
          <span className="hint" aria-live="polite">
            {selected.length ? (
              <>
                <b>{selected.length} picked.</b> Next, a few details about your business.
              </>
            ) : (
              "Pick at least one to continue."
            )}
          </span>
          <div className="foot-actions">
            <button type="button" className="btn btn-go" disabled={!selected.length} onClick={onNext}>
              Next: your business →
            </button>
          </div>
        </div>
      </footer>
    </div>
  );
}
