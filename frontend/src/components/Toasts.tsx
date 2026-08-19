import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";

/* ---------------------------------------------------------------------------
   In-page notices.

   The desktop notification covers the case where the tab is in the background.
   This covers the other one: something arrived while you were looking at a
   different screen inside the app, where a system popup would be redundant but
   silence would be wrong.

   Toasts auto-dismiss because they are informational. Anything that needs a
   decision belongs in a banner on the page, not in something that disappears.
   --------------------------------------------------------------------------- */

export type ToastTone = "info" | "settled" | "attention" | "danger";

export interface Toast {
  id: number;
  title: string;
  body?: string;
  tone: ToastTone;
  link?: string;
}

interface ToastApi {
  push: (toast: Omit<Toast, "id">) => void;
}

const ToastContext = createContext<ToastApi>({ push: () => undefined });

export function useToast(): ToastApi {
  return useContext(ToastContext);
}

const TONES: Record<ToastTone, { bar: string; icon: ReactNode }> = {
  info: {
    bar: "bg-brand",
    icon: (
      <svg viewBox="0 0 24 24" className="size-4 text-brand" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="12" cy="12" r="9" />
        <path d="M12 11v5M12 8h.01" strokeLinecap="round" />
      </svg>
    ),
  },
  settled: {
    bar: "bg-settled",
    icon: (
      <svg viewBox="0 0 24 24" className="size-4 text-settled" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M20 6L9 17l-5-5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ),
  },
  attention: {
    bar: "bg-attention",
    icon: (
      <svg viewBox="0 0 24 24" className="size-4 text-attention" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M12 3l9 16H3z" strokeLinejoin="round" />
        <path d="M12 10v4M12 17h.01" strokeLinecap="round" />
      </svg>
    ),
  },
  danger: {
    bar: "bg-danger",
    icon: (
      <svg viewBox="0 0 24 24" className="size-4 text-danger" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="12" cy="12" r="9" />
        <path d="M15 9l-6 6M9 9l6 6" strokeLinecap="round" />
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

  useEffect(() => {
    const hide = setTimeout(() => setLeaving(true), 6000);
    const remove = setTimeout(onDismiss, 6300);
    return () => {
      clearTimeout(hide);
      clearTimeout(remove);
    };
  }, [onDismiss]);

  const tone = TONES[toast.tone];

  return (
    <div
      role="status"
      className={`pointer-events-auto flex w-80 overflow-hidden rounded-card border border-rule bg-surface shadow-raised transition-all duration-300 ${
        leaving ? "translate-x-2 opacity-0" : "translate-x-0 opacity-100"
      }`}
    >
      <span className={`w-1 shrink-0 ${tone.bar}`} />
      <div className="flex min-w-0 flex-1 gap-2.5 px-3 py-2.5">
        <span className="mt-0.5 shrink-0">{tone.icon}</span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-ink">{toast.title}</p>
          {toast.body && (
            <p className="mt-0.5 line-clamp-2 text-xs text-ink-soft">{toast.body}</p>
          )}
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
          className="shrink-0 self-start rounded p-0.5 text-ink-faint hover:bg-sunk hover:text-ink"
        >
          <svg viewBox="0 0 24 24" className="size-3.5" fill="none" stroke="currentColor" strokeWidth="2">
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
    setToasts((current) => {
      const next = [...current, { ...toast, id: Date.now() + Math.random() }];
      // Three at a time; beyond that they stop being readable.
      return next.slice(-3);
    });
  }, []);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((t) => t.id !== id));
  }, []);

  return (
    <ToastContext.Provider value={{ push }}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex flex-col gap-2">
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
