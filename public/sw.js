self.addEventListener("push", (event) => {
  const { id, title, body, url } = event.data.json();
  event.waitUntil(self.registration.showNotification(title, { body, tag: id, data: { url } }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL(event.notification.data.url, self.location.origin);
  if (url.origin === self.location.origin) event.waitUntil(self.clients.openWindow(url.href));
});
