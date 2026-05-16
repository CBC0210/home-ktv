"use client";

import { useEffect, useRef } from "react";
import type { Song } from "@/lib/types";
import { getLyricsAss } from "@/lib/api";

interface Props {
  song: Song;
  videoRef: React.RefObject<HTMLVideoElement | null>;
  /** Positive = subtitles shown LATER (delayed). Applied live, no reload. */
  offsetMs?: number;
}

// libass-wasm ships incomplete TS types; declare the runtime methods we use.
interface OctopusInst {
  resize: (width: number, height: number, top?: number, left?: number) => void;
  setCurrentTime: (t: number) => void;
  setIsPaused: (paused: boolean, t?: number) => void;
  setRate: (rate: number) => void;
  dispose: () => void;
}

export default function SubtitleLayer({ song, videoRef, offsetMs = 0 }: Props) {
  const octopusRef = useRef<OctopusInst | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  // libass `timeOffset` is added to currentTime. To DELAY subtitles
  // (positive offsetMs) we feed a SMALLER time → negate. Kept in a ref so
  // the video listeners always read the latest value without re-subscribing.
  const offsetRef = useRef(0);
  offsetRef.current = -offsetMs / 1000;

  // We render libass to OUR OWN full-screen canvas and sync time manually,
  // instead of letting libass attach to the <video>. libass's video mode
  // sizes the subtitle canvas to the video's *picture rectangle*
  // (object-fit aware) — so on a video whose aspect ≠ the screen, the
  // letterbox black bars clip / hide the lyrics. A screen-filling canvas
  // keeps lyrics in the lower-centre of the SCREEN, above the bars.
  useEffect(() => {
    if (!song.has_timing) return;
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return;

    let destroyed = false;
    let inst: OctopusInst | null = null;
    let cleanup: (() => void) | null = null;

    const dpr = window.devicePixelRatio || 1;
    const sizeCanvas = () => {
      const w = Math.max(1, Math.round(canvas.clientWidth * dpr));
      const h = Math.max(1, Math.round(canvas.clientHeight * dpr));
      return { w, h };
    };

    (async () => {
      let assContent = "";
      try {
        assContent = await getLyricsAss(song.id);
      } catch (err) {
        console.error("[SubtitleLayer] failed to fetch ASS:", err);
        return;
      }
      if (!assContent || destroyed) return;

      try {
        const { default: SubtitlesOctopusClass } = await import("libass-wasm");
        if (destroyed) return;

        // Seed the backing store before construction so worker-init gets
        // sane dimensions (a bare <canvas> defaults to 300×150).
        const { w, h } = sizeCanvas();
        canvas.width = w;
        canvas.height = h;

        const options = {
          canvas,                       // ← our screen-filling canvas (no `video`)
          subContent: assContent,
          workerUrl: "/libass/subtitles-octopus-worker.js",
          legacyWorkerUrl: "/libass/subtitles-octopus-worker-legacy.js",
          targetFps: 30,
          prescaleFactor: 1.0,
          renderAhead: 0.5,
          fallbackFont: "/libass/notocjk.otf",
          availableFonts: {
            "黑体": "/libass/fallback.ttf",
            "黑體": "/libass/fallback.ttf",
            "Noto Sans CJK SC": "/libass/notocjk.otf",
          },
          onReady: () => {
            console.info("[SubtitleLayer] libass ready (screen-fill canvas)");
            try {
              const s = sizeCanvas();
              inst?.resize(s.w, s.h);
              inst?.setCurrentTime(video.currentTime + offsetRef.current);
              inst?.setIsPaused(video.paused, video.currentTime + offsetRef.current);
            } catch { /* ignore */ }
          },
          onError: (e: unknown) => console.error("[SubtitleLayer] libass runtime error:", e),
        } as unknown as ConstructorParameters<typeof SubtitlesOctopusClass>[0];

        inst = new SubtitlesOctopusClass(options) as unknown as OctopusInst;
        octopusRef.current = inst;

        // ── Manual time sync (replaces libass's own video listeners) ──────
        const t = () => video.currentTime + offsetRef.current;
        const onTime = () => inst?.setCurrentTime(t());
        const onPlay = () => inst?.setIsPaused(false, t());
        const onPause = () => inst?.setIsPaused(true, t());
        const onSeeking = () => inst?.setIsPaused(true, t());
        const onSeeked = () => { inst?.setCurrentTime(t()); inst?.setIsPaused(video.paused, t()); };
        const onRate = () => inst?.setRate(video.playbackRate);
        video.addEventListener("timeupdate", onTime);
        video.addEventListener("playing", onPlay);
        video.addEventListener("play", onPlay);
        video.addEventListener("pause", onPause);
        video.addEventListener("waiting", onPause);
        video.addEventListener("seeking", onSeeking);
        video.addEventListener("seeked", onSeeked);
        video.addEventListener("ratechange", onRate);

        // ── Keep the canvas screen-filling on any layout change ───────────
        const onResize = () => {
          const s = sizeCanvas();
          try { inst?.resize(s.w, s.h); } catch { /* ignore */ }
        };
        window.addEventListener("resize", onResize);
        document.addEventListener("fullscreenchange", onResize);
        document.addEventListener("webkitfullscreenchange", onResize);
        const ro = typeof ResizeObserver !== "undefined" ? new ResizeObserver(onResize) : null;
        ro?.observe(canvas);

        cleanup = () => {
          video.removeEventListener("timeupdate", onTime);
          video.removeEventListener("playing", onPlay);
          video.removeEventListener("play", onPlay);
          video.removeEventListener("pause", onPause);
          video.removeEventListener("waiting", onPause);
          video.removeEventListener("seeking", onSeeking);
          video.removeEventListener("seeked", onSeeked);
          video.removeEventListener("ratechange", onRate);
          window.removeEventListener("resize", onResize);
          document.removeEventListener("fullscreenchange", onResize);
          document.removeEventListener("webkitfullscreenchange", onResize);
          ro?.disconnect();
        };
      } catch (err) {
        console.error("[SubtitleLayer] libass init failed:", err);
      }
    })();

    return () => {
      destroyed = true;
      cleanup?.();
      try { (inst ?? octopusRef.current)?.dispose(); } catch { /* ignore */ }
      octopusRef.current = null;
    };
  }, [song.id, song.has_timing]);  // eslint-disable-line react-hooks/exhaustive-deps

  // Live offset adjustment — push the new time immediately (offsetRef is
  // already updated above; the timeupdate listener will keep it thereafter).
  useEffect(() => {
    const inst = octopusRef.current;
    const video = videoRef.current;
    if (inst && video) {
      try { inst.setCurrentTime(video.currentTime + offsetRef.current); } catch { /* ignore */ }
    }
  }, [offsetMs]);  // eslint-disable-line react-hooks/exhaustive-deps

  if (song.has_timing) {
    // Full-screen subtitle canvas, above the video + its letterbox bars.
    return (
      <canvas
        ref={canvasRef}
        className="absolute inset-0 w-full h-full pointer-events-none z-20"
      />
    );
  }

  if (song.lyrics_source && song.lyrics_source !== "none") {
    return (
      <div className="absolute bottom-24 left-0 right-0 flex justify-center pointer-events-none px-8">
        <div className="bg-black/70 backdrop-blur-sm rounded-xl px-6 py-3 text-center max-w-2xl">
          <p className="text-white text-base leading-relaxed">
            純文字歌詞 — 請在手機遙控查看
          </p>
          <p className="text-gray-400 text-xs mt-1">
            來源：{song.lyrics_source}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="absolute bottom-20 left-0 right-0 flex justify-center pointer-events-none">
      <div className="bg-black/50 backdrop-blur-sm rounded-xl px-5 py-2">
        <p className="text-gray-400 text-sm">
          無歌詞 — 請在手機遙控自行搜尋
        </p>
      </div>
    </div>
  );
}
