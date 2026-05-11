"use client";

import type { Song } from "@/lib/types";

interface Props {
  song: Song;
  positionSec: number;
}

// Minimal subtitle display — shows song info when no ASS renderer is attached
export default function SubtitleLayer({ song, positionSec: _positionSec }: Props) {
  if (!song.has_timing) {
    return (
      <div className="absolute bottom-24 left-0 right-0 flex justify-center pointer-events-none">
        <div className="bg-black/60 backdrop-blur-sm rounded-xl px-6 py-3 text-center max-w-2xl">
          <p className="text-gray-300 text-sm">
            {song.lyrics_source === "none"
              ? "無歌詞 — 請在手機遙控查詢歌詞"
              : "純文字歌詞 — 請在手機遙控檢視"}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div
      id="libass-canvas"
      className="absolute inset-0 pointer-events-none"
      aria-hidden
    />
  );
}
