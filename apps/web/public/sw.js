// Service worker: shows push notifications and opens the app when one is clicked. It never reads
// the API or any stored session, and never shows SMS text: the server only sends who it is from.
// Plain JavaScript on purpose (it is served as is, not bundled), and a function body so a test can
// run it against a fake `self`.

const FALLBACK_TITLE = "New message";

// Only the app's own pages: a notification must not be able to send someone elsewhere.
function ownUrl(value) {
  if (typeof value !== "string" || !value) return "/";
  try {
    const url = new URL(value, self.location.origin);
    if (url.origin === self.location.origin) return url.pathname + url.search + url.hash;
  } catch {
    // fall through
  }
  return "/";
}

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = {};
  }
  if (!data || typeof data !== "object") data = {};
  const text = (value) => (typeof value === "string" ? value : undefined);
  // Always show something: a browser may withdraw permission from a site that receives a push and
  // shows nothing.
  event.waitUntil(
    self.registration.showNotification(text(data.title) || FALLBACK_TITLE, {
      body: text(data.body) || "",
      tag: text(data.tag),
      icon: "/icon-192.png",
      data: { url: ownUrl(data.url) },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = ownUrl(event.notification.data && event.notification.data.url);
  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      const open = windows.find((w) => new URL(w.url).origin === self.location.origin);
      if (open) {
        await open.focus();
        if (open.navigate) await open.navigate(url);
        return;
      }
      await self.clients.openWindow(url);
    })(),
  );
});
