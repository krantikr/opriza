/* Firebase messaging service worker.
 *
 * This file is why push works with the site closed. A service worker runs
 * outside any page, so the browser can wake it to show a notification when
 * every tab is gone - which the in-app bell and the plain Notification API
 * cannot do, because both need a live page.
 *
 * It must be served from the origin root at exactly this filename: the
 * Firebase SDK registers `/firebase-messaging-sw.js` by convention, and a
 * worker can only control pages at or below its own path. Hence `public/`
 * rather than `src/` - it is copied verbatim and never bundled.
 *
 * Config is injected at runtime rather than hard-coded. The page posts it
 * over on registration, so the same worker file works across environments
 * and no key is baked into a file committed to the repository.
 */

/* global importScripts, firebase, clients */

importScripts("https://www.gstatic.com/firebasejs/10.14.1/firebase-app-compat.js");
importScripts("https://www.gstatic.com/firebasejs/10.14.1/firebase-messaging-compat.js");

let messaging = null;

/** Start Firebase once the page has told us which project to talk to. */
function start(config) {
  if (messaging || !config || !config.apiKey) return;
  firebase.initializeApp(config);
  messaging = firebase.messaging();

  // Background messages: the tab is closed or hidden. Foreground delivery is
  // handled in the page by `onMessage`, so the two never both fire for one
  // notification and the trader gets a single buzz.
  messaging.onBackgroundMessage((payload) => {
    const note = payload.notification || {};
    const link = (payload.fcmOptions && payload.fcmOptions.link) || "/";

    self.registration.showNotification(note.title || "Steel Desk", {
      body: note.body || "",
      icon: "/favicon-192.png",
      badge: "/favicon-192.png",
      // Same tag collapses repeats about one subject instead of stacking a
      // column of near-identical buzzes.
      tag: link,
      renotify: true,
      data: { link },
    });
  });
}

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "FIREBASE_CONFIG") {
    start(event.data.config);
  }
});

/* Take over straight away rather than waiting for every tab to close.
 *
 * Without these, a newly installed worker sits in `waiting` until the last
 * tab using the old one goes away - so the first time a trader turns
 * notifications on, the worker they just registered is not the one running,
 * and nothing they do reaches it. */
self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil(
    self.clients.claim().then(function () {
      /* Ask for the config rather than only waiting to be told.
       *
       * The browser stops and restarts a service worker whenever it likes,
       * and `messaging` does not survive that - so a worker can wake to
       * handle a push with no idea which project it belongs to. Asking any
       * open page on every activation is what makes it self-healing. */
      return self.clients.matchAll({ type: "window", includeUncontrolled: true });
    }).then(function (tabs) {
      tabs.forEach(function (tab) {
        tab.postMessage({ type: "FIREBASE_CONFIG_REQUEST" });
      });
    }),
  );
});

/* Tapping a notification should land on the thing it is about.
 *
 * An already-open tab is focused and navigated rather than a second one
 * opened: a trader who taps three notifications should not end up with three
 * copies of the dashboard. */
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const link = (event.notification.data && event.notification.data.link) || "/";
  const url = new URL(link, self.location.origin).href;

  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((tabs) => {
      for (const tab of tabs) {
        if ("focus" in tab) {
          if ("navigate" in tab) tab.navigate(url);
          return tab.focus();
        }
      }
      return clients.openWindow(url);
    }),
  );
});
