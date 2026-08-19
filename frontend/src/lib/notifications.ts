/* ---------------------------------------------------------------------------
   Desktop notifications.

   The dashboard bell tells you what happened while you were looking; this
   tells you while you are not. A trading desk leaves the tab open in the
   background all day, so an enquiry that arrives at 11am is worth surfacing
   through the operating system rather than waiting to be noticed.

   Three rules keep it from becoming a nuisance:

   * **Permission is asked for, never assumed.** Browsers require a user
     gesture, and a page that demands notification rights on load is one people
     block permanently.
   * **Nothing is announced twice.** Delivered ids are remembered in
     localStorage, so a reload - or a second open tab - does not re-announce
     what you already saw.
   * **Nothing is announced from history.** On the first poll after load the
     backlog is recorded as already-seen. Otherwise opening the app in the
     morning would fire twenty notifications at once.
   --------------------------------------------------------------------------- */

const SEEN_KEY = "notif:seen";
const ENABLED_KEY = "notif:enabled";
const MAX_REMEMBERED = 400;

export type PermissionState = "unsupported" | "default" | "granted" | "denied";

export function permissionState(): PermissionState {
  if (typeof Notification === "undefined") return "unsupported";
  return Notification.permission as PermissionState;
}

/** Whether the user has switched desktop alerts on for this browser. */
export function isEnabled(): boolean {
  return localStorage.getItem(ENABLED_KEY) === "1" && permissionState() === "granted";
}

export function setEnabled(on: boolean): void {
  localStorage.setItem(ENABLED_KEY, on ? "1" : "0");
}

/**
 * Ask the browser for permission. Must be called from a click - browsers
 * ignore (and Safari rejects) a request made outside a user gesture.
 */
export async function requestPermission(): Promise<PermissionState> {
  if (typeof Notification === "undefined") return "unsupported";
  if (Notification.permission !== "default") return Notification.permission as PermissionState;

  try {
    const result = await Notification.requestPermission();
    return result as PermissionState;
  } catch {
    return "denied";
  }
}

function readSeen(): Set<number> {
  try {
    const raw = localStorage.getItem(SEEN_KEY);
    return new Set<number>(raw ? JSON.parse(raw) : []);
  } catch {
    return new Set();
  }
}

function writeSeen(seen: Set<number>): void {
  // Keep the newest ids only; this list grows forever otherwise.
  const trimmed = [...seen].slice(-MAX_REMEMBERED);
  try {
    localStorage.setItem(SEEN_KEY, JSON.stringify(trimmed));
  } catch {
    /* storage full or blocked - announcing twice is better than crashing */
  }
}

export interface Announceable {
  id: number;
  title: string;
  body: string | null;
  link: string | null;
  kind: string;
}

/**
 * Record a batch as already-seen without announcing it. Called once on the
 * first poll, so the backlog does not arrive as a burst of alerts.
 */
export function primeSeen(items: Announceable[]): void {
  const seen = readSeen();
  for (const item of items) seen.add(item.id);
  writeSeen(seen);
}

/**
 * Announce anything not seen before, and return what was announced.
 *
 * `onClick` receives the item's link so the caller can route to it - the
 * notification itself cannot navigate a single-page app.
 */
export function announce(
  items: Announceable[],
  onClick: (link: string) => void,
): Announceable[] {
  if (!isEnabled()) return [];

  const seen = readSeen();
  const fresh = items.filter((item) => !seen.has(item.id));
  if (fresh.length === 0) return [];

  // A burst is summarised rather than stacked: five separate popups for five
  // enquiries is worse than one that says five arrived.
  const toShow = fresh.length > 3 ? fresh.slice(0, 1) : fresh;

  for (const item of toShow) {
    try {
      const notification = new Notification(item.title, {
        body:
          fresh.length > 3
            ? `${item.body ?? ""}\n+${fresh.length - 1} more waiting`.trim()
            : (item.body ?? undefined),
        // Same tag replaces rather than stacks, so a repeated kind does not
        // pile up in the notification centre.
        tag: `steel-desk-${item.kind}`,
        icon: "/favicon.svg",
      });

      notification.onclick = () => {
        window.focus();
        if (item.link) onClick(item.link);
        notification.close();
      };
    } catch {
      /* the browser refused - the bell still has it */
    }
  }

  for (const item of fresh) seen.add(item.id);
  writeSeen(seen);
  return fresh;
}
