"use client";

import { useEffect, useState, useCallback } from "react";
import { useKtvStore } from "@/lib/stores";
import { useWebSocket } from "@/lib/ws";
import { getRoom, getQueue, getOnlineGuests } from "@/lib/api";
import type { GuestSession, ServerEvent, ClientCommand } from "@/lib/types";
import JoinForm from "./JoinForm";
import NowPlaying from "./NowPlaying";
import QueueList from "./QueueList";
import SearchView from "./SearchView";
import RoomTab from "./RoomTab";

type Tab = "playing" | "queue" | "search" | "room";

interface Props {
  roomId: string;
}

export default function RemoteView({ roomId }: Props) {
  const [tab, setTab] = useState<Tab>("playing");
  const [session, setSession] = useState<GuestSession | null>(null);
  const [loadingSession, setLoadingSession] = useState(true);
  const [hasPassword, setHasPassword] = useState(false);

  const {
    room,
    queue,
    currentSong,
    currentQueueItem,
    playback,
    guests,
    processing,
    setRoom,
    setQueue,
    setSession: storeSetSession,
    setCurrentSong,
    setPlayback,
    setGuests,
    setProcessing,
    updatePosition,
  } = useKtvStore();

  // Restore session from localStorage
  useEffect(() => {
    const stored = localStorage.getItem(`ktv_session_${roomId}`);
    if (stored) {
      try {
        setSession(JSON.parse(stored) as GuestSession);
      } catch {
        localStorage.removeItem(`ktv_session_${roomId}`);
      }
    }
    setLoadingSession(false);
  }, [roomId]);

  // Load room info
  useEffect(() => {
    getRoom(roomId)
      .then((r) => {
        setRoom(r);
        setHasPassword(r.has_password);
      })
      .catch(() => {});
  }, [roomId, setRoom]);

  // Load queue on mount
  useEffect(() => {
    if (!session) return;
    getQueue(roomId)
      .then(setQueue)
      .catch(() => {});
  }, [roomId, session, setQueue]);

  // Fetch initial online guests (WS events keep it updated after that)
  useEffect(() => {
    if (!session) return;
    getOnlineGuests(roomId)
      .then(setGuests)
      .catch(() => {});
  }, [roomId, session, setGuests]);

  // Sync session to store
  useEffect(() => {
    storeSetSession(session);
  }, [session, storeSetSession]);

  const handleEvent = useCallback(
    (event: ServerEvent) => {
      if (event.type === "queue.updated") setQueue(event.queue);
      else if (event.type === "song.started")
        setCurrentSong(event.song, event.queueItem);
      else if (event.type === "song.progress")
        updatePosition(event.positionSec);
      else if (event.type === "song.ended") setCurrentSong(null, null);
      else if (event.type === "playback.state") setPlayback(event.state);
      else if (event.type === "guests.updated") setGuests(event.guests);
      else if (event.type === "song.processing")
        setProcessing({ stage: event.stage, percent: event.percent });
    },
    [
      setQueue,
      setCurrentSong,
      updatePosition,
      setPlayback,
      setGuests,
      setProcessing,
    ]
  );

  const { sendCommand } = useWebSocket(
    roomId,
    session?.token ?? null,
    "remote",
    handleEvent
  );

  function handleJoined(s: GuestSession) {
    setSession(s);
    storeSetSession(s);
  }

  function handleLeave() {
    localStorage.removeItem(`ktv_session_${roomId}`);
    setSession(null);
    storeSetSession(null);
  }

  const wsCommand = useCallback(
    (cmd: ClientCommand) => sendCommand(cmd),
    [sendCommand]
  );

  // Loading
  if (loadingSession) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center">
        <span className="text-gray-400">載入中…</span>
      </div>
    );
  }

  // Not joined yet
  if (!session) {
    return (
      <JoinForm
        roomId={roomId}
        hasPassword={hasPassword}
        onJoined={handleJoined}
      />
    );
  }

  const TAB_ITEMS: { id: Tab; label: string; icon: string }[] = [
    { id: "playing", label: "播放中", icon: "🎵" },
    { id: "queue", label: "隊列", icon: "📋" },
    { id: "search", label: "搜尋", icon: "🔍" },
    { id: "room", label: "房間", icon: "👥" },
  ];

  return (
    <div className="min-h-screen bg-gray-950 flex flex-col">
      {/* Header */}
      <header className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
        <span className="text-white font-semibold">{room?.name ?? roomId}</span>
        <span className="text-gray-400 text-sm">{session.guest.nickname}</span>
      </header>

      {/* Content */}
      <main className="flex-1 overflow-y-auto pb-16">
        {tab === "playing" && (
          <NowPlaying
            currentSong={currentSong}
            currentQueueItem={currentQueueItem}
            playback={playback}
            processing={processing}
            sendCommand={wsCommand}
          />
        )}
        {tab === "queue" && (
          <QueueList
            queue={queue}
            currentQueueItemId={currentQueueItem?.id ?? null}
            sendCommand={wsCommand}
          />
        )}
        {tab === "search" && (
          <SearchView
            roomId={roomId}
            onAdded={() => setTab("queue")}
          />
        )}
        {tab === "room" && room && (
          <RoomTab
            room={room}
            session={session}
            guests={guests}
            onLeave={handleLeave}
          />
        )}
      </main>

      {/* Bottom tab bar */}
      <nav className="fixed bottom-0 left-0 right-0 bg-gray-900 border-t border-gray-800 flex">
        {TAB_ITEMS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex-1 flex flex-col items-center py-2 gap-0.5 transition-colors ${
              tab === t.id
                ? "text-purple-400"
                : "text-gray-500 hover:text-gray-300"
            }`}
          >
            <span className="text-lg">{t.icon}</span>
            <span className="text-xs">{t.label}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}
