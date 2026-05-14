"use client";

import { useEffect, useRef } from "react";
import type SubtitlesOctopus from "libass-wasm";
import type { Song } from "@/lib/types";

interface Props {
  song: Song;
  videoRef: React.RefObject<HTMLVideoElement | null>;
}

export default function SubtitleLayer({ song, videoRef }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const octopusRef = useRef<SubtitlesOctopus | null>(null);

  // Initialize libass renderer
  useEffect(() => {
    if (!song.has_timing || !containerRef.current) return;

    const container = containerRef.current;
    const base = process.env.NEXT_PUBLIC_API_URL ?? "";
    const assUrl = `${base}/songs/${song.id}/lyrics.ass`;

    let destroyed = false;

    import("libass-wasm").then(({ default: SubtitlesOctopusClass }) => {
      if (destroyed) return;

      const instance = new SubtitlesOctopusClass({
        subUrl: assUrl,
        workerUrl: "/libass/subtitles-octopus-worker.js",
        legacyWorkerUrl: "/libass/subtitles-octopus-worker-legacy.js",
        targetFps: 30,
        prescaleFactor: 1.0,
        renderAhead: 0.5,
        availableFonts: {},
        fallbackFont: "Arial",
        container,
      });

      octopusRef.current = instance;

      // Sync to current video position immediately after load
      const video = videoRef.current;
      if (video) {
        instance.setCurrentTime(video.currentTime);
      }
    }).catch(() => {});

    return () => {
      destroyed = true;
      octopusRef.current?.dispose();
      octopusRef.current = null;
    };
  }, [song.id, song.has_timing]);  // eslint-disable-line react-hooks/exhaustive-deps

  // Drive subtitle position from video timeupdate (~4x/sec) for smooth karaoke
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const onTimeUpdate = () => {
      octopusRef.current?.setCurrentTime(video.currentTime);
    };

    video.addEventListener("timeupdate", onTimeUpdate);
    return () => video.removeEventListener("timeupdate", onTimeUpdate);
  }, [videoRef]);

  if (song.has_timing) {
    return (
      <div
        ref={containerRef}
        className="absolute inset-0 pointer-events-none"
        aria-hidden
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
