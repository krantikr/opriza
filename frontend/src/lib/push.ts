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
async function ensureWorker(): Promise<ServiceWorkerRegistration> {
  if (registration) return registration;

  registration = await navigator.serviceWorker.register("/firebase-messaging-sw.js");
  await navigator.serviceWorker.ready;

  const target = registration.active ?? registration.waiting ?? registration.installing;
  target?.postMessage({ type: "FIREBASE_CONFIG", config: CONFIG });

  return registration;
}

/** Ask for permission, get a token, and register it with the desk.
 *
 *  Safe to call on every load once permission exists, and the app does: FCM
 *  rotates tokens on its own schedule, so a browser that registered once and
 *  never again would quietly stop receiving anything. */
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
        ? "On iPhone, add Steel Desk to your home screen first, then turn this on."
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
    const token = await getToken(getMessaging(app), {
      vapidKey: VAPID_KEY,
      serviceWorkerRegistration: worker,
    });

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
      onMessage(note.title ?? "Steel Desk", note.body ?? "", payload.fcmOptions?.link);
    });
  } catch {
    return () => {};
  }
}

export function pushStatus(): Promise<PushStatus> {
  return api.get<PushStatus>("/push/status");
}
