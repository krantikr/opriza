import type { ReactNode } from "react";
import type { Grade, Stage, Thread } from "../engine/types";

/* Small pieces every desk screen uses. Styles live in desk.css. */

export function PageHead({ title, sub, children }: { title: string; sub?: ReactNode; children?: ReactNode }) {
  return (
    <header className="dk-head">
      <div>
        <h1>{title}</h1>
        {sub && <p>{sub}</p>}
      </div>
      {children && <div className="dk-head-acts">{children}</div>}
    </header>
  );
}

export function Panel({ title, sub, right, children, className = "", pad = true }: { title?: ReactNode; sub?: ReactNode; right?: ReactNode; children: ReactNode; className?: string; pad?: boolean }) {
  return (
    <section className={`dk-panel ${className}`}>
      {(title || right) && (
        <div className="dk-panel-h">
          <div>
            {title && <h2>{title}</h2>}
            {sub && <p>{sub}</p>}
          </div>
          {right}
        </div>
      )}
      <div className={pad ? "dk-panel-b" : ""}>{children}</div>
    </section>
  );
}

export function GradeTag({ g }: { g: Grade }) {
  return <span className={`dk-grade g-${g}`} title={`Grade ${g}`}>{g}</span>;
}

export function Avatar({ t, size = 28 }: { t: Pick<Thread, "letter" | "bg" | "fg" | "name">; size?: number }) {
  return (
    <span className="dk-av" style={{ background: t.bg, color: t.fg, width: size, height: size, fontSize: size * 0.42 }} aria-hidden="true">
      {t.letter}
    </span>
  );
}

export function Initials({ name, size = 30 }: { name: string; size?: number }) {
  const ini = name.split(/\s+/).filter((x) => /^[A-Za-z]/.test(x)).map((x) => x[0]).join("").slice(0, 2).toUpperCase();
  return <span className="dk-ini" style={{ width: size, height: size, fontSize: size * 0.38 }} aria-hidden="true">{ini}</span>;
}

/** A row of tabs that switch a screen's view. */
export function Tabs<T extends string>({ value, onChange, items }: { value: T; onChange: (v: T) => void; items: { id: T; label: string; count?: number }[] }) {
  return (
    <div className="dk-tabs" role="tablist">
      {items.map((i) => (
        <button key={i.id} type="button" role="tab" aria-selected={value === i.id} onClick={() => onChange(i.id)}>
          {i.label}
          {i.count !== undefined && <span className="n">{i.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Check({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label className="dk-check" onClick={(e) => e.stopPropagation()}>
      <input type="checkbox" checked={on} onChange={(e) => onChange(e.target.checked)} aria-label={label} />
      <span aria-hidden="true" />
    </label>
  );
}

export function Toggle({ on, onChange, label }: { on: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button type="button" className={`dk-toggle ${on ? "on" : ""}`} role="switch" aria-checked={on} aria-label={label} onClick={() => onChange(!on)}>
      <span />
    </button>
  );
}

export const STAGES: { id: Stage; label: string }[] = [
  { id: "draft", label: "Draft" },
  { id: "sent", label: "Sent" },
  { id: "opened", label: "Opened" },
  { id: "talks", label: "In talks" },
  { id: "won", label: "Won" },
  { id: "lost", label: "Lost" },
];

export function StageTag({ stage }: { stage: Stage }) {
  return <span className={`dk-stage st-${stage}`}>{STAGES.find((x) => x.id === stage)!.label}</span>;
}

/** Hours as "5 h" or "2 d". */
export function age(h: number): string {
  if (h < 1) return "just now";
  return h < 24 ? `${h} h` : `${Math.round(h / 24)} d`;
}

/** A small bar showing one value against a maximum. */
export function Meter({ value, max, tone = "neutral" }: { value: number; max: number; tone?: "bad" | "warn" | "good" | "neutral" }) {
  return (
    <span className={`dk-meter t-${tone}`} aria-hidden="true">
      <b style={{ width: `${Math.max(3, Math.min(100, (value / Math.max(1, max)) * 100))}%` }} />
    </span>
  );
}

export function Empty({ title, sub }: { title: string; sub?: string }) {
  return (
    <div className="dk-empty">
      <b>{title}</b>
      {sub && <span>{sub}</span>}
    </div>
  );
}
