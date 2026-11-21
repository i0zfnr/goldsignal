const offlineCache = "xeniex-offline-v1";

self.addEventListener("install", event => {
  event.waitUntil(caches.open(offlineCache).then(cache => cache.add("/offline.html")).then(() => self.skipWaiting()));
});

self.addEventListener("activate", event => {
  event.waitUntil(Promise.all(["goldsignal-offline-v3", "xeniex-offline-v1"].map(name => caches.delete(name)))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (event.request.mode !== "navigate" || url.origin !== self.location.origin ||
      !["/", "/admin"].includes(url.pathname)) return;
  event.respondWith(fetch(event.request).catch(() => caches.match("/offline.html", { cacheName: offlineCache })));
});

const demoContext = crypto.randomUUID();

function demoDatabase() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open("goldsignal-demo-timing", 1);
    request.onupgradeneeded = () => request.result.createObjectStore("outbox", { keyPath: "id" });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function demoStore(action, value) {
  const db = await demoDatabase();
  try {
    return await new Promise((resolve, reject) => {
      const transaction = db.transaction("outbox", "readwrite");
      const store = transaction.objectStore("outbox");
      const request = action === "put" ? store.put(value) : action === "delete" ? store.delete(value) : store.getAll();
      let result;
      request.onsuccess = () => { result = request.result; };
      transaction.oncomplete = () => resolve(result);
      transaction.onerror = () => reject(transaction.error);
    });
  } finally { db.close(); }
}

async function demoRecord(demo, stage) {
  if (!demo) return;
  const client_at = Date.now() / 1000;
  const monotonic = performance.now() / 1000;
  await demoStore("put", { id: `${demo.attempt}:${stage}`, ...demo, stage, client_at,
    monotonic, context: demoContext, clock_offset: null, clock_uncertainty: null });
}

async function demoFlush() {
  const rows = await demoStore("all");
  if (!rows.length) return;
  let clock_offset = null, clock_uncertainty = null, clock_calibrated_at = null;
  try {
    const start = Date.now() / 1000;
    const clock = await fetch("/api/demo/clock", { cache: "no-store" });
    if (clock.ok) {
      const data = await clock.json();
      const end = Date.now() / 1000;
      clock_offset = data.server_at - (start + end) / 2;
      clock_uncertainty = (end - start) / 2;
      clock_calibrated_at = (start + end) / 2;
    }
  } catch {}
  for (const row of rows.slice(0, 100)) {
    const { id, ...body } = row;
    try {
      const response = await fetch("/api/demo/phone-event", { method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...body, clock_offset, clock_uncertainty, clock_calibrated_at }) });
      if (response.ok || response.status === 410) await demoStore("delete", id);
    } catch { break; }
  }
}

self.addEventListener("push", (event) => {
  const { id, title, body, url, demo } = event.data.json();
  event.waitUntil((async () => {
    if (demo) await demoRecord(demo, "push_handled").catch(() => {});
    await self.registration.showNotification(title, { body, tag: id, icon: "/app-icon-192.png", data: { url, demo } });
    if (demo) {
      await demoRecord(demo, "notification_shown").catch(() => {});
      await demoFlush().catch(() => {});
    }
  })());
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL(event.notification.data.url, self.location.origin);
  if (url.origin === self.location.origin) event.waitUntil((async () => {
    const demo = event.notification.data.demo;
    const measurement = demo ? demoRecord(demo, "notification_click").catch(() => {}) : Promise.resolve();
    await self.clients.openWindow(url.href);
    await measurement;
    if (demo) await demoFlush().catch(() => {});
  })());
});

self.addEventListener("message", event => {
  if (event.data?.type === "DEMO_FLUSH") event.waitUntil(demoFlush().catch(() => {}));
});
