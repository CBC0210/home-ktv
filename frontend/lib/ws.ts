"use client";

import { useEffect, useRef, useCallback } from "react";
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

export function useWebSocket(
  roomId: string,
  token: string | null,
  role: "player" | "remote" | "admin",
  onEvent: (event: ServerEvent) => void,
  onConnected?: () => void,
): { sendCommand: (cmd: ClientCommand) => void; connected: boolean } {
  const wsRef = useRef<WebSocket | null>(null);
  const connectedRef = useRef(false);
  const onEventRef = useRef(onEvent);
  const onConnectedRef = useRef(onConnected);
  onEventRef.current = onEvent;
  onConnectedRef.current = onConnected;

  const sendCommand = useCallback((cmd: ClientCommand) => {
    const ws = wsRef.current;
    if (ws?.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify(cmd));
      } catch (err) {
        console.warn("[WS] send failed:", err);
      }
    } else {
      console.warn(`[WS] dropped ${cmd.type} (readyState=${ws?.readyState ?? "null"})`);
    }
  }, []);

  useEffect(() => {
    // Skip until we have a token (except player which connects unauthenticated)
    if (role !== "player" && !token) return;

    let destroyed = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let retryDelay = 1000;

    function connect() {
      if (destroyed) return;
      const url = buildWsUrl(roomId, token, role);
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        connectedRef.current = true;
        retryDelay = 1000;
        console.info(`[WS] connected as ${role}`);
        onConnectedRef.current?.();
      };
      ws.onmessage = (e) => {
        try {
          onEventRef.current(JSON.parse(e.data as string) as ServerEvent);
        } catch {
          // ignore malformed messages
        }
      };
      ws.onclose = (e) => {
        connectedRef.current = false;
        if (wsRef.current === ws) wsRef.current = null;
        if (!destroyed) {
          console.info(`[WS] closed (code=${e.code}), retry in ${retryDelay}ms`);
          retryTimer = setTimeout(() => {
            retryDelay = Math.min(retryDelay * 2, 30000);
            connect();
          }, retryDelay);
        }
      };
      ws.onerror = () => {
        // onclose will fire next; nothing else to do
      };
    }

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
      document.removeEventListener("visibilitychange", handleVisibility);
      window.removeEventListener("online", handleVisibility);
      if (retryTimer) clearTimeout(retryTimer);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [roomId, token, role]);

  return { sendCommand, connected: connectedRef.current };
}
