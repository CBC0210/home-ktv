// Minimal service worker — required for Chrome/Android PWA installability.
// Network-first, and it deliberately caches NOTHING (API/WS/media are live
// data; the app shell/chunks are always fetched fresh). On activate it purges
// any caches left by older versions so a stale asset can never be served.
// Client-side auto-update (polling /build-id.txt → reload) lives in
// components/shared/AppUpdater.tsx.
const SW_VERSION = "v2-nocache";

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(keys.map((k) => caches.delete(k)));
      await self.clients.claim();
    })()
  );
});

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
  // Network-only; no cache fallback so nothing stale is ever served.
  event.respondWith(fetch(event.request).catch(() => Response.error()));
});
