const offlineCache = "goldsignal-offline-v3";

self.addEventListener("install", event => {
  event.waitUntil(caches.open(offlineCache).then(cache => cache.add("/offline.html")).then(() => self.skipWaiting()));
});

self.addEventListener("activate", event => {
  event.waitUntil(Promise.all(["goldsignal-offline-v1", "goldsignal-offline-v2"].map(name => caches.delete(name)))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (event.request.mode !== "navigate" || url.origin !== self.location.origin ||
      !["/", "/admin"].includes(url.pathname)) return;
  event.respondWith(fetch(event.request).catch(() => caches.match("/offline.html", { cacheName: offlineCache })));
});

self.addEventListener("push", (event) => {
  const { id, title, body, url } = event.data.json();
  event.waitUntil(self.registration.showNotification(title, { body, tag: id, icon: "/app-icon-192.png", data: { url } }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL(event.notification.data.url, self.location.origin);
  if (url.origin === self.location.origin) event.waitUntil(self.clients.openWindow(url.href));
});
