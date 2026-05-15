"use client";

import { useEffect, useRef } from "react";
import type SubtitlesOctopus from "libass-wasm";
import type { Song } from "@/lib/types";
import { getLyricsAss } from "@/lib/api";

interface Props {
  song: Song;
  videoRef: React.RefObject<HTMLVideoElement | null>;
  /** Positive = subtitles shown LATER (delayed). Applied live, no reload. */
  offsetMs?: number;
}

export default function SubtitleLayer({ song, videoRef, offsetMs = 0 }: Props) {
  const octopusRef = useRef<SubtitlesOctopus | null>(null);

  // libass `timeOffset` is added to video.currentTime. To DELAY subtitles
  // (positive offsetMs) we must feed it a SMALLER time → negate.
  const libassOffset = -offsetMs / 1000;

  // Initialize libass renderer. libass-wasm v4 requires a `video` or `canvas`
  // element — passing `container` is no longer accepted.
  useEffect(() => {
    if (!song.has_timing) return;
    const video = videoRef.current;
    if (!video) return;

    let destroyed = false;

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

        const options = {
          video,
          subContent: assContent,
          workerUrl: "/libass/subtitles-octopus-worker.js",
          legacyWorkerUrl: "/libass/subtitles-octopus-worker-legacy.js",
          targetFps: 30,
          prescaleFactor: 1.0,
          renderAhead: 0.5,
          // 黑体/黑體 → LXGW WenKai TC (pretty, Traditional-Chinese tuned).
          // Noto Sans CJK is the per-glyph fallback so Korean Hangul and
          // Japanese Kana (absent in LXGW) still render.
          fallbackFont: "/libass/notocjk.otf",
          availableFonts: {
            "黑体": "/libass/fallback.ttf",
            "黑體": "/libass/fallback.ttf",
            "Noto Sans CJK SC": "/libass/notocjk.otf",
          },
          timeOffset: libassOffset,
          onReady: () => console.info("[SubtitleLayer] libass ready"),
          onError: (e: unknown) => console.error("[SubtitleLayer] libass runtime error:", e),
        } as unknown as ConstructorParameters<typeof SubtitlesOctopusClass>[0];

        const instance = new SubtitlesOctopusClass(options);
        octopusRef.current = instance;
      } catch (err) {
        console.error("[SubtitleLayer] libass init failed:", err);
      }
    })();

    return () => {
      destroyed = true;
      try { octopusRef.current?.dispose(); } catch { /* ignore */ }
      octopusRef.current = null;
    };
  }, [song.id, song.has_timing]);  // eslint-disable-line react-hooks/exhaustive-deps

  // Live offset adjustment — no reload, libass picks up timeOffset per frame.
  useEffect(() => {
    const inst = octopusRef.current as unknown as { timeOffset?: number } | null;
    if (inst) inst.timeOffset = libassOffset;
  }, [libassOffset]);

  // When libass attaches to a video element it auto-syncs to currentTime via
  // the video's `timeupdate` event — no manual hookup needed.

  if (song.has_timing) {
    // libass creates its own canvas overlay positioned over the video element.
    // We don't need a wrapping div; just render nothing here.
    return null;
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
