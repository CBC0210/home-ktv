"use client";

import type { ReactNode } from "react";

interface Props {
  adding: boolean;
  added: boolean;
  onAdd: (position: "end" | "next") => void;
  /** Optional extra control stacked below (e.g. ♥ unfavorite). */
  extra?: ReactNode;
}

/**
 * The one-and-only "add a song" control. Every list (search / 曲庫 /
 * 資料庫 / 排行榜) uses this so the 點歌 + 插播 buttons look and sit
 * identically — right-aligned vertical pair.
 */
export default function AddButtons({ adding, added, onAdd, extra }: Props) {
  return (
    <div className="flex flex-col gap-1 flex-shrink-0 items-end">
      <button
        onClick={() => onAdd("end")}
        disabled={adding}
        title="加入隊列（排到隊尾）"
        className={`text-base w-9 h-9 rounded-xl transition-all font-bold flex items-center justify-center ${
          added
            ? "bg-emerald-600 text-white"
            : "bg-violet-600 hover:bg-violet-500 text-white disabled:opacity-40"
        }`}
      >
        {adding ? "…" : added ? "✓" : "+"}
      </button>
      <button
        onClick={() => onAdd("next")}
        disabled={adding}
        title="插播（插到下一首播放）"
        className="text-[10px] w-9 h-6 rounded-lg bg-white/8 hover:bg-white/15 text-white/55 hover:text-white transition-colors disabled:opacity-40 font-medium"
      >
        插播
      </button>
      {extra}
    </div>
  );
}
