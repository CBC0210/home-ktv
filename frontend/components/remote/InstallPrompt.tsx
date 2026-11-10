"use client";

import { useEffect, useState } from "react";
import { requestPwaInstall, usePwaInstall } from "@/lib/pwa-install";

export default function InstallPrompt() {
  const [show, setShow] = useState(false);
  const { canInstall, isIOS, isInstalled } = usePwaInstall();

  useEffect(() => {
    // Register the service worker (required for installability)
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => {});
    }

    if (localStorage.getItem("ktv_install_dismissed") === "1") return;
  }, []);

  useEffect(() => {
    if (!isInstalled && localStorage.getItem("ktv_install_dismissed") !== "1" && (canInstall || isIOS)) setShow(true);
  }, [canInstall, isIOS, isInstalled]);

  if (!show || isInstalled) return null;

  function dismiss() {
    setShow(false);
    localStorage.setItem("ktv_install_dismissed", "1");
  }

  async function install() {
    const outcome = await requestPwaInstall();
    if (outcome !== "unavailable") setShow(false);
  }

  return (
    <div className="fixed bottom-20 left-3 right-3 z-40 bg-[#1a1a1a] border border-violet-500/30 rounded-2xl px-4 py-3 shadow-2xl flex items-center gap-3">
      <div className="w-9 h-9 rounded-xl bg-violet-600 flex items-center justify-center flex-shrink-0 text-lg">
        🎤
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-white text-sm font-medium">下載到桌面當 App 用</p>
        {isIOS ? (
          <p className="text-white/45 text-[11px] mt-0.5 leading-snug">
            點 Safari 分享鈕 <span className="text-white/70">⎙</span> →「加入主畫面」
          </p>
        ) : (
          <p className="text-white/45 text-[11px] mt-0.5">全螢幕、開啟更快</p>
        )}
      </div>
      {!isIOS && canInstall && (
        <button
          onClick={install}
          className="px-3.5 py-2 rounded-xl bg-violet-600 hover:bg-violet-500 text-white text-xs font-medium flex-shrink-0 transition-colors"
        >
          下載
        </button>
      )}
      <button
        onClick={dismiss}
        className="text-white/30 hover:text-white/60 text-lg w-7 h-7 flex items-center justify-center flex-shrink-0"
        aria-label="關閉"
      >
        ✕
      </button>
    </div>
  );
}
