"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import type { ServerEvent, ClientCommand } from "./types";
import { wsBase } from "./endpoint";

function buildWsUrl(
  roomId: string,
  token: string | null,
  role: string
): string {
  const params = new URLSearchParams({ room_id: roomId, role });
  if (token) params.set("token", token);
  return `${wsBase()}/ws?${params}`;
}

/** Server closes with 4001 when the JWT is invalid or expired. */
const WS_CLOSE_AUTH_FAILED = 4001;
/** App-level heartbeat: Cloudflare Tunnel kills idle WS after ~100s, and a
 * network switch can leave a half-open socket stuck at readyState OPEN. */
const PING_INTERVAL_MS = 25_000;
/** No message of any kind for this long → assume dead, force a reconnect. */
const DEAD_SOCKET_MS = 75_000;

export function useWebSocket(
  roomId: string,
  token: string | null,
  role: "player" | "remote" | "admin",
  onEvent: (event: ServerEvent) => void,
  onConnected?: () => void,
  onAuthFailed?: () => void,
): { sendCommand: (cmd: ClientCommand) => boolean; connected: boolean } {
  const wsRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const onEventRef = useRef(onEvent);
  const onConnectedRef = useRef(onConnected);
  const onAuthFailedRef = useRef(onAuthFailed);
  onEventRef.current = onEvent;
  onConnectedRef.current = onConnected;
  onAuthFailedRef.current = onAuthFailed;

  /** Returns true if the command was actually written to an OPEN socket —
   * callers that must not lose a message (e.g. player.ended) can queue and
   * resend on the next onConnected. */
  const sendCommand = useCallback((cmd: ClientCommand): boolean => {
    const ws = wsRef.current;
    if (ws?.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify(cmd));
        return true;
      } catch (err) {
        console.warn("[WS] send failed:", err);
        return false;
      }
    }
    console.warn(`[WS] dropped ${cmd.type} (readyState=${ws?.readyState ?? "null"})`);
    return false;
  }, []);

  useEffect(() => {
    // Skip until we have a token (except player which connects unauthenticated)
    if (role !== "player" && !token) return;

    let destroyed = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let retryDelay = 1000;
    let lastMessageAt = Date.now();

    function connect() {
      if (destroyed) return;
      const url = buildWsUrl(roomId, token, role);
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        retryDelay = 1000;
        lastMessageAt = Date.now();
        console.info(`[WS] connected as ${role}`);
        onConnectedRef.current?.();
      };
      ws.onmessage = (e) => {
        lastMessageAt = Date.now();
        try {
          const parsed = JSON.parse(e.data as string) as { type?: string };
          if (parsed.type === "pong") return; // heartbeat reply — not an app event
          onEventRef.current(parsed as ServerEvent);
        } catch {
          // ignore malformed messages
        }
      };
      ws.onclose = (e) => {
        setConnected(false);
        if (wsRef.current === ws) wsRef.current = null;
        if (destroyed) return;
        if (e.code === WS_CLOSE_AUTH_FAILED) {
          // Token rejected — retrying with the same dead token would loop
          // forever. Tell the owner so it can re-join / drop the session.
          console.warn("[WS] auth failed (4001) — session token rejected");
          onAuthFailedRef.current?.();
          return;
        }
        console.info(`[WS] closed (code=${e.code}), retry in ${retryDelay}ms`);
        retryTimer = setTimeout(() => {
          retryDelay = Math.min(retryDelay * 2, 30000);
          connect();
        }, retryDelay);
      };
      ws.onerror = () => {
        // onclose will fire next; nothing else to do
      };
    }

    // Heartbeat: keep the tunnel connection warm and detect half-open
    // sockets (send() into a dead TCP connection raises no error).
    const heartbeat = setInterval(() => {
      const ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      if (Date.now() - lastMessageAt > DEAD_SOCKET_MS) {
        console.warn("[WS] no traffic — assuming dead socket, reconnecting");
        try { ws.close(); } catch { /* onclose schedules the retry */ }
        return;
      }
      try { ws.send(JSON.stringify({ type: "ping" })); } catch { /* ignore */ }
    }, PING_INTERVAL_MS);

    // When the tab becomes visible again on mobile, kick a reconnect if needed
    function handleVisibility() {
      if (document.visibilityState !== "visible") return;
      const ws = wsRef.current;
      if (!ws || ws.readyState >= WebSocket.CLOSING) {
        if (retryTimer) { clearTimeout(retryTimer); retryTimer = null; }
        retryDelay = 1000;
        connect();
      }
    }

    document.addEventListener("visibilitychange", handleVisibility);
    window.addEventListener("online", handleVisibility);

    connect();
    return () => {
      destroyed = true;
      clearInterval(heartbeat);
      document.removeEventListener("visibilitychange", handleVisibility);
      window.removeEventListener("online", handleVisibility);
      if (retryTimer) clearTimeout(retryTimer);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [roomId, token, role]);

  return { sendCommand, connected };
}
