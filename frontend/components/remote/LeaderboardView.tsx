"use client";

import { useState, useEffect, useCallback } from "react";
import Image from "next/image";
import {
  getLeaderboard,
  addSong,
  type LeaderboardItem,
  type LeaderboardCategory,
} from "@/lib/api";
import AddButtons from "./AddButtons";

interface Props {
  roomId: string;
  token: string | null;
  onAdded?: () => void;
}

// "personal/我的最愛" moved to 資料庫 tab (歷史 / 喜歡的歌曲) — no duplicate here.
const CATEGORIES: { id: LeaderboardCategory; label: string; emoji: string }[] = [
  { id: "all_time", label: "歷史經典", emoji: "🏆" },
  { id: "monthly_hot", label: "本月熱門", emoji: "🔥" },
];

function formatDuration(sec: number | null): string {
  if (!sec) return "";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function LeaderboardView({ roomId, token, onAdded }: Props) {
  const [category, setCategory] = useState<LeaderboardCategory>("all_time");
  const [items, setItems] = useState<LeaderboardItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState<string | null>(null);
  const [addedId, setAddedId] = useState<string | null>(null);

  const load = useCallback(
    async (cat: LeaderboardCategory) => {
      setLoading(true);
      setError(null);
      try {
        const data = await getLeaderboard(cat, 20);
        setItems(data);
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e);
        if (msg.includes("401") && cat === "personal") {
          setError("請先加入房間以查看個人排行榜");
        } else {
          setError("載入排行榜失敗");
        }
        setItems([]);
      } finally {
        setLoading(false);
      }
    },
    []
  );

  useEffect(() => {
    void load(category);
  }, [category, load]);

  async function handleAdd(item: LeaderboardItem, position: "end" | "next") {
    const key = item.song_id;
    setAdding(key);
    try {
      await addSong({
        youtube_url: `https://www.youtube.com/watch?v=${item.song_id}`,
        room_id: roomId,
        position,
      });
      setAddedId(key);
      setTimeout(() => setAddedId(null), 2500);
      onAdded?.();
    } catch {
      // silent — user can retry
    } finally {
      setAdding(null);
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Category selector */}
      <div className="flex gap-2 px-4 pt-3 pb-2 sticky top-0 bg-gray-950 z-10">
        {CATEGORIES.map((c) => (
          <button
            key={c.id}
            onClick={() => setCategory(c.id)}
            className={`flex-1 flex flex-col items-center py-2 rounded-xl text-xs font-medium transition-colors ${
              category === c.id
                ? "bg-purple-600 text-white"
                : "bg-gray-800 text-gray-400 hover:bg-gray-700"
            }`}
          >
            <span className="text-base mb-0.5">{c.emoji}</span>
            {c.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        {loading && (
          <div className="flex justify-center py-12 text-gray-500">載入中…</div>
        )}

        {error && !loading && (
          <div className="flex flex-col items-center py-12 gap-2 text-center px-6">
            <span className="text-3xl">😔</span>
            <p className="text-gray-400 text-sm">{error}</p>
          </div>
        )}

        {!loading && !error && items.length === 0 && (
          <div className="flex flex-col items-center py-12 gap-2 text-center px-6">
            <span className="text-3xl">🎵</span>
            <p className="text-gray-400 text-sm">
              {category === "monthly_hot"
                ? "本月還沒有播放記錄"
                : category === "personal"
                ? "你還沒有播放過任何歌曲"
                : "還沒有播放過任何歌曲"}
            </p>
          </div>
        )}

        {!loading && !error && items.length > 0 && (
          <div className="divide-y divide-gray-800/60">
            {items.map((item) => (
              <div key={item.song_id} className="flex items-center gap-3 px-4 py-3">
                {/* Rank */}
                <div
                  className={`w-7 text-center font-bold text-sm flex-shrink-0 ${
                    item.rank === 1
                      ? "text-yellow-400"
                      : item.rank === 2
                      ? "text-gray-300"
                      : item.rank === 3
                      ? "text-amber-600"
                      : "text-gray-600"
                  }`}
                >
                  {item.rank <= 3 ? ["🥇", "🥈", "🥉"][item.rank - 1] : item.rank}
                </div>

                {/* Thumbnail */}
                <div className="relative w-12 h-9 rounded-lg overflow-hidden bg-gray-800 flex-shrink-0">
                  {item.thumbnail_url ? (
                    <Image
                      src={item.thumbnail_url}
                      alt={item.title}
                      fill
                      className="object-cover"
                      unoptimized
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-base">🎵</div>
                  )}
                </div>

                {/* Info */}
                <div className="flex-1 min-w-0">
                  <p className="text-white text-sm truncate leading-tight">{item.title}</p>
                  <div className="flex items-center gap-2 mt-0.5 flex-wrap">
                    {item.artist && (
                      <span className="text-gray-500 text-xs truncate max-w-[100px]">
                        {item.artist}
                      </span>
                    )}
                    {item.duration_sec != null && (
                      <span className="text-gray-600 text-xs">
                        {formatDuration(item.duration_sec)}
                      </span>
                    )}
                    <span className="text-purple-400 text-xs font-medium">
                      ×{item.play_count}
                    </span>
                  </div>
                </div>

                <AddButtons
                  adding={adding === item.song_id}
                  added={addedId === item.song_id}
                  onAdd={(pos) => handleAdd(item, pos)}
                />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
