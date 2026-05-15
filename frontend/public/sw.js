// Minimal service worker — required for Chrome/Android PWA installability.
// Network-first; we deliberately do NOT cache API/WS/media (live data).
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  // Never intercept API, websocket, or media/song streams.
  if (
    url.pathname.startsWith("/api/") ||
    url.pathname.startsWith("/ws") ||
    url.pathname.startsWith("/songs/")
  ) {
    return;
  }
  event.respondWith(
    fetch(event.request).catch(
      () => caches.match(event.request).then((r) => r || Response.error())
    )
  );
});
