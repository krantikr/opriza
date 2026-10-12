/* ---------------------------------------------------------------------------
   Shared building blocks for the Oprisa marketing site: SEO head management,
   scroll-reveal, count-up, and the self-writing WhatsApp phone.

   Motion is deliberate, not decorative: the phone replays the morning brief —
   the single thing the product promises — and everything resolves instantly
   under prefers-reduced-motion.
   --------------------------------------------------------------------------- */

import { useEffect, useRef, useState } from "react";

export const reduced = () =>
  typeof window !== "undefined" &&
  window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/* --- SEO: title + meta, set per page, cleaned up on unmount ---------------- */

const SITE = "Oprisa";
const BASE_URL = "https://opriza.vercel.app";

function setMeta(selector: string, attr: "name" | "property", key: string, content: string) {
  let el = document.head.querySelector<HTMLMetaElement>(selector);
  if (!el) {
    el = document.createElement("meta");
    el.setAttribute(attr, key);
    document.head.appendChild(el);
  }
  el.setAttribute("content", content);
}

export function useSeo(opts: { title: string; description: string; path: string }) {
  useEffect(() => {
    const full = opts.title === SITE ? SITE : `${opts.title} · ${SITE}`;
    document.title = full;
    const url = BASE_URL + opts.path;

    setMeta('meta[name="description"]', "name", "description", opts.description);
    setMeta('meta[property="og:title"]', "property", "og:title", full);
    setMeta('meta[property="og:description"]', "property", "og:description", opts.description);
    setMeta('meta[property="og:type"]', "property", "og:type", "website");
    setMeta('meta[property="og:url"]', "property", "og:url", url);
    setMeta('meta[property="og:site_name"]', "property", "og:site_name", SITE);
    setMeta('meta[name="twitter:card"]', "name", "twitter:card", "summary_large_image");
    setMeta('meta[name="twitter:title"]', "name", "twitter:title", full);
    setMeta('meta[name="twitter:description"]', "name", "twitter:description", opts.description);

    let canon = document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]');
    if (!canon) {
      canon = document.createElement("link");
      canon.setAttribute("rel", "canonical");
      document.head.appendChild(canon);
    }
    canon.setAttribute("href", url);
  }, [opts.title, opts.description, opts.path]);
}

/* --- Scroll reveal --------------------------------------------------------- */

export function useReveal<T extends HTMLElement>(delay = 0) {
  const ref = useRef<T>(null);
  const [shown, setShown] = useState(false);
  useEffect(() => {
    if (reduced() || typeof IntersectionObserver === "undefined") {
      setShown(true);
      return;
    }
    const el = ref.current;
    if (!el) return;

    // Failsafe: anything still hidden a few seconds after mount is revealed
    // unconditionally. Content must never be stranded at opacity:0 because an
    // observer never fired — that would hide it from crawlers and from the
    // first painted frame.
    const safety = window.setTimeout(() => setShown(true), 2500 + delay);

    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          window.setTimeout(() => setShown(true), delay);
          io.disconnect();
        }
      },
      { threshold: 0.12, rootMargin: "0px 0px -60px 0px" },
    );
    io.observe(el);
    return () => {
      io.disconnect();
      clearTimeout(safety);
    };
  }, [delay]);
  return { ref, shown };
}

export function Reveal({
  children,
  delay = 0,
  className = "",
  as: Tag = "div",
}: {
  children: React.ReactNode;
  delay?: number;
  className?: string;
  as?: "div" | "section" | "li" | "span";
}) {
  const { ref, shown } = useReveal<HTMLDivElement>(delay);
  return (
    <Tag ref={ref as never} className={`reveal${shown ? " in" : ""}${className ? " " + className : ""}`}>
      {children}
    </Tag>
  );
}

/* --- Count up (fires once when scrolled into view) ------------------------- */

export function CountUp({
  to,
  prefix = "",
  suffix = "",
  decimals = 0,
  duration = 1100,
}: {
  to: number;
  prefix?: string;
  suffix?: string;
  decimals?: number;
  duration?: number;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const [val, setVal] = useState(reduced() ? to : 0);
  useEffect(() => {
    if (reduced()) return;
    const el = ref.current;
    if (!el) return;
    let raf = 0;
    const io = new IntersectionObserver(
      ([entry]) => {
        if (!entry.isIntersecting) return;
        io.disconnect();
        const start = performance.now();
        const tick = (now: number) => {
          const p = Math.min(1, (now - start) / duration);
          const eased = 1 - Math.pow(1 - p, 3);
          setVal(to * eased);
          if (p < 1) raf = requestAnimationFrame(tick);
        };
        raf = requestAnimationFrame(tick);
      },
      { threshold: 0.4 },
    );
    io.observe(el);
    return () => {
      io.disconnect();
      cancelAnimationFrame(raf);
    };
  }, [to, duration]);
  return (
    <span ref={ref} className="tnum">
      {prefix}
      {val.toFixed(decimals)}
      {suffix}
    </span>
  );
}

/* --- The self-writing morning brief (the signature) ------------------------ */

type Line = { lbl?: string; cls?: string; html: string; max?: string };

const MicIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
    <path d="M12 2a3 3 0 00-3 3v6a3 3 0 006 0V5a3 3 0 00-3-3z" />
    <path d="M5 11a7 7 0 0014 0M12 18v3" />
  </svg>
);

export function Phone({
  status = "online",
  lines,
  animate = true,
  startInView = true,
}: {
  status?: string;
  lines: Line[];
  animate?: boolean;
  startInView?: boolean;
}) {
  const threadRef = useRef<HTMLDivElement>(null);
  const [replayable, setReplayable] = useState(false);
  const timers = useRef<number[]>([]);

  useEffect(() => {
    const thread = threadRef.current;
    if (!thread) return;
    const clearAll = () => {
      timers.current.forEach(clearTimeout);
      timers.current = [];
      thread.innerHTML = "";
    };
    const dayPill = () => {
      const p = document.createElement("div");
      p.className = "daypill";
      p.textContent = "Today";
      thread.appendChild(p);
    };
    const makeBubble = (item: Line) => {
      const b = document.createElement("div");
      b.className = "bubble " + (item.cls || "");
      if (item.max) b.style.maxWidth = item.max;
      b.innerHTML = (item.lbl ? `<span class="b-lbl">${item.lbl}</span>` : "") + item.html;
      return b;
    };
    const typingEl = () => {
      const t = document.createElement("div");
      t.className = "typing";
      t.id = "mk-typing";
      t.innerHTML = "<span></span><span></span><span></span>";
      return t;
    };

    const run = () => {
      clearAll();
      dayPill();
      if (!animate || reduced()) {
        lines.forEach((it) => {
          const b = makeBubble(it);
          b.classList.add("show");
          thread.appendChild(b);
        });
        setReplayable(true);
        return;
      }
      let delay = 350;
      lines.forEach((it, i) => {
        timers.current.push(
          window.setTimeout(() => {
            thread.appendChild(typingEl());
            thread.scrollTop = thread.scrollHeight;
          }, delay),
        );
        delay += i === 0 ? 620 : 800;
        timers.current.push(
          window.setTimeout(() => {
            const t = document.getElementById("mk-typing");
            if (t) t.remove();
            const b = makeBubble(it);
            thread.appendChild(b);
            void b.offsetWidth;
            b.classList.add("show");
            thread.scrollTop = thread.scrollHeight;
            if (i === lines.length - 1) setReplayable(true);
          }, delay),
        );
        delay += 240;
      });
    };

    const start = () => run();
    let io: IntersectionObserver | null = null;
    if (startInView && "IntersectionObserver" in window && !reduced()) {
      io = new IntersectionObserver(
        (entries) => {
          entries.forEach((e) => {
            if (e.isIntersecting) {
              start();
              io?.disconnect();
            }
          });
        },
        { threshold: 0.3 },
      );
      io.observe(thread);
    } else {
      start();
    }
    return () => {
      io?.disconnect();
      timers.current.forEach(clearTimeout);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const replay = () => {
    const thread = threadRef.current;
    if (!thread) return;
    setReplayable(false);
    // re-run by dispatching a fresh sequence
    timers.current.forEach(clearTimeout);
    timers.current = [];
    thread.innerHTML = "";
    const dayPill = document.createElement("div");
    dayPill.className = "daypill";
    dayPill.textContent = "Today";
    thread.appendChild(dayPill);
    let delay = 200;
    lines.forEach((it, i) => {
      timers.current.push(
        window.setTimeout(() => {
          const t = document.createElement("div");
          t.className = "typing";
          t.id = "mk-typing";
          t.innerHTML = "<span></span><span></span><span></span>";
          thread.appendChild(t);
          thread.scrollTop = thread.scrollHeight;
        }, delay),
      );
      delay += i === 0 ? 500 : 720;
      timers.current.push(
        window.setTimeout(() => {
          const t = document.getElementById("mk-typing");
          if (t) t.remove();
          const b = document.createElement("div");
          b.className = "bubble " + (it.cls || "");
          if (it.max) b.style.maxWidth = it.max;
          b.innerHTML = (it.lbl ? `<span class="b-lbl">${it.lbl}</span>` : "") + it.html;
          thread.appendChild(b);
          void b.offsetWidth;
          b.classList.add("show");
          thread.scrollTop = thread.scrollHeight;
          if (i === lines.length - 1) setReplayable(true);
        }, delay),
      );
      delay += 220;
    });
  };

  return (
    <div className="phone">
      <div className="screen">
        <div className="wa-top">
          <div className="wa-av">O</div>
          <div>
            <div className="nm">Oprisa</div>
            <div className="st">{status}</div>
          </div>
        </div>
        <div className="thread" ref={threadRef} aria-live="polite" aria-label="Oprisa morning brief" />
        <div className="wa-bar">
          <div className="inp">Ask anything…</div>
          <div className="mic">
            <MicIcon />
          </div>
        </div>
      </div>
      {replayable && animate && !reduced() && (
        <button className="replay" onClick={replay} type="button">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.4}>
            <path d="M3 12a9 9 0 109-9 9 9 0 00-6.4 2.6L3 8" />
            <path d="M3 3v5h5" />
          </svg>
          Replay
        </button>
      )}
    </div>
  );
}

/* --- Theme toggle (per-viewer convenience) --------------------------------- */

export function ThemeToggle() {
  const flip = () => {
    const root = document.documentElement;
    const cur = root.getAttribute("data-theme");
    const prefDark = window.matchMedia?.("(prefers-color-scheme: dark)").matches;
    const next = cur ? (cur === "dark" ? "light" : "dark") : prefDark ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try {
      localStorage.setItem("oprisa-theme", next);
    } catch {
      /* private mode */
    }
  };
  return (
    <button className="theme-btn" onClick={flip} type="button">
      Theme
    </button>
  );
}
