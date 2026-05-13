"use client";

import { useEffect, useState, useCallback } from "react";
import { useKtvStore } from "@/lib/stores";
import { useWebSocket } from "@/lib/ws";
import { getRoom, getQueue, getOnlineGuests, setGuestToken } from "@/lib/api";
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

const TAB_ITEMS: { id: Tab; label: string; icon: React.ReactNode }[] = [
  {
    id: "playing",
    label: "播放",
    icon: (
      <svg viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5">
        <path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z" />
      </svg>
    ),
  },
  {
    id: "queue",
    label: "隊列",
    icon: (
      <svg viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5">
        <path d="M3 13h2v-2H3v2zm0 4h2v-2H3v2zm0-8h2V7H3v2zm4 4h14v-2H7v2zm0 4h14v-2H7v2zM7 7v2h14V7H7z" />
      </svg>
    ),
  },
  {
    id: "search",
    label: "搜尋",
    icon: (
      <svg viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5">
        <path d="M15.5 14h-.79l-.28-.27C15.41 12.59 16 11.11 16 9.5 16 5.91 13.09 3 9.5 3S3 5.91 3 9.5 5.91 16 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z" />
      </svg>
    ),
  },
  {
    id: "room",
    label: "房間",
    icon: (
      <svg viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5">
        <path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z" />
      </svg>
    ),
  },
];

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
    setIsPlaying,
  } = useKtvStore();

  useEffect(() => {
    const stored = localStorage.getItem(`ktv_session_${roomId}`);
    if (stored) {
      try {
        const s = JSON.parse(stored) as GuestSession;
        setSession(s);
        setGuestToken(s.token);
      } catch {
        localStorage.removeItem(`ktv_session_${roomId}`);
      }
    }
    setLoadingSession(false);
  }, [roomId]);

  useEffect(() => {
    getRoom(roomId)
      .then((r) => { setRoom(r); setHasPassword(r.has_password); })
      .catch(() => {});
  }, [roomId, setRoom]);

  useEffect(() => {
    if (!session) return;
    getQueue(roomId).then((q) => {
      setQueue(q);
      // Detect currently-playing song from queue so "正在播放" works on late join
      const playing = q.find((item) => item.status === "playing");
      if (playing?.song) {
        setCurrentSong(playing.song, playing);
        setIsPlaying(true);
      }
    }).catch(() => {});
  }, [roomId, session, setQueue, setCurrentSong, setIsPlaying]);

  useEffect(() => {
    if (!session) return;
    getOnlineGuests(roomId).then(setGuests).catch(() => {});
  }, [roomId, session, setGuests]);

  useEffect(() => {
    storeSetSession(session);
    setGuestToken(session?.token ?? null);
  }, [session, storeSetSession]);

  const handleEvent = useCallback(
    (event: ServerEvent) => {
      if (event.type === "queue.updated") setQueue(event.queue);
      else if (event.type === "song.started") {
        setCurrentSong(event.song, event.queueItem);
        setIsPlaying(true);
      }
      else if (event.type === "song.progress") updatePosition(event.positionSec);
      else if (event.type === "song.ended") {
        setCurrentSong(null, null);
        setIsPlaying(false);
      }
      else if (event.type === "playback.state") setPlayback(event.state);
      else if (event.type === "playback.setVolume") {
        const patch: { main_volume?: number; vocal_volume?: number } = {};
        if (typeof event.main === "number") patch.main_volume = event.main;
        if (typeof event.vocal === "number") patch.vocal_volume = event.vocal;
        if (Object.keys(patch).length) setPlayback(patch);
      }
      else if (event.type === "guests.updated") setGuests(event.guests);
      else if (event.type === "song.processing")
        setProcessing({ stage: event.stage, percent: event.percent });
    },
    [setQueue, setCurrentSong, updatePosition, setPlayback, setGuests, setProcessing, setIsPlaying]
  );

  const { sendCommand } = useWebSocket(roomId, session?.token ?? null, "remote", handleEvent);

  function handleJoined(s: GuestSession) {
    setSession(s);
    storeSetSession(s);
  }

  function handleLeave() {
    localStorage.removeItem(`ktv_session_${roomId}`);
    setSession(null);
    storeSetSession(null);
  }

  const wsCommand = useCallback((cmd: ClientCommand) => sendCommand(cmd), [sendCommand]);

  if (loadingSession) {
    return (
      <div className="min-h-screen bg-[#0a0a0a] flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!session) {
    return <JoinForm roomId={roomId} hasPassword={hasPassword} onJoined={handleJoined} />;
  }

  const initials = session.guest.nickname.slice(0, 1).toUpperCase();
  const pendingCount = queue.filter(q => q.status !== "playing").length;

  return (
    <div className="min-h-screen bg-[#0a0a0a] flex flex-col">
      {/* Header */}
      <header className="flex items-center justify-between px-5 py-3 border-b border-white/6 bg-[#0a0a0a]/90 backdrop-blur-md sticky top-0 z-30">
        <div className="flex items-center gap-2">
          <div className="w-1.5 h-1.5 rounded-full bg-violet-400 animate-pulse" />
          <span className="text-white font-semibold text-sm">{room?.name ?? roomId}</span>
        </div>
        <div
          className="w-8 h-8 rounded-full flex items-center justify-center text-white text-xs font-bold shadow-sm"
          style={{ backgroundColor: session.guest.avatar_color ?? "#7c3aed" }}
        >
          {initials}
        </div>
      </header>

      {/* Content */}
      <main className="flex-1 overflow-y-auto pb-20">
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
          <SearchView roomId={roomId} token={session.token} />
        )}
        {tab === "room" && room && (
          <RoomTab room={room} session={session} guests={guests} onLeave={handleLeave} />
        )}
      </main>

      {/* Bottom tab bar */}
      <nav className="fixed bottom-0 left-0 right-0 bg-[#111]/90 backdrop-blur-xl border-t border-white/6 flex z-30 safe-bottom">
        {TAB_ITEMS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`relative flex-1 flex flex-col items-center py-3 gap-0.5 transition-colors ${
              tab === t.id ? "text-violet-400" : "text-white/35 hover:text-white/60"
            }`}
          >
            {t.id === "queue" && pendingCount > 0 && (
              <span className="absolute top-2 right-[calc(50%-12px)] min-w-[16px] h-4 px-1 bg-violet-500 rounded-full text-white text-[10px] font-bold flex items-center justify-center leading-none">
                {pendingCount > 9 ? "9+" : pendingCount}
              </span>
            )}
            {t.icon}
            <span className="text-[10px] font-medium">{t.label}</span>
            {tab === t.id && (
              <span className="absolute bottom-0 left-1/2 -translate-x-1/2 w-5 h-0.5 bg-violet-400 rounded-full" />
            )}
          </button>
        ))}
      </nav>
    </div>
  );
}
