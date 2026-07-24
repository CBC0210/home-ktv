import type { NextConfig } from "next";
import { readFileSync } from "node:fs";

// Per-build id (written by scripts/gen-build-id.mjs). Baked into the client as
// NEXT_PUBLIC_BUILD_ID and matched by public/build-id.txt so a running client
// can poll for a new deploy and auto-reload. Falls back to "dev" when unset.
let BUILD_ID = "dev";
try {
  BUILD_ID = readFileSync(new URL("./.build-id", import.meta.url), "utf8").trim() || "dev";
} catch {
  /* first run / dev — leave as "dev" */
}

// App pages must always be revalidated so a reload picks up the newest chunk
// hashes after a deploy (static assets under /_next/static stay immutable).
const NO_CACHE_PAGE = [{ key: "Cache-Control", value: "no-cache, must-revalidate" }];

// Baseline security headers for every page/asset the frontend serves.
// The Cloudflare Tunnel can't inject response headers, so they must originate
// here (and in the FastAPI middleware for /api & /songs).
//
// The CSP is intentionally permissive on script/connect so it works in BOTH
// the tunnel deployment and the zero-config LAN mode (page :3002 → API/WS
// :8000, a different origin), and so libass-wasm (WebAssembly + web worker)
// and Next's hydration inline scripts keep working. The high-value directives
// here are frame-ancestors (anti-clickjacking), object-src none and base-uri.
const CSP = [
  "default-src 'self'",
  "base-uri 'self'",
  "object-src 'none'",
  "frame-ancestors 'self'",
  "img-src 'self' https://img.youtube.com https://i.ytimg.com data: blob:",
  "media-src 'self' blob: data:",
  "font-src 'self' data:",
  "style-src 'self' 'unsafe-inline'",
  "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://static.cloudflareinsights.com",
  "worker-src 'self' blob:",
  "connect-src 'self' https: http: wss: ws:",
].join("; ");

const SECURITY_HEADERS = [
  { key: "X-Frame-Options", value: "SAMEORIGIN" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" },
  { key: "Content-Security-Policy", value: CSP },
];

const nextConfig: NextConfig = {
  output: "standalone",
  generateBuildId: async () => BUILD_ID,
  env: { NEXT_PUBLIC_BUILD_ID: BUILD_ID },
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "img.youtube.com" },
      { protocol: "https", hostname: "i.ytimg.com" },
    ],
  },
  async headers() {
    return [
      { source: "/:path*", headers: SECURITY_HEADERS },
      // Always-revalidate the interactive pages so a reload gets the new build.
      { source: "/", headers: NO_CACHE_PAGE },
      { source: "/rooms", headers: NO_CACHE_PAGE },
      { source: "/admin", headers: NO_CACHE_PAGE },
      { source: "/r/:path*", headers: NO_CACHE_PAGE },
      // The version file must never be cached — it's the update signal.
      { source: "/build-id.txt", headers: [{ key: "Cache-Control", value: "no-store" }] },
    ];
  },
};

export default nextConfig;
