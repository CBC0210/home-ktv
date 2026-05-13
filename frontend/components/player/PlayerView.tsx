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

/**
 * DualAudio manages two AudioContext sources (vocals + instrumental) mixed
 * through individual GainNodes. Designed for use with a muted <video> element
 * that provides the visual track.
 */
class DualAudioMixer {
  private ctx: AudioContext;
  private vocalEl: HTMLAudioElement;
  private instrEl: HTMLAudioElement;
  private vocalGain: GainNode;
  private instrGain: GainNode;
  private masterGain: GainNode;
  private started = false;

  constructor() {
    this.ctx = new AudioContext();
    this.vocalEl = new Audio();
    this.instrEl = new Audio();
    this.vocalEl.crossOrigin = "anonymous";
    this.instrEl.crossOrigin = "anonymous";

    const vocalSrc = this.ctx.createMediaElementSource(this.vocalEl);
    const instrSrc = this.ctx.createMediaElementSource(this.instrEl);

    this.vocalGain = this.ctx.createGain();
    this.instrGain = this.ctx.createGain();
    this.masterGain = this.ctx.createGain();

    vocalSrc.connect(this.vocalGain);
    instrSrc.connect(this.instrGain);
    this.vocalGain.connect(this.masterGain);
    this.instrGain.connect(this.masterGain);
    this.masterGain.connect(this.ctx.destination);
  }

  load(vocalUrl: string, instrUrl: string) {
    this.vocalEl.src = vocalUrl;
    this.instrEl.src = instrUrl;
    this.started = false;
  }

  async play(atPosition?: number) {
    if (this.ctx.state === "suspended") {
      await this.ctx.resume();
    }
    if (atPosition !== undefined) {
      this.vocalEl.currentTime = atPosition;
      this.instrEl.currentTime = atPosition;
    }
    await Promise.allSettled([this.vocalEl.play(), this.instrEl.play()]);
    this.started = true;
  }

  pause() {
    this.vocalEl.pause();
    this.instrEl.pause();
  }

  seek(positionSec: number) {
    this.vocalEl.currentTime = positionSec;
    this.instrEl.currentTime = positionSec;
  }

  setVolumes(main: number, vocal: number) {
    this.masterGain.gain.value = main;
    // vocal_volume=0 → only instrumental; vocal_volume=1 → full vocals
    this.vocalGain.gain.value = vocal;
    this.instrGain.gain.value = 1; // instrumental always at full
  }

  get currentTime() {
    return this.instrEl.currentTime;
  }

  get isPlaying() {
    return !this.instrEl.paused && this.started;
  }

  destroy() {
    this.vocalEl.pause();
    this.instrEl.pause();
    this.vocalEl.src = "";
    this.instrEl.src = "";
    this.ctx.close().catch(() => {});
  }
}

export default function PlayerView({ roomId }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const mixerRef = useRef<DualAudioMixer | null>(null);
  const positionTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [remoteUrl, setRemoteUrl] = useState<string>("");
  // Increment to force SubtitleLayer remount when lyrics are replaced
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
  } = useKtvStore();

  const themeStyle = THEME_STYLES[theme];

  useEffect(() => {
    setRemoteUrl(window.location.origin + `/r/${roomId}/remote`);
  }, [roomId]);

  const handleEvent = useCallback(
    (event: ServerEvent) => {
      const video = videoRef.current;
      const mixer = mixerRef.current;

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

        // Playback control commands forwarded from Remote
        case "playback.play":
          video?.play().catch(() => {});
          mixer?.play().catch(() => {});
          setPlayback({ ...playback, is_playing: true });
          break;
        case "playback.pause":
          video?.pause();
          mixer?.pause();
          setPlayback({ ...playback, is_playing: false });
          break;
        case "playback.seek":
          if (video) video.currentTime = event.positionSec;
          mixer?.seek(event.positionSec);
          updatePosition(event.positionSec);
          break;
        case "playback.setVolume":
          setPlayback({
            ...playback,
            main_volume: event.main ?? playback.main_volume,
            vocal_volume: event.vocal ?? playback.vocal_volume,
          });
          break;
        case "playback.skip":
        case "playback.replay":
          // Queue management not yet implemented in player; server handles via queue API
          break;
        case "lyrics.updated":
          // Reload SubtitleLayer so it fetches the updated .ass file
          setSubtitleRevision((r) => r + 1);
          break;
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [setQueue, setCurrentSong, updatePosition, setPlayback, setProcessing, setGuests]
  );

  // sendRef allows the onConnected callback to call sendCommand without circular deps
  const sendRef = useRef<((cmd: never) => void) | null>(null);
  const onWsConnected = useCallback(() => {
    sendRef.current?.({ type: "player.ready" } as never);
  }, []);

  const { sendCommand } = useWebSocket(roomId, null, "player", handleEvent, onWsConnected);
  sendRef.current = sendCommand as never;

  // Broadcast position every second when playing
  useEffect(() => {
    if (positionTimerRef.current) clearInterval(positionTimerRef.current);
    if (playback.is_playing && currentSong) {
      positionTimerRef.current = setInterval(() => {
        const pos = videoRef.current?.currentTime ?? 0;
        updatePosition(pos);
        sendCommand({ type: "player.playing", positionSec: pos } as never);
      }, 1000);
    }
    return () => {
      if (positionTimerRef.current) clearInterval(positionTimerRef.current);
    };
  }, [playback.is_playing, currentSong, sendCommand, updatePosition]);

  // Initial data load
  useEffect(() => {
    getQueue(roomId).then(setQueue).catch(() => {});
    getRoom(roomId).then(setRoom).catch(() => {});
  }, [roomId, setQueue, setRoom]);

  // HLS + dual audio setup when song changes
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    // Tear down previous
    video.src = "";
    mixerRef.current?.destroy();
    mixerRef.current = null;

    if (!currentSong || currentSong.status !== "ready") {
      video.src = "";
      return;
    }

    const base = process.env.NEXT_PUBLIC_API_URL ?? "";
    const videoSrc = `${base}/songs/${currentSong.id}/video.mp4`;
    const vocalSrc = `${base}/songs/${currentSong.id}/audio/vocals.wav`;
    const instrSrc = `${base}/songs/${currentSong.id}/audio/no_vocals.wav`;

    // Load video track directly (MP4 with range-request support for seeking)
    video.src = videoSrc;
    video.load();
    video.addEventListener("canplay", () => {
      video.play().catch(() => {});
      sendRef.current?.({ type: "player.playing", positionSec: 0 } as never);
    }, { once: true });
    video.addEventListener("error", () => {
      sendRef.current?.({
        type: "player.error",
        error: `Video load error: ${video.error?.message ?? "unknown"}`,
      } as never);
    }, { once: true });

    // Load dual audio tracks
    const mixer = new DualAudioMixer();
    mixerRef.current = mixer;
    mixer.load(vocalSrc, instrSrc);
    mixer.setVolumes(playback.main_volume, playback.vocal_volume);
    mixer.play(0).catch(() => {
      // Autoplay blocked — will start when user interacts
    });

    return () => {
      video.src = "";
      mixerRef.current?.destroy();
      mixerRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentSong]);

  // Keep volumes in sync whenever playback.main_volume / vocal_volume changes
  useEffect(() => {
    mixerRef.current?.setVolumes(playback.main_volume, playback.vocal_volume);
  }, [playback.main_volume, playback.vocal_volume]);

  // Sync play/pause state → video + mixer
  useEffect(() => {
    const video = videoRef.current;
    const mixer = mixerRef.current;
    if (!video) return;
    if (playback.is_playing) {
      video.play().catch(() => {});
      mixer?.play().catch(() => {});
    } else {
      video.pause();
      mixer?.pause();
    }
  }, [playback.is_playing]);

  const nextItem = queue.find(
    (q) => q.id !== currentQueueItem?.id && q.status !== "playing"
  );

  // ── Standby screen ──────────────────────────────────────────────────────────
  if (!currentSong) {
    return (
      <div className={`relative min-h-screen flex flex-col overflow-hidden ${themeStyle.bg}`}>
        {/* Ambient glow */}
        <div className="absolute inset-0 pointer-events-none overflow-hidden">
          <div className="absolute top-1/3 left-1/2 -translate-x-1/2 w-[600px] h-[600px] bg-violet-700/15 rounded-full blur-[120px] animate-pulse-glow" />
          <div className="absolute bottom-1/4 right-1/4 w-80 h-80 bg-purple-800/10 rounded-full blur-[80px] animate-pulse-glow" style={{ animationDelay: "2s" }} />
        </div>

        {/* Header */}
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

        {/* Main content */}
        <div className="relative z-10 flex flex-1 items-center justify-center px-10 gap-20">
          {/* QR code section */}
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

          {/* Queue or idle message */}
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
                      {item.status !== "ready" && item.status !== "pending" && (
                        <span className="text-amber-400 text-xs flex-shrink-0">
                          {STAGE_LABELS[item.status] ?? "處理中"}
                        </span>
                      )}
                      {item.status === "ready" && (
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 flex-shrink-0" />
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

        {/* Processing overlay */}
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
      </div>
    );
  }

  // ── Playing screen ──────────────────────────────────────────────────────────
  return (
    <div className="relative w-screen h-screen bg-black overflow-hidden">
      <video
        ref={videoRef}
        className="absolute inset-0 w-full h-full object-contain"
        playsInline
        muted
      />

      <SubtitleLayer key={subtitleRevision} song={currentSong} positionSec={playback.position_sec} />

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

      {processing && (
        <div className="absolute bottom-6 left-1/2 -translate-x-1/2 bg-gray-800/90 backdrop-blur rounded-xl px-6 py-3 text-center">
          <p className="text-white text-sm">
            {STAGE_LABELS[processing.stage] ?? processing.stage} — {processing.percent}%
          </p>
        </div>
      )}
    </div>
  );
}
