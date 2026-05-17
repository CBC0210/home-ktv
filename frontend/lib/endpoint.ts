/**
 * Where the browser should reach the FastAPI backend.
 *
 * Zero-config default = LAN: the backend runs on the same host as the page,
 * on its own port (8000), so scanning the TV's QR code from a phone on the
 * same Wi-Fi just works — no Cloudflare, no reverse proxy, no env needed.
 *
 * Behind a single-origin reverse proxy / Cloudflare Tunnel, set
 * NEXT_PUBLIC_API_URL to the public origin (e.g. https://ktv.example.com)
 * — it is then used verbatim for HTTP and ws/wss is derived from it.
 *
 * NEXT_PUBLIC_* is inlined by Next at build time; the window branch only
 * runs in the browser (all callers are client components).
 */
const ENV_URL = (process.env.NEXT_PUBLIC_API_URL ?? "").trim().replace(/\/+$/, "");
const API_PORT = (process.env.NEXT_PUBLIC_API_PORT ?? "8000").trim();

export function apiBase(): string {
  if (ENV_URL) return ENV_URL;
  if (typeof window !== "undefined") {
    return `${window.location.protocol}//${window.location.hostname}:${API_PORT}`;
  }
  return "";
}

export function wsBase(): string {
  const b = apiBase();
  if (b) return b.replace(/^http/, "ws"); // http→ws, https→wss
  if (typeof window !== "undefined") {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    return `${proto}://${window.location.host}`;
  }
  return "";
}
