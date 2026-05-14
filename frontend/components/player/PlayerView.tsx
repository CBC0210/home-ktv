"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import QRCode from "react-qr-code";
import { useKtvStore, THEME_STYLES } from "@/lib/stores";
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
  const vocalRef = useRef<HTMLAudioElement>(null);
  const instrRef = useRef<HTMLAudioElement>(null);
  const [remoteUrl, setRemoteUrl] = useState<string>("");
  const [audioBlocked, setAudioBlocked] = useState(false);
  const [subtitleRevision, setSubtitleRevision] = useState(0);
  const clock = useClock();

  const {
    room,
    currentSong,
    currentQueueItem,
    queue,
    guests,
    playback,
    processing,
    theme,
    setRoom,
    setQueue,
    setCurrentSong,
    setPlayback,
    setGuests,
    setProcessing,
    updatePosition,
    setIsPlaying,
  } = useKtvStore();

  const themeStyle = THEME_STYLES[theme];

  // Stable refs to avoid stale closures in event listeners
  const setIsPlayingRef = useRef(setIsPlaying);
  setIsPlayingRef.current = setIsPlaying;
  const playbackRef = useRef(playback);
  playbackRef.current = playback;

  useEffect(() => {
    setRemoteUrl(window.location.origin + `/r/${roomId}/remote`);
  }, [roomId]);

  // ── Audio volume helpers ────────────────────────────────────────────────────
  const syncVolumes = useCallback((main: number, vocal: number) => {
    const v = vocalRef.current;
    const i = instrRef.current;
    if (v) v.volume = Math.max(0, Math.min(1, main * vocal));
    if (i) i.volume = Math.max(0, Math.min(1, main));
  }, []);

  // Try to start the audio elements (may be blocked by autoplay policy)
  const tryPlayAudio = useCallback(async (atPosition?: number) => {
    const vocal = vocalRef.current;
    const instr = instrRef.current;
    if (!vocal || !instr) return;
    if (atPosition !== undefined) {
      vocal.currentTime = atPosition;
      instr.currentTime = atPosition;
    }
    const results = await Promise.allSettled([vocal.play(), instr.play()]);
    const blocked = results.some((r) => r.status === "rejected");
    setAudioBlocked(blocked);
  }, []);

  // ── WS event handler ────────────────────────────────────────────────────────
  const handleEvent = useCallback(
    (event: ServerEvent) => {
      const video = videoRef.current;

      switch (event.type) {
        case "queue.updated":
          setQueue(event.queue);
          break;
        case "song.started":
          setCurrentSong(event.song, event.queueItem);
          break;
        case "song.progress":
          updatePosition(event.positionSec);
          break;
        case "song.ended":
          setCurrentSong(null, null);
          setIsPlayingRef.current(false);
          break;
        case "playback.state":
          setPlayback(event.state);
          break;
        case "song.processing":
          setProcessing({ stage: event.stage, percent: event.percent });
          break;
        case "guests.updated":
          setGuests(event.guests);
          break;

        case "playback.play": {
          const pos = video?.currentTime ?? 0;
          video?.play().catch(() => {});
          void tryPlayAudio(pos);
          setIsPlayingRef.current(true);
          break;
        }
        case "playback.pause":
          video?.pause();
          vocalRef.current?.pause();
          instrRef.current?.pause();
          setIsPlayingRef.current(false);
          break;
        case "playback.seek":
          if (video) video.currentTime = event.positionSec;
          if (vocalRef.current) vocalRef.current.currentTime = event.positionSec;
          if (instrRef.current) instrRef.current.currentTime = event.positionSec;
          updatePosition(event.positionSec);
          break;
        case "playback.setVolume":
          setPlayback({
            ...playbackRef.current,
            main_volume: event.main ?? playbackRef.current.main_volume,
            vocal_volume: event.vocal ?? playbackRef.current.vocal_volume,
          });
          break;
        case "playback.replay":
          if (video) video.currentTime = 0;
          if (vocalRef.current) vocalRef.current.currentTime = 0;
          if (instrRef.current) instrRef.current.currentTime = 0;
          video?.play().catch(() => {});
          void tryPlayAudio(0);
          setIsPlayingRef.current(true);
          break;
        case "lyrics.updated":
          setSubtitleRevision((r) => r + 1);
          break;
      }
    },
    [setQueue, setCurrentSong, updatePosition, setPlayback, setProcessing, setGuests, tryPlayAudio]
  );

  const sendRef = useRef<((cmd: never) => void) | null>(null);
  const onWsConnected = useCallback(() => {
    sendRef.current?.({ type: "player.ready" } as never);
  }, []);

  const { sendCommand } = useWebSocket(roomId, null, "player", handleEvent, onWsConnected);
  sendRef.current = sendCommand as never;

  // ── Position broadcast timer ─────────────────────────────────────────────
  useEffect(() => {
    if (!playback.is_playing || !currentSong) return;
    const id = setInterval(() => {
      const pos = videoRef.current?.currentTime ?? 0;
      updatePosition(pos);
      sendRef.current?.({ type: "player.playing", positionSec: pos } as never);
    }, 1000);
    return () => clearInterval(id);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playback.is_playing, currentSong, updatePosition]);

  // ── Initial data load — also restore currently-playing song on page load ──
  useEffect(() => {
    getQueue(roomId).then((q) => {
      setQueue(q);
      const playing = q.find((item) => item.status === "playing");
      if (playing?.song) {
        setCurrentSong(playing.song, playing);
        setIsPlayingRef.current(true);
      }
    }).catch(() => {});
    getRoom(roomId).then(setRoom).catch(() => {});
  }, [roomId, setQueue, setRoom, setCurrentSong]);

  // ── Song change: load video + audio ──────────────────────────────────────
  useEffect(() => {
    const video = videoRef.current;
    const vocal = vocalRef.current;
    const instr = instrRef.current;
    if (!video) return;

    // Tear down previous
    video.src = "";
    if (vocal) { vocal.pause(); vocal.src = ""; }
    if (instr) { instr.pause(); instr.src = ""; }
    setAudioBlocked(false);
    setIsPlayingRef.current(false);

    if (!currentSong || currentSong.status !== "ready") return;

    const base = process.env.NEXT_PUBLIC_API_URL ?? "";
    video.src = `${base}/songs/${currentSong.id}/video.mp4`;
    if (vocal) vocal.src = `${base}/songs/${currentSong.id}/audio/no_vocals.wav`;
    if (instr) instr.src = `${base}/songs/${currentSong.id}/audio/vocals.wav`;

    syncVolumes(playbackRef.current.main_volume, playbackRef.current.vocal_volume);

    // Play once the video has enough data — avoids "play before ready" errors
    const handleCanPlay = () => {
      video.play().catch(() => {
        // Autoplay blocked — user must tap to unlock
        setAudioBlocked(true);
      });
    };

    video.addEventListener("canplay", handleCanPlay, { once: true });

    video.addEventListener("playing", () => {
      setIsPlayingRef.current(true);
      void tryPlayAudio(video.currentTime);
      sendRef.current?.({ type: "player.playing", positionSec: video.currentTime } as never);
    }, { once: true });

    video.addEventListener("ended", () => {
      sendRef.current?.({ type: "player.ended" } as never);
    }, { once: true });

    video.addEventListener("error", () => {
      sendRef.current?.({
        type: "player.error",
        error: `Video error: ${video.error?.message ?? "unknown"}`,
      } as never);
    }, { once: true });

    // Continuously re-sync audio to video to prevent drift (WAV has no timestamp sync)
    const handleTimeUpdate = () => {
      const vt = video.currentTime;
      if (vocal && Math.abs(vocal.currentTime - vt) > 0.15) vocal.currentTime = vt;
      if (instr && Math.abs(instr.currentTime - vt) > 0.15) instr.currentTime = vt;
    };
    video.addEventListener("timeupdate", handleTimeUpdate);

    video.load();

    return () => {
      video.removeEventListener("canplay", handleCanPlay);
      video.removeEventListener("timeupdate", handleTimeUpdate);
      video.src = "";
      if (vocal) { vocal.pause(); vocal.src = ""; }
      if (instr) { instr.pause(); instr.src = ""; }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentSong]);

  // ── Keep audio volumes in sync ───────────────────────────────────────────
  useEffect(() => {
    syncVolumes(playback.main_volume, playback.vocal_volume);
  }, [playback.main_volume, playback.vocal_volume, syncVolumes]);

  const nextItem = queue.find(
    (q) => q.id !== currentQueueItem?.id && q.status !== "playing"
  );

  // ── Standby screen ─────────────────────────────────────────────────────────
  if (!currentSong) {
    return (
      <div className={`relative min-h-screen flex flex-col overflow-hidden ${themeStyle.bg}`}>
        <div className="absolute inset-0 pointer-events-none overflow-hidden">
          <div className="absolute top-1/3 left-1/2 -translate-x-1/2 w-[600px] h-[600px] bg-violet-700/15 rounded-full blur-[120px] animate-pulse-glow" />
          <div className="absolute bottom-1/4 right-1/4 w-80 h-80 bg-purple-800/10 rounded-full blur-[80px] animate-pulse-glow" style={{ animationDelay: "2s" }} />
        </div>

        <header className="relative z-10 flex items-center justify-between px-10 py-6">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-violet-500 to-purple-700 flex items-center justify-center shadow-lg shadow-violet-900/50">
              <svg viewBox="0 0 24 24" fill="white" className="w-5 h-5">
                <path d="M12 3a9 9 0 110 18A9 9 0 0112 3zm0 4a5 5 0 100 10A5 5 0 0012 7zm0 2a3 3 0 110 6 3 3 0 010-6z"/>
                <circle cx="12" cy="12" r="1.5" fill="white"/>
              </svg>
            </div>
            <span className={`font-bold text-2xl tracking-tight ${themeStyle.headerText}`}>
              {room?.name ?? "Home KTV"}
            </span>
          </div>
          <div className="flex items-center gap-6">
            {guests.length > 0 && (
              <div className="flex items-center gap-2 bg-white/8 backdrop-blur rounded-full px-3 py-1.5">
                <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                <span className="text-white/70 text-sm">{guests.length} 人在線</span>
              </div>
            )}
            <span className="text-white/60 text-xl font-mono tabular-nums">{clock}</span>
          </div>
        </header>

        <div className="relative z-10 flex flex-1 items-center justify-center px-10 gap-20">
          <div className="flex flex-col items-center gap-5">
            <div className="bg-white rounded-3xl p-5 shadow-2xl shadow-black/60 ring-1 ring-white/20">
              {remoteUrl ? (
                <QRCode value={remoteUrl} size={200} bgColor="#ffffff" fgColor="#0f0f0f" />
              ) : (
                <div className="w-[200px] h-[200px] bg-gray-100 animate-pulse rounded-2xl" />
              )}
            </div>
            <div className="text-center">
              <p className="text-white/70 text-base font-medium">掃 QR Code 用手機點歌</p>
              {remoteUrl && (
                <p className="text-white/30 text-xs font-mono mt-1">{remoteUrl}</p>
              )}
            </div>
          </div>

          <div className="flex flex-col gap-4 min-w-72 max-w-sm">
            {queue.length === 0 ? (
              <div className="text-center py-12">
                <p className="text-white/30 text-2xl font-light">等待點歌中…</p>
                <p className="text-white/20 text-sm mt-2">掃碼後搜尋喜歡的歌曲</p>
              </div>
            ) : (
              <>
                <p className="text-white/40 text-xs uppercase tracking-widest font-medium">
                  待播隊列 · {queue.length} 首
                </p>
                <div className="flex flex-col gap-1">
                  {queue.slice(0, 5).map((item, i) => (
                    <div
                      key={item.id}
                      className="flex items-center gap-3 py-2.5 px-4 rounded-2xl bg-white/5 border border-white/6 backdrop-blur"
                    >
                      <span className="text-white/20 text-xs w-4 font-mono flex-shrink-0">{i + 1}</span>
                      <span className="text-white text-sm truncate flex-1 font-medium">
                        {item.song?.title ?? item.song_id}
                      </span>
                      {item.status === "playing" && (
                        <span className="text-violet-400 text-xs flex-shrink-0">▶ 播放中</span>
                      )}
                      {item.status === "ready" && (
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 flex-shrink-0" />
                      )}
                      {!["playing", "ready", "pending"].includes(item.status) && (
                        <span className="text-amber-400 text-xs flex-shrink-0">
                          {STAGE_LABELS[item.status] ?? "處理中"}
                        </span>
                      )}
                    </div>
                  ))}
                  {queue.length > 5 && (
                    <p className="text-white/25 text-xs text-center pt-1">
                      還有 {queue.length - 5} 首…
                    </p>
                  )}
                </div>
              </>
            )}
          </div>
        </div>

        {processing && (
          <div className="absolute bottom-8 left-1/2 -translate-x-1/2 z-20 bg-black/80 backdrop-blur-xl border border-white/10 rounded-2xl px-8 py-4 text-center min-w-64">
            <p className="text-white font-medium text-sm">
              {STAGE_LABELS[processing.stage] ?? processing.stage}
            </p>
            <div className="w-full h-1 bg-white/10 rounded-full mt-2.5 overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-violet-500 to-purple-400 rounded-full transition-all duration-300"
                style={{ width: `${processing.percent}%` }}
              />
            </div>
            <p className="text-white/40 text-xs mt-1.5">{processing.percent}%</p>
          </div>
        )}

        {/* Hidden audio elements — always mounted so refs are stable */}
        <audio ref={vocalRef} preload="auto" className="hidden" />
        <audio ref={instrRef} preload="auto" className="hidden" />
      </div>
    );
  }

  // ── Playing screen ─────────────────────────────────────────────────────────
  return (
    <div className="relative w-screen h-screen bg-black overflow-hidden">
      {/* Hidden audio elements */}
      <audio ref={vocalRef} preload="auto" className="hidden" />
      <audio ref={instrRef} preload="auto" className="hidden" />

      <video
        ref={videoRef}
        className="absolute inset-0 w-full h-full object-contain"
        playsInline
        muted
      />

      <SubtitleLayer key={subtitleRevision} song={currentSong} videoRef={videoRef} />

      {/* Song info */}
      <div className="absolute top-4 left-4 bg-black/60 backdrop-blur-sm rounded-xl px-4 py-2.5 max-w-sm">
        <p className="text-white font-semibold text-sm truncate">{currentSong.title}</p>
        {currentSong.artist && (
          <p className="text-gray-300 text-xs mt-0.5">{currentSong.artist}</p>
        )}
        {currentQueueItem?.guest?.nickname && (
          <p className="text-purple-300 text-xs mt-0.5">
            ♪ {currentQueueItem.guest.nickname}
          </p>
        )}
      </div>

      {/* Next song */}
      {nextItem && (
        <div className="absolute bottom-6 right-6 bg-black/60 backdrop-blur-sm rounded-xl px-4 py-2.5 max-w-xs">
          <p className="text-gray-400 text-xs uppercase tracking-wider mb-0.5">下一首</p>
          <p className="text-white text-sm truncate">
            {nextItem.song?.title ?? nextItem.song_id}
          </p>
          {nextItem.guest?.nickname && (
            <p className="text-gray-400 text-xs mt-0.5">{nextItem.guest.nickname} 點的</p>
          )}
        </div>
      )}

      {/* Processing overlay */}
      {processing && (
        <div className="absolute bottom-6 left-1/2 -translate-x-1/2 bg-gray-800/90 backdrop-blur rounded-xl px-6 py-3 text-center">
          <p className="text-white text-sm">
            {STAGE_LABELS[processing.stage] ?? processing.stage} — {processing.percent}%
          </p>
        </div>
      )}

      {/* Audio unlock overlay — shown when autoplay is blocked */}
      {audioBlocked && (
        <div
          className="absolute inset-0 z-50 flex items-center justify-center cursor-pointer"
          onClick={() => void tryPlayAudio(videoRef.current?.currentTime ?? 0)}
        >
          <div className="bg-black/70 backdrop-blur-md rounded-3xl px-10 py-8 text-center border border-white/10">
            <div className="text-5xl mb-3">🔊</div>
            <p className="text-white text-xl font-semibold">點擊啟用聲音</p>
            <p className="text-white/50 text-sm mt-1">瀏覽器需要互動才能播放音訊</p>
          </div>
        </div>
      )}
    </div>
  );
}
