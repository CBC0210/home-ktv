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
  pending: "排隊中",
  processing: "處理中",
  downloading: "下載中",
  separating: "分離人聲",
  fetching_lyrics: "抓取歌詞",
  aligning: "對齊字幕",
  packaging: "封裝中",
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

function formatTime(sec: number): string {
  if (!isFinite(sec) || sec < 0) return "0:00";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function PlayerView({ roomId }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const vocalRef = useRef<HTMLAudioElement>(null);
  const instrRef = useRef<HTMLAudioElement>(null);
  // True once the user has unlocked audio at least once this session.
  // Until then we keep songs PAUSED at 0 instead of playing muted, so the
  // first song doesn't silently run ahead and then jump on unlock.
  const audioUnlockedRef = useRef(false);
  // Server's last-known playback position — used to resume after a
  // mid-song page refresh instead of restarting from 0.
  const resumePosRef = useRef(0);
  // Web Audio graph (lazy)
  const audioCtxRef = useRef<AudioContext | null>(null);
  const vocalGainRef = useRef<GainNode | null>(null);
  const instrGainRef = useRef<GainNode | null>(null);

  const [remoteUrl, setRemoteUrl] = useState<string>("");
  const [audioBlocked, setAudioBlocked] = useState(false);
  const [subtitleRevision, setSubtitleRevision] = useState(0);
  const [subtitleOffsetMs, setSubtitleOffsetMs] = useState(0);
  const [reactions, setReactions] = useState<{ id: number; emoji: string; from: string; x: number }[]>([]);
  const [systemError, setSystemError] = useState<string | null>(null);
  const [videoPosition, setVideoPosition] = useState(0);
  const [processingExpanded, setProcessingExpanded] = useState(false);
  const [activity, setActivity] = useState<{ id: number; text: string; actor: string } | null>(null);
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

  // Stable refs to avoid stale closures
  const setIsPlayingRef = useRef(setIsPlaying);
  setIsPlayingRef.current = setIsPlaying;
  const playbackRef = useRef(playback);
  playbackRef.current = playback;
  // Reported-problem songs play the video's own embedded audio (perfect A/V
  // sync, no Demucs artefacts); the split vocal/instr graph is bypassed and
  // vocal-mix is inert. Ref so callbacks read the live value.
  const useOrigAudioRef = useRef(false);
  useOrigAudioRef.current = !!currentSong?.use_original_audio;

  useEffect(() => {
    setRemoteUrl(window.location.origin + `/r/${roomId}/remote`);
  }, [roomId]);

  // ── Web Audio init — MUST run inside a user-gesture stack ──────────────────
  // Chrome's autoplay policy: AudioContext starts suspended; resume() only
  // works synchronously inside a click handler. We init lazily on first
  // unlock-click and never on automatic media events.
  const ensureAudioGraph = useCallback(async (): Promise<boolean> => {
    const v = vocalRef.current;
    const i = instrRef.current;
    if (!v || !i) return false;
    if (audioCtxRef.current) {
      if (audioCtxRef.current.state === "suspended") {
        try { await audioCtxRef.current.resume(); } catch { /* ignore */ }
      }
      return audioCtxRef.current.state === "running";
    }
    try {
      type WindowWithWebkit = Window & typeof globalThis & { webkitAudioContext?: typeof AudioContext };
      const win = window as WindowWithWebkit;
      const Ctx = win.AudioContext ?? win.webkitAudioContext;
      if (!Ctx) return false;
      const ctx = new Ctx();
      const vGain = ctx.createGain();
      const iGain = ctx.createGain();
      const vSrc = ctx.createMediaElementSource(v);
      const iSrc = ctx.createMediaElementSource(i);
      vSrc.connect(vGain).connect(ctx.destination);
      iSrc.connect(iGain).connect(ctx.destination);
      audioCtxRef.current = ctx;
      vocalGainRef.current = vGain;
      instrGainRef.current = iGain;
      v.volume = 1;
      i.volume = 1;
      // Apply current desired gains
      const m = Math.max(0, Math.min(1, playbackRef.current.main_volume));
      const vv = Math.max(0, Math.min(2, playbackRef.current.vocal_volume));
      vGain.gain.value = m * vv;
      iGain.gain.value = m;
      // Detect when the browser auto-suspends the context (background tab,
      // power-saving, etc.) — re-show unlock overlay so user can re-enable.
      ctx.onstatechange = () => {
        console.info("[Player] AudioContext state →", ctx.state);
        if (ctx.state === "suspended") {
          setAudioBlocked(true);
        } else if (ctx.state === "running") {
          setAudioBlocked(false);
        }
      };
      // Resume (only succeeds in user-gesture call stack)
      try { await ctx.resume(); } catch { /* ignore */ }
      console.info("[Player] Web Audio graph initialized, state=" + ctx.state);
      return ctx.state === "running";
    } catch (err) {
      console.error("[Player] Web Audio init failed:", err);
      return false;
    }
  }, []);

  const syncVolumes = useCallback((main: number, vocal: number) => {
    const m = Math.max(0, Math.min(1, main));
    const vv = Math.max(0, Math.min(2, vocal));
    if (useOrigAudioRef.current) {
      // Original embedded audio: only main volume applies (no vocal track).
      const video = videoRef.current;
      if (video) { video.muted = false; video.volume = m; }
      return;
    }
    if (vocalGainRef.current && instrGainRef.current) {
      vocalGainRef.current.gain.value = m * vv;
      instrGainRef.current.gain.value = m;
      console.info(`[Player] gain set: vocal=${(m * vv).toFixed(2)} instr=${m.toFixed(2)}`);
    } else {
      const v = vocalRef.current;
      const i = instrRef.current;
      if (v) v.volume = Math.min(1, m * vv);
      if (i) i.volume = m;
      console.info(`[Player] volume fallback: vocal=${Math.min(1, m * vv).toFixed(2)} instr=${m.toFixed(2)} (no Web Audio)`);
    }
  }, []);

  // Auto-play attempt for HTMLAudioElement (without Web Audio). Will fail on
  // first run due to autoplay policy → triggers the unlock overlay.
  const tryPlayAudio = useCallback(async (atPosition?: number) => {
    if (useOrigAudioRef.current) return;  // audio rides the video element
    const vocal = vocalRef.current;
    const instr = instrRef.current;
    if (!vocal || !instr) return;
    if (atPosition !== undefined) {
      vocal.currentTime = atPosition;
      instr.currentTime = atPosition;
    }
    const results = await Promise.allSettled([vocal.play(), instr.play()]);
    const blocked = results.some((r) => r.status === "rejected");
    setAudioBlocked(blocked || !audioCtxRef.current);
  }, []);

  // Called when user clicks the unlock overlay (or anywhere when blocked).
  // This is synchronously inside a user gesture so Web Audio can be created
  // and resumed reliably.
  const unlockAudio = useCallback(async () => {
    if (useOrigAudioRef.current) {
      // No Web Audio graph — just start the video (carries its own audio).
      const video = videoRef.current;
      let pos = video?.currentTime ?? 0;
      if (resumePosRef.current > 1 && pos < 1) {
        pos = resumePosRef.current;
        if (video) video.currentTime = pos;
      }
      resumePosRef.current = 0;
      if (video) {
        video.muted = false;
        video.volume = Math.max(0, Math.min(1, playbackRef.current.main_volume));
        try { await video.play(); audioUnlockedRef.current = true; setAudioBlocked(false); }
        catch { setAudioBlocked(true); }
      }
      return;
    }
    const ok = await ensureAudioGraph();
    const video = videoRef.current;
    const vocal = vocalRef.current;
    const instr = instrRef.current;
    // Resume from the server's last position after a mid-song refresh,
    // else from wherever the video currently is (0 for a fresh song).
    let pos = video?.currentTime ?? 0;
    if (resumePosRef.current > 1 && pos < 1) {
      pos = resumePosRef.current;
      if (video) video.currentTime = pos;
    }
    resumePosRef.current = 0;  // consume — only resume once
    if (vocal) { vocal.currentTime = pos; try { await vocal.play(); } catch { /* ignore */ } }
    if (instr) { instr.currentTime = pos; try { await instr.play(); } catch { /* ignore */ } }
    if (video && video.paused) { try { await video.play(); } catch { /* ignore */ } }
    if (ok) audioUnlockedRef.current = true;
    setAudioBlocked(!ok);
  }, [ensureAudioGraph]);

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
          setSubtitleOffsetMs(event.song?.subtitle_offset_ms ?? 0);
          setProcessing(null);
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
          // Remember server's last position so a mid-song refresh can resume
          if (typeof event.state?.position_sec === "number" && event.state.position_sec > 1) {
            resumePosRef.current = event.state.position_sec;
          }
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
          console.info(`[Player] WS setVolume: main=${event.main} vocal=${event.vocal} (current main=${playbackRef.current.main_volume} vocal=${playbackRef.current.vocal_volume})`);
          setPlayback({
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
        case "lyrics.offset":
          setSubtitleOffsetMs(event.offsetMs);
          break;
        case "reaction": {
          const id = Date.now() + Math.random();
          const x = 10 + Math.random() * 80;
          setReactions((r) => [...r, { id, emoji: event.emoji, from: event.from, x }]);
          setTimeout(() => {
            setReactions((r) => r.filter((it) => it.id !== id));
          }, 4000);
          break;
        }
        case "system.error":
          setSystemError(event.message);
          setTimeout(() => setSystemError(null), 5000);
          break;
        case "activity": {
          const id = Date.now() + Math.random();
          setActivity({ id, text: event.text, actor: event.actor });
          setTimeout(() => {
            setActivity((cur) => (cur && cur.id === id ? null : cur));
          }, 3000);
          break;
        }
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
  // Only broadcasts when the video is genuinely playing — never while paused
  // (e.g. waiting for the unlock tap), so we don't spam position 0 and
  // corrupt every Remote's progress on a mid-song refresh.
  useEffect(() => {
    if (!playback.is_playing || !currentSong) return;
    const id = setInterval(() => {
      const v = videoRef.current;
      if (!v || v.paused || v.currentTime <= 0) return;
      const pos = v.currentTime;
      setVideoPosition(pos);
      updatePosition(pos);
      sendRef.current?.({ type: "player.playing", positionSec: pos } as never);
    }, 1000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playback.is_playing, currentSong, updatePosition]);

  // ── Initial data load — also restore currently-playing song on page load ──
  // Note: we do NOT force is_playing=true here. The song-change effect
  // pauses at 0 until the unlock tap; handlePlaying flips is_playing once
  // the video actually starts. This prevents the mid-refresh "stuck at 0".
  useEffect(() => {
    getQueue(roomId).then((q) => {
      setQueue(q);
      const playing = q.find((item) => item.status === "playing");
      if (playing?.song) {
        setCurrentSong(playing.song, playing);
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

    setAudioBlocked(false);
    setIsPlayingRef.current(false);

    // No song to play — unload media (using removeAttribute, not src="" which
    // fires a spurious MEDIA_ELEMENT_ERROR: Empty src attribute).
    if (!currentSong || currentSong.status !== "ready") {
      if (video.src) {
        video.pause();
        video.removeAttribute("src");
        video.load();
      }
      if (vocal?.src) { vocal.pause(); vocal.removeAttribute("src"); vocal.load(); }
      if (instr?.src) { instr.pause(); instr.removeAttribute("src"); instr.load(); }
      return;
    }

    // Direct swap to new song — no intermediate empty src
    const base = process.env.NEXT_PUBLIC_API_URL ?? "";
    const orig = !!currentSong.use_original_audio;
    video.src = `${base}/songs/${currentSong.id}/video.mp4`;
    if (orig) {
      // Play the video's embedded audio; bypass the split tracks entirely.
      video.muted = false;
      if (vocal?.src) { vocal.pause(); vocal.removeAttribute("src"); vocal.load(); }
      if (instr?.src) { instr.pause(); instr.removeAttribute("src"); instr.load(); }
    } else {
      video.muted = true;
      if (vocal) vocal.src = `${base}/songs/${currentSong.id}/audio/vocals.wav`;
      if (instr) instr.src = `${base}/songs/${currentSong.id}/audio/no_vocals.wav`;
    }

    syncVolumes(playbackRef.current.main_volume, playbackRef.current.vocal_volume);

    const handleCanPlay = () => {
      if (!audioUnlockedRef.current) {
        // Audio not unlocked yet — keep the song PAUSED at 0 and show the
        // tap-to-start overlay. unlockAudio() will start video+audio together.
        video.pause();
        video.currentTime = 0;
        setAudioBlocked(true);
        return;
      }
      video.play().catch(() => setAudioBlocked(true));
    };
    video.addEventListener("canplay", handleCanPlay, { once: true });

    const handlePlaying = () => {
      setIsPlayingRef.current(true);
      void tryPlayAudio(video.currentTime);
      sendRef.current?.({ type: "player.playing", positionSec: video.currentTime } as never);
    };
    video.addEventListener("playing", handlePlaying, { once: true });

    const handleEnded = () => {
      sendRef.current?.({ type: "player.ended" } as never);
    };
    video.addEventListener("ended", handleEnded);

    const handleVideoError = () => {
      // Empty src during transitions is harmless — code 4 with no src means no source
      if (!video.src || video.src.endsWith("/")) return;
      const code = video.error?.code;
      const msg = video.error?.message ?? "";
      if (code === 4 && msg.includes("Empty src")) return;
      console.error("[Player] video error:", video.error);
      sendRef.current?.({
        type: "player.error",
        error: `Video error: ${msg || "unknown"}`,
      } as never);
    };
    video.addEventListener("error", handleVideoError);

    // Keep audio locked to the video clock WITHOUT constant hard seeks.
    // Hard-seeking every timeupdate (~4×/s) makes the vocal stutter and
    // sound sped-up/slowed-down. Instead: tiny drift → nudge playbackRate
    // so it converges smoothly; only a big gap (real desync / user seek)
    // gets a single hard seek.
    const softSync = (el: HTMLAudioElement | null, vt: number) => {
      if (!el || el.readyState < 2 || el.paused) return;
      const drift = el.currentTime - vt;        // +ve = audio ahead
      const ad = Math.abs(drift);
      if (ad > 0.45) {
        el.currentTime = vt;                    // real desync — snap once
        el.playbackRate = 1;
      } else if (ad > 0.04) {
        // Converge over ~1-2s; clamp so pitch shift is inaudible
        el.playbackRate = Math.max(0.97, Math.min(1.03, 1 - drift * 0.5));
      } else {
        el.playbackRate = 1;                    // in sync
      }
    };
    const handleTimeUpdate = () => {
      const vt = video.currentTime;
      setVideoPosition(vt);
      softSync(vocal, vt);
      softSync(instr, vt);
    };
    video.addEventListener("timeupdate", handleTimeUpdate);

    return () => {
      video.removeEventListener("canplay", handleCanPlay);
      video.removeEventListener("playing", handlePlaying);
      video.removeEventListener("ended", handleEnded);
      video.removeEventListener("error", handleVideoError);
      video.removeEventListener("timeupdate", handleTimeUpdate);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentSong?.id, currentSong?.status]);

  // ── Keep audio volumes in sync ───────────────────────────────────────────
  useEffect(() => {
    syncVolumes(playback.main_volume, playback.vocal_volume);
  }, [playback.main_volume, playback.vocal_volume, syncVolumes]);

  const nextItem = queue.find((q) => q.id !== currentQueueItem?.id && q.status !== "playing");
  const duration = currentSong?.duration_sec ?? 0;
  const progressPct = duration > 0 ? Math.min(100, (videoPosition / duration) * 100) : 0;

  // ── Preload next ready song's media during current playback ───────────────
  // Pulls video + opus audio into the browser HTTP cache so song-to-song
  // switching is instant instead of streaming-from-cold over the Tunnel.
  const preloadedRef = useRef<string | null>(null);
  useEffect(() => {
    if (!currentSong) return;
    const next = queue.find(
      (q) => q.status === "ready" && q.song && q.id !== currentQueueItem?.id
    );
    const nextSong = next?.song;
    if (!nextSong || preloadedRef.current === nextSong.id) return;
    preloadedRef.current = nextSong.id;
    const base = process.env.NEXT_PUBLIC_API_URL ?? "";
    const urls = [
      `${base}/songs/${nextSong.id}/video.mp4`,
      `${base}/songs/${nextSong.id}/audio/vocals.wav`,
      `${base}/songs/${nextSong.id}/audio/no_vocals.wav`,
    ];
    const controllers: AbortController[] = [];
    urls.forEach((u) => {
      const ctrl = new AbortController();
      controllers.push(ctrl);
      // Low-priority full GET → populates HTTP cache; body discarded.
      fetch(u, { signal: ctrl.signal, priority: "low" as RequestPriority })
        .then((r) => r.blob())
        .then(() => console.info("[Player] preloaded", u.split("/").slice(-2).join("/")))
        .catch(() => { /* aborted or failed — fine */ });
    });
    return () => controllers.forEach((c) => c.abort());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentSong?.id, queue]);

  // ────────────────────────────────────────────────────────────────────────────
  // Render — media is rendered at root and never unmounts; overlays change.
  // ────────────────────────────────────────────────────────────────────────────
  const isPlaying = !!currentSong;

  return (
    <div
      className={`relative min-h-screen w-screen overflow-hidden ${isPlaying ? "bg-black" : themeStyle.bg}`}
      onClick={() => {
        if (audioBlocked) void unlockAudio();
      }}
    >
      {/* ── Standby decorative glow ───────────────────────────────────────── */}
      {!isPlaying && (
        <div className="absolute inset-0 pointer-events-none overflow-hidden">
          <div className="absolute top-1/3 left-1/2 -translate-x-1/2 w-[600px] h-[600px] bg-violet-700/15 rounded-full blur-[120px] animate-pulse-glow" />
          <div className="absolute bottom-1/4 right-1/4 w-80 h-80 bg-purple-800/10 rounded-full blur-[80px] animate-pulse-glow" style={{ animationDelay: "2s" }} />
        </div>
      )}

      {/* ── Media (always mounted, hidden in standby) ─────────────────────── */}
      <video
        ref={videoRef}
        className={`absolute inset-0 w-full h-full object-contain ${isPlaying ? "" : "invisible pointer-events-none"}`}
        playsInline
        muted
      />
      <audio ref={vocalRef} preload="auto" className="hidden" />
      <audio ref={instrRef} preload="auto" className="hidden" />

      {/* ── Subtitle layer (only when has timing) ─────────────────────────── */}
      {isPlaying && currentSong?.has_timing && (
        <SubtitleLayer
          key={subtitleRevision}
          song={currentSong}
          videoRef={videoRef}
          offsetMs={subtitleOffsetMs}
        />
      )}

      {/* ── Standby UI ────────────────────────────────────────────────────── */}
      {!isPlaying && (
        <>
          <header className="relative z-10 flex items-center justify-between px-10 py-6">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-violet-500 to-purple-700 flex items-center justify-center shadow-lg shadow-violet-900/50">
                <svg viewBox="0 0 24 24" fill="white" className="w-5 h-5">
                  <path d="M12 3a9 9 0 110 18A9 9 0 0112 3zm0 4a5 5 0 100 10A5 5 0 0012 7zm0 2a3 3 0 110 6 3 3 0 010-6z"/>
                  <circle cx="12" cy="12" r="1.5" fill="white"/>
                </svg>
              </div>
              <div className="flex flex-col">
                <span className={`font-bold text-2xl tracking-tight leading-none ${themeStyle.headerText}`}>
                  {room?.name ?? "響窩"}
                </span>
                <span className="text-white/30 text-[10px] tracking-widest mt-0.5">響窩 ECHONEST</span>
              </div>
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

          <div className="relative z-10 flex flex-1 items-center justify-center px-10 gap-20 min-h-[70vh]">
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

          {/* Credit */}
          <div className="absolute bottom-5 left-0 right-0 text-center pointer-events-none">
            <p className="text-white/20 text-xs tracking-wide">
              響窩 Echonest · 由 CBC 製作
            </p>
          </div>
        </>
      )}

      {/* ── Playing-time HUD ──────────────────────────────────────────────── */}
      {isPlaying && (
        <>
          {/* Top-left: song info */}
          <div className="absolute top-4 left-4 z-10 bg-black/60 backdrop-blur-sm rounded-xl px-4 py-2.5 max-w-md">
            <p className="text-white font-semibold text-sm truncate">{currentSong?.title}</p>
            {currentSong?.artist && (
              <p className="text-gray-300 text-xs mt-0.5">{currentSong.artist}</p>
            )}
            {currentQueueItem?.guest?.nickname && (
              <p className="text-purple-300 text-xs mt-0.5">
                ♪ {currentQueueItem.guest.nickname}
              </p>
            )}
          </div>

          {/* Top-right: clock + guests + QR code */}
          <div className="absolute top-4 right-4 z-10 flex flex-col items-end gap-2">
            <div className="flex items-center gap-3 bg-black/60 backdrop-blur-sm rounded-xl px-3 py-2">
              {guests.length > 0 && (
                <div className="flex items-center gap-1.5">
                  <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                  <span className="text-white/70 text-xs">{guests.length}</span>
                </div>
              )}
              <span className="text-white/80 text-xs font-mono tabular-nums">{clock}</span>
            </div>
            {remoteUrl && (
              <div className="bg-white rounded-lg p-1.5 shadow-lg">
                <QRCode value={remoteUrl} size={72} bgColor="#ffffff" fgColor="#0f0f0f" />
              </div>
            )}
          </div>

          {/* Next song (lower right) */}
          {nextItem && (
            <div className="absolute bottom-16 right-4 z-10 bg-black/60 backdrop-blur-sm rounded-xl px-4 py-2.5 max-w-xs">
              <p className="text-gray-400 text-xs uppercase tracking-wider mb-0.5">下一首</p>
              <p className="text-white text-sm truncate">
                {nextItem.song?.title ?? nextItem.song_id}
              </p>
              <div className="flex items-center gap-2 mt-0.5">
                {nextItem.guest?.nickname && (
                  <p className="text-gray-400 text-xs">{nextItem.guest.nickname} 點的</p>
                )}
                {nextItem.status !== "ready" && nextItem.status !== "playing" && (
                  <p className="text-amber-400 text-xs">
                    {STAGE_LABELS[nextItem.status] ?? nextItem.status}
                  </p>
                )}
              </div>
            </div>
          )}

          {/* Bottom: progress bar */}
          <div className="absolute bottom-0 left-0 right-0 z-10 px-6 pb-4 pt-8 bg-gradient-to-t from-black/70 to-transparent">
            <div className="h-1 bg-white/15 rounded-full overflow-hidden mb-1.5">
              <div
                className="h-full bg-gradient-to-r from-violet-400 to-purple-300 transition-all"
                style={{ width: `${progressPct}%` }}
              />
            </div>
            <div className="flex justify-between text-xs text-white/60 font-mono tabular-nums">
              <span>{formatTime(videoPosition)}</span>
              <span>{formatTime(duration)}</span>
            </div>
          </div>
        </>
      )}

      {/* ── Processing badge — small corner indicator, click to expand ────── */}
      {processing && (
        <button
          onClick={() => setProcessingExpanded((v) => !v)}
          className={`absolute z-20 transition-all cursor-pointer ${
            isPlaying
              ? "bottom-16 left-4"  // playing: above progress bar, left side
              : "bottom-8 right-8"  // standby: bottom-right corner
          }`}
          aria-label="Processing details"
        >
          {processingExpanded ? (
            <div className="bg-black/85 backdrop-blur-xl border border-white/10 rounded-2xl px-5 py-3 text-left shadow-2xl min-w-56">
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-white/50 text-[10px] uppercase tracking-wider">下一首處理中</span>
                <span className="text-white/30 text-xs">▾</span>
              </div>
              <p className="text-white font-medium text-sm">
                {STAGE_LABELS[processing.stage] ?? processing.stage}
              </p>
              {processing.percent > 0 && (
                <>
                  <div className="w-full h-1 bg-white/10 rounded-full mt-2 overflow-hidden">
                    <div
                      className="h-full bg-gradient-to-r from-violet-500 to-purple-400 rounded-full transition-all duration-300"
                      style={{ width: `${processing.percent}%` }}
                    />
                  </div>
                  <p className="text-white/40 text-[10px] mt-1">{processing.percent}%</p>
                </>
              )}
            </div>
          ) : (
            <div className="bg-black/70 backdrop-blur-sm border border-white/10 rounded-full pl-2 pr-3 py-1.5 flex items-center gap-2 hover:bg-black/85 transition-colors">
              <div className="w-3 h-3 border-2 border-violet-400 border-t-transparent rounded-full animate-spin" />
              <span className="text-white/80 text-xs font-medium tabular-nums">
                {processing.percent > 0 ? `${processing.percent}%` : "…"}
              </span>
            </div>
          )}
        </button>
      )}

      <ReactionOverlay reactions={reactions} />
      {systemError && <SystemErrorToast message={systemError} />}

      {/* Activity toast — transient notification of what someone just did */}
      {activity && (
        <div
          key={activity.id}
          className="absolute bottom-32 left-1/2 -translate-x-1/2 z-30 bg-black/80 backdrop-blur-md border border-white/15 rounded-full px-5 py-2 shadow-2xl pointer-events-none animate-activity-pop"
        >
          <p className="text-white text-sm font-medium whitespace-nowrap">
            <span className="text-violet-300">{activity.actor}</span>
            <span className="text-white/30 mx-2">·</span>
            <span>{activity.text}</span>
          </p>
        </div>
      )}

      {/* Tap-to-start overlay — just a single play button */}
      {audioBlocked && isPlaying && (
        <div
          className="absolute inset-0 z-50 flex items-center justify-center cursor-pointer bg-black/80 backdrop-blur-sm"
          onClick={() => void unlockAudio()}
        >
          <button
            className="w-28 h-28 rounded-full bg-white/95 flex items-center justify-center shadow-2xl active:scale-95 transition-transform"
            aria-label="開始播放"
          >
            <svg viewBox="0 0 24 24" fill="#0a0a0a" className="w-12 h-12 ml-1.5">
              <path d="M8 5v14l11-7z" />
            </svg>
          </button>
        </div>
      )}
    </div>
  );
}

function ReactionOverlay({
  reactions,
}: {
  reactions: { id: number; emoji: string; from: string; x: number }[];
}) {
  return (
    <div className="absolute inset-0 pointer-events-none z-40 overflow-hidden">
      {reactions.map((r) => (
        <div
          key={r.id}
          className="absolute bottom-20 animate-reaction-float text-center"
          style={{ left: `${r.x}%` }}
        >
          <div className="text-6xl drop-shadow-2xl">{r.emoji}</div>
          <div className="text-white/80 text-xs mt-1 bg-black/40 backdrop-blur rounded-full px-2 py-0.5 inline-block">
            {r.from}
          </div>
        </div>
      ))}
    </div>
  );
}

function SystemErrorToast({ message }: { message: string }) {
  return (
    <div className="absolute top-6 left-1/2 -translate-x-1/2 z-50 bg-red-900/80 backdrop-blur-md border border-red-500/30 rounded-xl px-5 py-3 max-w-md shadow-2xl">
      <p className="text-white text-sm font-medium">⚠ {message}</p>
    </div>
  );
}
