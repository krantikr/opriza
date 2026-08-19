/* ---------------------------------------------------------------------------
   Alerts.

   Two delivery routes, because one does not cover both cases:

   * **In-app** - a toast, always on. Works on every device including iOS
     Safari, and needs no permission from anybody.
   * **System** - an OS-level notification, so an enquiry reaches you with the
     tab in the background or the phone in a pocket.

   On **desktop** and on **Android** the system route uses the Notifications
   API. On **iOS** that API only exists once the site has been added to the
   home screen as a web app - Apple gates it behind installation. So the toast
   is the guaranteed floor everywhere, and the system layer is an upgrade that
   turns itself on wherever the browser permits it.

   Alerts are **on by default**: a desk that misses an enquiry has lost the
   order, so the safe default is to tell you. Permission is still requested on
   the first gesture rather than at load, because browsers ignore - and users
   permanently block - a site that demands it up front.
   --------------------------------------------------------------------------- */

const SEEN_KEY = "notif:seen";
const PREF_KEY = "notif:pref";
const ASKED_KEY = "notif:asked";
const MAX_REMEMBERED = 400;

export type PermissionState = "unsupported" | "default" | "granted" | "denied";

export function permissionState(): PermissionState {
  if (typeof Notification === "undefined") return "unsupported";
  return Notification.permission as PermissionState;
}

/** True on an iPhone or iPad browser, where the API needs home-screen install. */
export function needsHomeScreenInstall(): boolean {
  if (typeof navigator === "undefined") return false;
  const ios = /iPad|iPhone|iPod/.test(navigator.userAgent);
  const standalone =
    window.matchMedia?.("(display-mode: standalone)").matches ||
    // Safari's own flag, which is not in the standard.
    (navigator as unknown as { standalone?: boolean }).standalone === true;
  return ios && !standalone && typeof Notification === "undefined";
}

/**
 * Whether the user wants system alerts. Defaults to **on** - only an explicit
 * opt-out turns it off, so a desk is told about work by default.
 */
export function isWanted(): boolean {
  return localStorage.getItem(PREF_KEY) !== "off";
}

export function setWanted(on: boolean): void {
  localStorage.setItem(PREF_KEY, on ? "on" : "off");
}

/** Wanted *and* actually permitted by the browser. */
export function isActive(): boolean {
  return isWanted() && permissionState() === "granted";
}

/**
 * Ask the browser for permission. Must run inside a user gesture - browsers
 * ignore requests made outside one, and asking on page load is how a site gets
 * blocked for good.
 */
export async function requestPermission(): Promise<PermissionState> {
  if (typeof Notification === "undefined") return "unsupported";
  localStorage.setItem(ASKED_KEY, "1");

  if (Notification.permission !== "default") return Notification.permission as PermissionState;
  try {
    return (await Notification.requestPermission()) as PermissionState;
  } catch {
    return "denied";
  }
}

/** Whether we have already prompted, so the first gesture only asks once. */
export function hasAsked(): boolean {
  return localStorage.getItem(ASKED_KEY) === "1";
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
  const trimmed = [...seen].slice(-MAX_REMEMBERED);
  try {
    localStorage.setItem(SEEN_KEY, JSON.stringify(trimmed));
  } catch {
    /* storage full or blocked - announcing twice beats crashing */
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
 * Record a batch as seen without announcing it. Called once on the first poll
 * so the backlog does not arrive as a burst of alerts.
 */
export function primeSeen(items: Announceable[]): void {
  const seen = readSeen();
  for (const item of items) seen.add(item.id);
  writeSeen(seen);
}

/** Which items are new, marking them seen. Used for the in-app toasts too. */
export function takeUnseen(items: Announceable[]): Announceable[] {
  const seen = readSeen();
  const fresh = items.filter((item) => !seen.has(item.id));
  if (fresh.length === 0) return [];
  for (const item of fresh) seen.add(item.id);
  writeSeen(seen);
  return fresh;
}

/**
 * Raise system notifications for the given items, if the browser allows it.
 *
 * Vibrates on a phone that supports it, since a silent banner is easy to miss
 * in a pocket. `onClick` receives the link so the caller can route - a
 * notification cannot navigate a single-page app by itself.
 */
export function systemNotify(
  items: Announceable[],
  onClick: (link: string) => void,
): void {
  if (!isActive() || items.length === 0) return;

  // A burst is summarised rather than stacked: five popups for five enquiries
  // is worse than one saying five arrived.
  const summarise = items.length > 3;
  const toShow = summarise ? items.slice(0, 1) : items;

  for (const item of toShow) {
    try {
      const notification = new Notification(item.title, {
        body: summarise
          ? `${item.body ?? ""}\n+${items.length - 1} more waiting`.trim()
          : (item.body ?? undefined),
        tag: `steel-desk-${item.kind}`,
        icon: "/favicon.svg",
        badge: "/favicon.svg",
        // Android honours this; desktop ignores it harmlessly.
        ...({ vibrate: [120, 60, 120] } as object),
      });

      notification.onclick = () => {
        window.focus();
        if (item.link) onClick(item.link);
        notification.close();
      };
    } catch {
      /* refused - the toast and the bell still have it */
    }
  }
}
