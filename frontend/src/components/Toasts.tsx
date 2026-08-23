import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { playChime } from "../lib/chime";
import { soundEnabled } from "../lib/sound-preference";

/* ---------------------------------------------------------------------------
   In-page notices.

   The desktop notification covers the case where the tab is in the background.
   This covers the other one: something arrived while you were looking at a
   different screen inside the app, where a system popup would be redundant but
   silence would be wrong.

   Toasts auto-dismiss because they are informational. Anything that needs a
   decision belongs in a banner on the page, not in something that disappears.

   They sit top-right, under the header rather than over it. A trader's eye is
   already at the top of the screen for the bell and the account menu, and the
   bottom corner competes with the detail panels that open there.
   --------------------------------------------------------------------------- */

export type ToastTone = "info" | "settled" | "attention" | "danger";

export interface Toast {
  id: number;
  title: string;
  body?: string;
  tone: ToastTone;
  link?: string;
  /** Suppresses the chime for this one notice. Used where a toast confirms an
   *  action the person just took - they know it worked, and a sound for every
   *  click is what makes people mute the app entirely. */
  silent?: boolean;
}

interface ToastApi {
  push: (toast: Omit<Toast, "id">) => void;
  /** Shorthands for the two cases that make up most calls, so a confirmation
   *  or a failure does not need the tone spelled out at every site. */
  success: (message: string) => void;
  error: (message: string) => void;
}

const ToastContext = createContext<ToastApi>({
  push: () => undefined,
  success: () => undefined,
  error: () => undefined,
});

export function useToast(): ToastApi {
  return useContext(ToastContext);
}

/* Each tone is a filled circle on a tinted card, per the agreed design.
   The tint fades to the surface colour across the card so the text side stays
   plain - a fully washed card makes body text harder to read, and the point of
   the colour is to be recognised at a glance, not to be looked at. */
const TONES: Record<
  ToastTone,
  { border: string; wash: string; badge: string; icon: ReactNode }
> = {
  settled: {
    border: "border-settled",
    wash: "from-settled-wash",
    badge: "bg-settled",
    icon: (
      <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="3">
        <path d="M20 6L9 17l-5-5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
  attention: {
    border: "border-attention",
    wash: "from-attention-wash",
    badge: "bg-attention",
    icon: (
      <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="2.5">
        <path d="M12 4l9 16H3z" strokeLinejoin="round" />
        <path d="M12 10v4M12 17h.01" strokeLinecap="round" />
      </svg>
    ),
  },
  info: {
    border: "border-brand",
    wash: "from-brand-wash",
    badge: "bg-brand",
    icon: (
      <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="2.5">
        <path d="M12 11v5M12 7.5h.01" strokeLinecap="round" />
      </svg>
    ),
  },
  danger: {
    border: "border-danger",
    wash: "from-danger-wash",
    badge: "bg-danger",
    icon: (
      <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="2.5">
        <path d="M12 7v6M12 16.5h.01" strokeLinecap="round" />
      </svg>
    ),
  },
};

function ToastCard({
  toast,
  onDismiss,
  onOpen,
}: {
  toast: Toast;
  onDismiss: () => void;
  onOpen?: () => void;
}) {
  const [leaving, setLeaving] = useState(false);
  const [entered, setEntered] = useState(false);

  // Slide in from the right edge it lives on. Starting the transition on the
  // next frame is what makes it animate at all - mounted and styled in the
  // same paint, the browser has nothing to interpolate from.
  useEffect(() => {
    const raf = requestAnimationFrame(() => setEntered(true));
    return () => cancelAnimationFrame(raf);
  }, []);

  useEffect(() => {
    const hide = setTimeout(() => setLeaving(true), 6000);
    const remove = setTimeout(onDismiss, 6300);
    return () => {
      clearTimeout(hide);
      clearTimeout(remove);
    };
  }, [onDismiss]);

  const tone = TONES[toast.tone];
  const offscreen = leaving || !entered;

  return (
    <div
      role="status"
      className={`pointer-events-auto w-[22rem] overflow-hidden rounded-card border-2 bg-surface shadow-raised transition-all duration-300 ease-out ${
        tone.border
      } ${offscreen ? "translate-x-6 opacity-0" : "translate-x-0 opacity-100"}`}
    >
      <div className={`flex items-start gap-3 bg-gradient-to-r ${tone.wash} to-surface to-70% px-4 py-3`}>
        <span
          className={`mt-0.5 grid size-7 shrink-0 place-items-center rounded-full text-white ${tone.badge}`}
        >
          {tone.icon}
        </span>

        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-ink">{toast.title}</p>
          {toast.body && <p className="mt-0.5 line-clamp-2 text-xs text-ink-soft">{toast.body}</p>}
          {toast.link && onOpen && (
            <button
              type="button"
              onClick={() => {
                onOpen();
                onDismiss();
              }}
              className="mt-1 text-xs font-medium text-brand hover:underline"
            >
              Open
            </button>
          )}
        </div>

        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss"
          className="-mr-1 shrink-0 self-center rounded p-1 text-ink-faint transition-colors hover:bg-sunk hover:text-ink"
        >
          <svg viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M18 6L6 18M6 6l12 12" strokeLinecap="round" />
          </svg>
        </button>
      </div>
    </div>
  );
}

export function ToastProvider({
  children,
  onOpenLink,
}: {
  children: ReactNode;
  onOpenLink?: (link: string) => void;
}) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const push = useCallback((toast: Omit<Toast, "id">) => {
    // Read the preference at ring time, not at mount: a trader who mutes in
    // Settings expects the very next notification to be silent.
    if (!toast.silent && soundEnabled()) playChime(toast.tone);

    setToasts((current) => {
      const next = [...current, { ...toast, id: Date.now() + Math.random() }];
      // Four at a time; beyond that they stop being readable.
      return next.slice(-4);
    });
  }, []);

  const api = useMemo<ToastApi>(
    () => ({
      push,
      // Confirmations of a click the person just made: shown, not sounded.
      success: (message: string) => push({ tone: "settled", title: message, silent: true }),
      error: (message: string) => push({ tone: "danger", title: message }),
    }),
    [push],
  );

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((t) => t.id !== id));
  }, []);

  return (
    <ToastContext.Provider value={api}>
      {children}
      {/* Top-right, below the 56px header so a toast never covers the bell it
          is telling you about. */}
      <div className="pointer-events-none fixed right-4 top-16 z-50 flex flex-col gap-3">
        {toasts.map((toast) => (
          <ToastCard
            key={toast.id}
            toast={toast}
            onDismiss={() => dismiss(toast.id)}
            onOpen={toast.link && onOpenLink ? () => onOpenLink(toast.link!) : undefined}
          />
        ))}
      </div>
    </ToastContext.Provider>
  );
}
