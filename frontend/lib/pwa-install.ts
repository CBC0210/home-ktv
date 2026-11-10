"use client";

import { useSyncExternalStore } from "react";

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

export interface PwaInstallState {
  canInstall: boolean;
  isInstalled: boolean;
  isStandalone: boolean;
  isIOS: boolean;
}

const serverState: PwaInstallState = {
  canInstall: false,
  isInstalled: false,
  isStandalone: false,
  isIOS: false,
};

let deferredPrompt: BeforeInstallPromptEvent | null = null;
let listening = false;
let state = serverState;
const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((listener) => listener());
}

function isIOSDevice() {
  const { userAgent, platform, maxTouchPoints } = window.navigator;
  return /iPhone|iPad|iPod/i.test(userAgent) || (platform === "MacIntel" && maxTouchPoints > 1);
}

function update(next: Partial<PwaInstallState>) {
  state = { ...state, ...next };
  emit();
}

function startListening() {
  if (listening || typeof window === "undefined") return;
  listening = true;

  const isStandalone =
    window.matchMedia("(display-mode: standalone)").matches ||
    (window.navigator as Navigator & { standalone?: boolean }).standalone === true;
  state = { ...state, isStandalone, isInstalled: isStandalone, isIOS: isIOSDevice() };

  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferredPrompt = event as BeforeInstallPromptEvent;
    update({ canInstall: true });
  });
  window.addEventListener("appinstalled", () => {
    deferredPrompt = null;
    update({ canInstall: false, isInstalled: true });
  });
}

function subscribe(listener: () => void) {
  startListening();
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot() {
  return state;
}

export function usePwaInstall() {
  return useSyncExternalStore(subscribe, getSnapshot, () => serverState);
}

/** Call only from a user gesture. Browser prompt events are single-use. */
export async function requestPwaInstall(): Promise<"accepted" | "dismissed" | "unavailable"> {
  const prompt = deferredPrompt;
  if (!prompt) return "unavailable";

  // Chrome permits prompt() only once for each beforeinstallprompt event. A
  // later browser event will restore canInstall; until then the UI gives its
  // manual browser-menu instructions instead of pretending another prompt works.
  deferredPrompt = null;
  update({ canInstall: false });

  try {
    await prompt.prompt();
    const choice = await prompt.userChoice;
    return choice.outcome;
  } catch {
    return "unavailable";
  }
}
