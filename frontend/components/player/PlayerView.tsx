"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import QRCode from "react-qr-code";
import { useKtvStore } from "@/lib/stores";
import { useWebSocket } from "@/lib/ws";
import { getQueue, getRoom } from "@/lib/api";
import type { ServerEvent } from "@/lib/types";
import SubtitleLayer from "./SubtitleLayer";

interface Props {
  roomId: string;
}

const STAGE_LABELS: Record<string, string> = {
  downloading: "下載中",
  separating: "分離人聲",
  fetching_lyrics: "抓取歌詞",
  aligning: "對齊字幕",
  packaging: "封裝 HLS",
};

function useClock() {
  const [time, setTime] = useState<string>("");
  useEffect(() => {
    const fmt = () =>
      new Date().toLocaleTimeString("zh-TW", {
        hour: "2-digit",
        minute: "2-digit",
      });
    setTime(fmt());
    const id = setInterval(() => setTime(fmt()), 10_000);
    return () => clearInterval(id);
  }, []);
  return time;
}

export default function PlayerView({ roomId }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const hlsRef = useRef<import("hls.js").default | null>(null);
  const [remoteUrl, setRemoteUrl] = useState<string>("");
  const clock = useClock();

  const {
    room,
    currentSong,
    currentQueueItem,
    queue,
    guests,
    playback,
    processing,
    setRoom,
    setQueue,
    setCurrentSong,
    setPlayback,
    setGuests,
    setProcessing,
    updatePosition,
  } = useKtvStore();

  // Build the Remote URL (client-only — window is not available on server)
  useEffect(() => {
    setRemoteUrl(window.location.origin + `/r/${roomId}/remote`);
  }, [roomId]);

  const handleEvent = useCallback(
    (event: ServerEvent) => {
      if (event.type === "queue.updated") setQueue(event.queue);
      else if (event.type === "song.started")
        setCurrentSong(event.song, event.queueItem);
      else if (event.type === "song.progress") updatePosition(event.positionSec);
      else if (event.type === "song.ended") setCurrentSong(null, null);
      else if (event.type === "playback.state") setPlayback(event.state);
      else if (event.type === "song.processing")
        setProcessing({ stage: event.stage, percent: event.percent });
      else if (event.type === "guests.updated") setGuests(event.guests);
    },
    [setQueue, setCurrentSong, updatePosition, setPlayback, setProcessing, setGuests]
  );

  const { sendCommand } = useWebSocket(roomId, null, "player", handleEvent);
  void sendCommand;

  // Initial data load
  useEffect(() => {
    getQueue(roomId).then(setQueue).catch(() => {});
    getRoom(roomId).then(setRoom).catch(() => {});
  }, [roomId, setQueue, setRoom]);

  // HLS setup when song changes
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    if (!currentSong || currentSong.status !== "ready") {
      hlsRef.current?.destroy();
      hlsRef.current = null;
      video.src = "";
      return;
    }

    const src = `/songs/${currentSong.id}/stream.m3u8`;

    import("hls.js").then(({ default: Hls }) => {
      hlsRef.current?.destroy();

      if (Hls.isSupported()) {
        const hls = new Hls({ enableWorker: false });
        hlsRef.current = hls;
        hls.loadSource(src);
        hls.attachMedia(video);
        hls.on(Hls.Events.MANIFEST_PARSED, () => {
          video.play().catch(() => {});
        });
      } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
        video.src = src;
        video.play().catch(() => {});
      }
    });

    return () => {
      hlsRef.current?.destroy();
      hlsRef.current = null;
    };
  }, [currentSong]);

  // Sync play/pause
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    if (playback.is_playing && video.paused) video.play().catch(() => {});
    if (!playback.is_playing && !video.paused) video.pause();
  }, [playback.is_playing]);

  const nextItem = queue.find(
    (q) => q.id !== currentQueueItem?.id && q.status !== "playing"
  );

  // ── Standby screen ──────────────────────────────────────────────────────────
  if (!currentSong) {
    return (
      <div className="relative min-h-screen bg-gray-950 flex flex-col overflow-hidden">
        {/* Ambient gradient */}
        <div className="absolute inset-0 bg-gradient-to-br from-purple-950/60 via-gray-950 to-indigo-950/40 pointer-events-none" />

        {/* Top bar: room name + clock */}
        <header className="relative z-10 flex items-center justify-between px-8 py-5">
          <div className="flex items-center gap-3">
            <span className="text-purple-400 text-2xl">🎤</span>
            <span className="text-white font-semibold text-xl tracking-wide">
              {room?.name ?? "Home KTV"}
            </span>
          </div>
          <div className="flex items-center gap-6">
            {guests.length > 0 && (
              <span className="text-gray-400 text-sm">
                {guests.length} 人在線
              </span>
            )}
            <span className="text-gray-300 text-lg font-mono tabular-nums">
              {clock}
            </span>
          </div>
        </header>

        {/* Main content */}
        <div className="relative z-10 flex flex-1 flex-col items-center justify-center gap-10 px-8 pb-16">
          {/* QR code card */}
          <div className="flex flex-col items-center gap-4">
            <div className="bg-white rounded-3xl p-5 shadow-2xl shadow-purple-900/40">
              {remoteUrl ? (
                <QRCode value={remoteUrl} size={180} bgColor="#ffffff" fgColor="#111827" />
              ) : (
                <div className="w-44 h-44 bg-gray-100 animate-pulse rounded-xl" />
              )}
            </div>
            <p className="text-gray-400 text-sm">掃 QR Code 用手機點歌</p>
            {remoteUrl && (
              <p className="text-gray-600 text-xs font-mono">
                {remoteUrl}
              </p>
            )}
          </div>

          <p className="text-gray-500 text-lg">等待點歌中…</p>

          {/* Queue preview */}
          {queue.length > 0 && (
            <div className="bg-gray-800/70 backdrop-blur-sm border border-gray-700/50 rounded-2xl px-6 py-4 w-full max-w-sm">
              <p className="text-gray-400 text-xs uppercase tracking-wider mb-3">
                隊列 ({queue.length})
              </p>
              {queue.slice(0, 4).map((item) => (
                <div key={item.id} className="flex items-center gap-3 py-1.5">
                  <div className="w-1.5 h-1.5 rounded-full bg-purple-400 flex-shrink-0" />
                  <span className="text-white text-sm truncate flex-1">
                    {item.song?.title ?? item.song_id}
                  </span>
                  {item.status !== "ready" && item.status !== "pending" && (
                    <span className="text-yellow-400 text-xs flex-shrink-0">
                      {STAGE_LABELS[item.status] ?? item.status}
                    </span>
                  )}
                </div>
              ))}
              {queue.length > 4 && (
                <p className="text-gray-500 text-xs mt-2 text-right">
                  + {queue.length - 4} 首
                </p>
              )}
            </div>
          )}
        </div>

        {/* Processing overlay (bottom) */}
        {processing && (
          <div className="absolute bottom-6 left-1/2 -translate-x-1/2 z-20 bg-gray-800/95 backdrop-blur border border-gray-700 rounded-2xl px-8 py-4 text-center min-w-56">
            <p className="text-white font-medium text-sm">
              {STAGE_LABELS[processing.stage] ?? processing.stage}
            </p>
            <div className="w-full h-1.5 bg-gray-700 rounded-full mt-2 overflow-hidden">
              <div
                className="h-full bg-purple-500 rounded-full transition-all duration-300"
                style={{ width: `${processing.percent}%` }}
              />
            </div>
            <p className="text-gray-400 text-xs mt-1">{processing.percent}%</p>
          </div>
        )}
      </div>
    );
  }

  // ── Playing screen ──────────────────────────────────────────────────────────
  return (
    <div className="relative w-screen h-screen bg-black overflow-hidden">
      {/* Video layer */}
      <video
        ref={videoRef}
        className="absolute inset-0 w-full h-full object-contain"
        playsInline
        muted
      />

      {/* Subtitle layer */}
      <SubtitleLayer song={currentSong} positionSec={playback.position_sec} />

      {/* Top-left: song info */}
      <div className="absolute top-4 left-4 bg-black/60 backdrop-blur-sm rounded-xl px-4 py-2.5 max-w-sm">
        <p className="text-white font-semibold text-sm truncate">
          {currentSong.title}
        </p>
        {currentSong.artist && (
          <p className="text-gray-300 text-xs mt-0.5">{currentSong.artist}</p>
        )}
        {currentQueueItem?.guest?.nickname && (
          <p className="text-purple-300 text-xs mt-0.5">
            ♪ {currentQueueItem.guest.nickname}
          </p>
        )}
      </div>

      {/* Bottom-right: next up */}
      {nextItem && (
        <div className="absolute bottom-6 right-6 bg-black/60 backdrop-blur-sm rounded-xl px-4 py-2.5 max-w-xs">
          <p className="text-gray-400 text-xs uppercase tracking-wider mb-0.5">
            下一首
          </p>
          <p className="text-white text-sm truncate">
            {nextItem.song?.title ?? nextItem.song_id}
          </p>
          {nextItem.guest?.nickname && (
            <p className="text-gray-400 text-xs mt-0.5">
              {nextItem.guest.nickname} 點的
            </p>
          )}
        </div>
      )}

      {/* Bottom-center: processing indicator */}
      {processing && (
        <div className="absolute bottom-6 left-1/2 -translate-x-1/2 bg-gray-800/90 backdrop-blur rounded-xl px-6 py-3 text-center">
          <p className="text-white text-sm">
            {STAGE_LABELS[processing.stage] ?? processing.stage} —{" "}
            {processing.percent}%
          </p>
        </div>
      )}
    </div>
  );
}
