"use client";

import { useEffect, useState, useCallback } from "react";
import { useKtvStore } from "@/lib/stores";
import { useWebSocket } from "@/lib/ws";
import { getRoom, getQueue, getOnlineGuests, setGuestToken, verifyRoomAdmin } from "@/lib/api";
import type { GuestSession, ServerEvent, ClientCommand } from "@/lib/types";
import JoinForm from "./JoinForm";
import InstallPrompt from "./InstallPrompt";
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
  const [systemError, setSystemError] = useState<string | null>(null);
  const [reactionToast, setReactionToast] = useState<{ emoji: string; from: string } | null>(null);
  const [adminMode, setAdminMode] = useState(false);
  const [adminModalOpen, setAdminModalOpen] = useState(false);
  const [adminPassword, setAdminPassword] = useState("");
  const [adminError, setAdminError] = useState<string | null>(null);
  const [adminVerifying, setAdminVerifying] = useState(false);

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
    // Restore admin mode flag (stored separately so it survives refresh)
    if (localStorage.getItem(`ktv_admin_${roomId}`) === "1") {
      setAdminMode(true);
    }
    setLoadingSession(false);
  }, [roomId]);

  async function handleAdminVerify() {
    if (!adminPassword.trim()) return;
    setAdminVerifying(true);
    setAdminError(null);
    try {
      await verifyRoomAdmin(roomId, adminPassword);
      setAdminMode(true);
      localStorage.setItem(`ktv_admin_${roomId}`, "1");
      setAdminModalOpen(false);
      setAdminPassword("");
    } catch {
      setAdminError("密碼錯誤");
    } finally {
      setAdminVerifying(false);
    }
  }

  function exitAdminMode() {
    setAdminMode(false);
    localStorage.removeItem(`ktv_admin_${roomId}`);
  }

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
        setProcessing(null);  // pipeline finished — clear overlay
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
      else if (event.type === "system.error") {
        setSystemError(event.message);
        setTimeout(() => setSystemError(null), 5000);
      }
      else if (event.type === "reaction") {
        setReactionToast({ emoji: event.emoji, from: event.from });
        setTimeout(() => setReactionToast(null), 2500);
      }
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
          {adminMode && (
            <span className="ml-2 px-2 py-0.5 rounded-full bg-amber-500/20 border border-amber-500/40 text-amber-300 text-[10px] font-bold uppercase tracking-wider">
              管理員
            </span>
          )}
        </div>
        <button
          onClick={() => {
            if (adminMode) exitAdminMode();
            else setAdminModalOpen(true);
          }}
          className={`w-9 h-9 rounded-full flex items-center justify-center text-white text-xs font-bold shadow-sm transition-all ${
            adminMode ? "ring-2 ring-amber-400 ring-offset-2 ring-offset-[#0a0a0a]" : "active:scale-90"
          }`}
          style={{ backgroundColor: session.guest.avatar_color ?? "#7c3aed" }}
          title={adminMode ? "點擊退出管理員模式" : "點擊進入管理員模式"}
        >
          {initials}
        </button>
      </header>

      {/* Admin password modal */}
      {adminModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/85 backdrop-blur-md flex items-center justify-center p-6">
          <div className="bg-[#1a1a1a] border border-white/10 rounded-3xl p-6 w-full max-w-sm shadow-2xl">
            <div className="text-center mb-4">
              <div className="text-3xl mb-2">🔐</div>
              <h2 className="text-white font-bold text-lg">進入管理員模式</h2>
              <p className="text-white/40 text-xs mt-1">解鎖隊列管理、刪除歌曲等進階操作</p>
            </div>
            <input
              type="password"
              autoFocus
              value={adminPassword}
              onChange={(e) => { setAdminPassword(e.target.value); setAdminError(null); }}
              onKeyDown={(e) => { if (e.key === "Enter") void handleAdminVerify(); }}
              placeholder="管理員密碼"
              className="w-full bg-white/8 border border-white/10 rounded-2xl px-4 py-3 text-white placeholder-white/30 focus:outline-none focus:border-amber-500/50 focus:bg-white/10 transition-all text-sm"
            />
            {adminError && (
              <p className="text-red-400 text-xs mt-2 text-center">{adminError}</p>
            )}
            <div className="flex gap-2 mt-4">
              <button
                onClick={() => { setAdminModalOpen(false); setAdminPassword(""); setAdminError(null); }}
                className="flex-1 py-3 rounded-2xl bg-white/8 text-white/70 text-sm hover:bg-white/12 transition-colors"
              >
                取消
              </button>
              <button
                onClick={handleAdminVerify}
                disabled={adminVerifying || !adminPassword.trim()}
                className="flex-1 py-3 rounded-2xl bg-amber-600 text-white text-sm font-medium hover:bg-amber-500 transition-colors disabled:opacity-40"
              >
                {adminVerifying ? "驗證中…" : "進入"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Content */}
      <main className="flex-1 overflow-y-auto pb-20">
        {tab === "playing" && (
          <NowPlaying
            currentSong={currentSong}
            currentQueueItem={currentQueueItem}
            playback={playback}
            processing={processing}
            sendCommand={wsCommand}
            adminMode={adminMode}
          />
        )}
        {tab === "queue" && (
          <QueueList
            queue={queue}
            currentQueueItemId={currentQueueItem?.id ?? null}
            sendCommand={wsCommand}
            adminMode={adminMode}
          />
        )}
        {tab === "search" && (
          <SearchView roomId={roomId} token={session.token} />
        )}
        {tab === "room" && room && (
          <RoomTab
            room={room}
            session={session}
            guests={guests}
            onLeave={handleLeave}
            adminMode={adminMode}
            onKick={(gid) => wsCommand({ type: "guest.kick", guestId: gid })}
          />
        )}
      </main>

      {/* System error toast */}
      {systemError && (
        <div className="fixed top-16 left-1/2 -translate-x-1/2 z-40 bg-red-900/90 backdrop-blur border border-red-500/40 rounded-xl px-4 py-2.5 max-w-xs shadow-xl">
          <p className="text-white text-xs font-medium">⚠ {systemError}</p>
        </div>
      )}

      {/* Reaction toast */}
      {reactionToast && (
        <div className="fixed top-16 left-1/2 -translate-x-1/2 z-40 bg-violet-900/90 backdrop-blur border border-violet-500/40 rounded-full px-4 py-2 shadow-xl">
          <p className="text-white text-xs">
            {reactionToast.emoji} {reactionToast.from}
          </p>
        </div>
      )}

      <InstallPrompt />

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
