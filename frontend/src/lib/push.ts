/* Firebase Cloud Messaging: system notifications that arrive with the site
   closed.

   This is the gap the existing `notifications.ts` cannot fill. That module
   uses the browser Notification API directly, which only fires while a tab is
   open - close the dashboard and a trader hears nothing. FCM hands delivery
   to the operating system via a service worker, so the buzz arrives whether
   or not the site is running.

   The two are complements, not rivals:
     - tab open   -> `onMessage` here, routed to the existing toast layer, so
                     the trader is not buzzed by the OS about something already
                     on screen;
     - tab closed -> `firebase-messaging-sw.js` shows the system notification.

   Everything degrades quietly. No Firebase config, no service worker support,
   permission denied, iOS Safari without the site installed - each returns a
   reason rather than throwing, because a desk with push unavailable must
   still work exactly as it did before. */

import { api } from "../api/client";

export interface PushStatus {
  configured: boolean;
  devices: number;
}

/** Read from Vite env so no key is committed. Absent values leave push
 *  inactive rather than half-configured. */
const CONFIG = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
};

const VAPID_KEY = import.meta.env.VITE_FIREBASE_VAPID_KEY;

export type PushOutcome =
  | { ok: true; token: string }
  | { ok: false; reason: string };

export function isConfigured(): boolean {
  return Boolean(CONFIG.apiKey && CONFIG.projectId && VAPID_KEY);
}

export function isSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    "serviceWorker" in navigator &&
    "Notification" in window &&
    "PushManager" in window
  );
}

/** A name a person can recognise in a list of their devices.
 *
 *  Derived from the user agent rather than asked for: nobody will type
 *  "Rajesh's phone" into a field, and an unlabelled list of tokens is one
 *  nobody can safely revoke from. */
function deviceLabel(): string {
  const ua = navigator.userAgent;
  const browser = /Edg\//.test(ua)
    ? "Edge"
    : /Chrome\//.test(ua)
      ? "Chrome"
      : /Safari\//.test(ua)
        ? "Safari"
        : /Firefox\//.test(ua)
          ? "Firefox"
          : "Browser";
  const platform = /Android/.test(ua)
    ? "Android"
    : /iPhone|iPad/.test(ua)
      ? "iOS"
      : /Macintosh/.test(ua)
        ? "Mac"
        : /Windows/.test(ua)
          ? "Windows"
          : "device";
  return `${browser} on ${platform}`;
}

let registration: ServiceWorkerRegistration | null = null;

/** Register the worker and hand it the Firebase config.
 *
 *  The config travels by postMessage rather than living in the worker file,
 *  so one static file serves every environment and no key is committed. */
/** Reject if `promise` has not settled within `ms`.
 *
 *  Used to bound calls that can otherwise wait for ever. A rejection the
 *  caller can show beats a spinner that never stops: the first tells someone
 *  what to check, the second is indistinguishable from a broken button. */
function withTimeout<T>(promise: Promise<T>, ms: number, message: string): Promise<T> {
  return Promise.race([
    promise,
    new Promise<T>((_, reject) => setTimeout(() => reject(new Error(message)), ms)),
  ]);
}

/** Resolve once this registration has a worker that can receive a message.
 *
 *  `navigator.serviceWorker.ready` is not enough on a first install: it
 *  resolves for whatever registration currently controls the page, which on
 *  the very first visit is not the one just created. The config was then
 *  posted to an `installing` worker that had no `message` listener yet, the
 *  worker never called `start()`, and `getToken` hung or failed with nothing
 *  on screen to explain it - which is exactly "clicking does nothing".
 */
function activeWorker(reg: ServiceWorkerRegistration): Promise<ServiceWorker> {
  if (reg.active) return Promise.resolve(reg.active);

  return new Promise((resolve, reject) => {
    const pending = reg.installing ?? reg.waiting;
    if (!pending) {
      reject(new Error("The service worker registered but produced no worker."));
      return;
    }
    const timer = setTimeout(
      () => reject(new Error("The notification service worker did not start in time.")),
      10_000,
    );
    pending.addEventListener("statechange", () => {
      if (pending.state === "activated") {
        clearTimeout(timer);
        resolve(pending);
      }
      if (pending.state === "redundant") {
        clearTimeout(timer);
        reject(new Error("The notification service worker failed to install."));
      }
    });
  });
}

async function ensureWorker(): Promise<ServiceWorkerRegistration> {
  if (registration) return registration;

  const reg = await withTimeout(
    navigator.serviceWorker.register("/firebase-messaging-sw.js"),
    10_000,
    "The notification service worker could not be registered.",
  );

  // Wait for a worker that is actually running before handing it the config,
  // and confirm it received it. The worker also asks on its own activation,
  // so the two approaches cover each other whichever wins the race.
  const worker = await activeWorker(reg);
  worker.postMessage({ type: "FIREBASE_CONFIG", config: CONFIG });

  registration = reg;
  return reg;
}

/** Ask for permission, get a token, and register it with the desk.
 *
 *  Safe to call on every load once permission exists, and the app does: FCM
 *  rotates tokens on its own schedule, so a browser that registered once and
 *  never again would quietly stop receiving anything. */
/** Answer a worker that starts up and asks which project it belongs to.
 *
 *  A service worker is stopped and restarted freely by the browser, and it
 *  loses `messaging` every time. Without this it would stay uninitialised
 *  until the next `ensureWorker`, and a background notification arriving in
 *  between would be dropped. */
if (typeof navigator !== "undefined" && "serviceWorker" in navigator) {
  navigator.serviceWorker.addEventListener("message", (event) => {
    if (event.data?.type === "FIREBASE_CONFIG_REQUEST") {
      event.source?.postMessage({ type: "FIREBASE_CONFIG", config: CONFIG });
    }
  });
}

export async function enablePush(): Promise<PushOutcome> {
  if (!isConfigured()) {
    return { ok: false, reason: "Push is not configured for this desk." };
  }
  if (!isSupported()) {
    // iOS only exposes these APIs once the site is on the home screen, which
    // is worth saying rather than failing silently.
    const ios = /iPhone|iPad|iPod/.test(navigator.userAgent);
    return {
      ok: false,
      reason: ios
        ? "On iPhone, add Oprisa to your home screen first, then turn this on."
        : "This browser cannot receive push notifications.",
    };
  }

  let permission = Notification.permission;
  if (permission === "default") permission = await Notification.requestPermission();
  if (permission !== "granted") {
    return { ok: false, reason: "Notifications are blocked in your browser settings." };
  }

  try {
    const [{ initializeApp, getApps }, { getMessaging, getToken }] = await Promise.all([
      import("firebase/app"),
      import("firebase/messaging"),
    ]);

    const app = getApps().length ? getApps()[0] : initializeApp(CONFIG);
    const worker = await ensureWorker();

    // `getToken` can hang indefinitely - a blocked push service, a VAPID key
    // the project does not recognise, a network that accepts the connection
    // and never answers. It has no timeout of its own, so without this the
    // whole call never settles, the caller's `finally` never runs, and the
    // button sits on "Working…" for ever with nothing to explain why.
    const token = await withTimeout(
      getToken(getMessaging(app), {
        vapidKey: VAPID_KEY,
        serviceWorkerRegistration: worker,
      }),
      15_000,
      "Firebase did not return a token in time. Check the VAPID key and that "
        + "notifications are reachable from this network.",
    );

    if (!token) return { ok: false, reason: "The browser did not return a token." };

    await api.post("/push/devices", {
      token,
      label: deviceLabel(),
      user_agent: navigator.userAgent.slice(0, 300),
    });

    return { ok: true, token };
  } catch (e) {
    return { ok: false, reason: (e as Error).message };
  }
}

/** Deliver foreground messages through the app's own toast layer.
 *
 *  Without this the OS would buzz about a notification already visible on
 *  screen, which reads as the app talking over itself. Returns a teardown. */
export async function listenInForeground(
  onMessage: (title: string, body: string, link?: string) => void,
): Promise<() => void> {
  if (!isConfigured() || !isSupported() || Notification.permission !== "granted") {
    return () => {};
  }
  try {
    const [{ initializeApp, getApps }, messagingModule] = await Promise.all([
      import("firebase/app"),
      import("firebase/messaging"),
    ]);
    const app = getApps().length ? getApps()[0] : initializeApp(CONFIG);
    return messagingModule.onMessage(messagingModule.getMessaging(app), (payload) => {
      const note = payload.notification ?? {};
      onMessage(note.title ?? "Oprisa", note.body ?? "", payload.fcmOptions?.link);
    });
  } catch {
    return () => {};
  }
}

export function pushStatus(): Promise<PushStatus> {
  return api.get<PushStatus>("/push/status");
}
