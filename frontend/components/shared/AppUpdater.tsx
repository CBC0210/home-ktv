"use client";

import { useEffect } from "react";

// Keeps every open tab (Remote / Player / Admin) on the latest deploy without
// the user ever clearing cache:
//   1. Polls /build-id.txt; if the server's build id differs from the one this
//      bundle was built with, a new version is live → reload once.
//   2. Backstop: if a lazily-loaded chunk 404s (its file was replaced by a new
//      deploy), reload to fetch the current bundle.
// The reload gets fresh HTML (pages are served no-cache) with the new chunk
// hashes, so the app self-heals after every deploy.

const MY_BUILD = process.env.NEXT_PUBLIC_BUILD_ID || "dev";
const POLL_MS = 60_000;

export default function AppUpdater() {
  useEffect(() => {
    let reloading = false;
    const reload = () => {
      if (reloading) return;
      reloading = true;
      // Cache-bust the navigation so we never re-load a stale HTML.
      const u = new URL(window.location.href);
      u.searchParams.set("_v", Date.now().toString());
      window.location.replace(u.toString());
    };

    async function checkVersion() {
      if (document.visibilityState !== "visible") return;
      try {
        const res = await fetch(`/build-id.txt?ts=${Date.now()}`, { cache: "no-store" });
        if (!res.ok) return;
        const serverBuild = (await res.text()).trim();
        if (serverBuild && MY_BUILD !== "dev" && serverBuild !== MY_BUILD) {
          reload();
        }
      } catch {
        /* offline / transient — try again next tick */
      }
    }

    const timer = setInterval(checkVersion, POLL_MS);
    const onVisible = () => { if (document.visibilityState === "visible") void checkVersion(); };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("online", onVisible);
    // First check shortly after mount.
    const kickoff = setTimeout(checkVersion, 4000);

    // Backstop: a failed chunk load right after a deploy → reload once.
    const isChunkError = (msg: string) =>
      /ChunkLoadError|Loading chunk [\w-]+ failed|Loading CSS chunk|error loading dynamically imported module|Importing a module script failed/i.test(msg);
    const onError = (e: ErrorEvent) => { if (isChunkError(e?.message || "")) reload(); };
    const onRejection = (e: PromiseRejectionEvent) => {
      const m = (e?.reason && (e.reason.message || String(e.reason))) || "";
      if (isChunkError(m)) reload();
    };
    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onRejection);

    return () => {
      clearInterval(timer);
      clearTimeout(kickoff);
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("online", onVisible);
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejection);
    };
  }, []);

  return null;
}
