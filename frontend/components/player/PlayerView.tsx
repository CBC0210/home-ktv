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
  const hlsRef = useRef<import("hls.js").default | null>(null);
  const mixerRef = useRef<DualAudioMixer | null>(null);
  const positionTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
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
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [setQueue, setCurrentSong, updatePosition, setPlayback, setProcessing, setGuests]
  );

  const { sendCommand } = useWebSocket(roomId, null, "player", handleEvent);

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
    hlsRef.current?.destroy();
    hlsRef.current = null;
    mixerRef.current?.destroy();
    mixerRef.current = null;

    if (!currentSong || currentSong.status !== "ready") {
      video.src = "";
      return;
    }

    const base = process.env.NEXT_PUBLIC_API_URL ?? "";
    const hlsSrc = `${base}/songs/${currentSong.id}/stream.m3u8`;
    const vocalSrc = `${base}/songs/${currentSong.id}/audio/vocals.wav`;
    const instrSrc = `${base}/songs/${currentSong.id}/audio/no_vocals.wav`;

    // Load video track via hls.js (muted — audio handled by mixer)
    import("hls.js").then(({ default: Hls }) => {
      if (Hls.isSupported()) {
        const hls = new Hls({ enableWorker: false });
        hlsRef.current = hls;
        hls.loadSource(hlsSrc);
        hls.attachMedia(video);
        hls.on(Hls.Events.MANIFEST_PARSED, () => {
          video.play().catch(() => {});
        });
      } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
        video.src = hlsSrc;
        video.play().catch(() => {});
      }
    });

    // Load dual audio tracks
    const mixer = new DualAudioMixer();
    mixerRef.current = mixer;
    mixer.load(vocalSrc, instrSrc);
    mixer.setVolumes(playback.main_volume, playback.vocal_volume);
    mixer.play(0).catch(() => {
      // Autoplay blocked — will start when user interacts
    });

    return () => {
      hlsRef.current?.destroy();
      hlsRef.current = null;
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
      <div className="relative min-h-screen bg-gray-950 flex flex-col overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-purple-950/60 via-gray-950 to-indigo-950/40 pointer-events-none" />

        <header className="relative z-10 flex items-center justify-between px-8 py-5">
          <div className="flex items-center gap-3">
            <span className="text-purple-400 text-2xl">🎤</span>
            <span className="text-white font-semibold text-xl tracking-wide">
              {room?.name ?? "Home KTV"}
            </span>
          </div>
          <div className="flex items-center gap-6">
            {guests.length > 0 && (
              <span className="text-gray-400 text-sm">{guests.length} 人在線</span>
            )}
            <span className="text-gray-300 text-lg font-mono tabular-nums">
              {clock}
            </span>
          </div>
        </header>

        <div className="relative z-10 flex flex-1 flex-col items-center justify-center gap-10 px-8 pb-16">
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
              <p className="text-gray-600 text-xs font-mono">{remoteUrl}</p>
            )}
          </div>

          <p className="text-gray-500 text-lg">等待點歌中…</p>

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
      <video
        ref={videoRef}
        className="absolute inset-0 w-full h-full object-contain"
        playsInline
        muted
      />

      <SubtitleLayer song={currentSong} positionSec={playback.position_sec} />

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
