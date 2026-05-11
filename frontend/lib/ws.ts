"use client";

import { useEffect, useRef, useCallback } from "react";
import type { ServerEvent, ClientCommand } from "./types";

function buildWsUrl(
  roomId: string,
  token: string | null,
  role: string
): string {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "";
  let wsBase: string;
  if (apiUrl) {
    wsBase = apiUrl.replace(/^https/, "wss").replace(/^http/, "ws");
  } else {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    wsBase = `${proto}://${window.location.host}`;
  }
  const params = new URLSearchParams({ room_id: roomId, role });
  if (token) params.set("token", token);
  return `${wsBase}/ws?${params}`;
}

export function useWebSocket(
  roomId: string,
  token: string | null,
  role: "player" | "remote" | "admin",
  onEvent: (event: ServerEvent) => void
): { sendCommand: (cmd: ClientCommand) => void; connected: boolean } {
  const wsRef = useRef<WebSocket | null>(null);
  const connectedRef = useRef(false);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  const sendCommand = useCallback((cmd: ClientCommand) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(cmd));
    }
  }, []);

  useEffect(() => {
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
      };
      ws.onmessage = (e) => {
        try {
          onEventRef.current(JSON.parse(e.data as string) as ServerEvent);
        } catch {
          // ignore malformed messages
        }
      };
      ws.onclose = () => {
        connectedRef.current = false;
        wsRef.current = null;
        if (!destroyed) {
          retryTimer = setTimeout(() => {
            retryDelay = Math.min(retryDelay * 2, 30000);
            connect();
          }, retryDelay);
        }
      };
    }

    connect();
    return () => {
      destroyed = true;
      if (retryTimer) clearTimeout(retryTimer);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [roomId, token, role]);

  return { sendCommand, connected: connectedRef.current };
}
