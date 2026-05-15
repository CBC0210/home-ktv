"use client";

import { useState, useEffect, useCallback } from "react";
import Image from "next/image";
import {
  addSong, getHistory, getFavorites, getRecommendations,
  removeFavorite, type LibrarySong,
} from "@/lib/api";

interface Props {
  roomId: string;
  onAdded?: () => void;
}

type View = "history" | "favorites" | "recommend";

const VIEW_LABEL: Record<View, string> = {
  history: "歷史記錄",
  favorites: "喜歡的歌曲",
  recommend: "歌曲推薦",
};

const VIEW_EMPTY: Record<View, string> = {
  history: "還沒有播放記錄",
  favorites: "還沒有收藏的歌曲（在播放頁按 ♥ 收藏）",
  recommend: "多聽幾首歌後這裡會有推薦",
};

function fmtDur(sec: number | null): string {
  if (!sec) return "";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function LibraryView({ roomId, onAdded }: Props) {
  const [view, setView] = useState<View>("history");
  const [songs, setSongs] = useState<LibrarySong[]>([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState<string | null>(null);
  const [addedId, setAddedId] = useState<string | null>(null);

  const load = useCallback(async (v: View) => {
    setLoading(true);
    try {
      const fn = v === "history" ? getHistory
        : v === "favorites" ? getFavorites
        : getRecommendations;
      setSongs(await fn());
    } catch {
      setSongs([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(view); }, [view, load]);

  async function handleAdd(song: LibrarySong, position: "end" | "next") {
    setAdding(song.id);
    try {
      await addSong({
        youtube_url: `https://www.youtube.com/watch?v=${song.id}`,
        room_id: roomId,
        position,
      });
      setAddedId(song.id);
      setTimeout(() => setAddedId(null), 2000);
      onAdded?.();
    } catch {
      /* ignore */
    } finally {
      setAdding(null);
    }
  }

  async function unfav(songId: string) {
    try {
      await removeFavorite(songId);
      setSongs((s) => s.filter((x) => x.id !== songId));
    } catch { /* ignore */ }
  }

  return (
    <div className="flex flex-col h-full">
      {/* View switcher */}
      <div className="flex gap-2 px-4 py-3 border-b border-white/6">
        {(["history", "favorites", "recommend"] as View[]).map((v) => (
          <button
            key={v}
            onClick={() => setView(v)}
            className={`flex-1 py-2 rounded-xl text-xs font-medium transition-colors ${
              view === v
                ? "bg-violet-600 text-white"
                : "bg-white/8 text-white/55 hover:bg-white/12"
            }`}
          >
            {VIEW_LABEL[v]}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="flex flex-col items-center py-16 gap-3">
            <div className="w-7 h-7 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
            <span className="text-white/30 text-sm">載入中…</span>
          </div>
        ) : songs.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-center px-8 gap-3">
            <div className="w-16 h-16 rounded-full bg-white/5 flex items-center justify-center">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="w-7 h-7 text-white/25">
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 9l10.5-3m0 6.553v3.75a2.25 2.25 0 01-1.632 2.163l-1.32.377a1.803 1.803 0 01-.99-3.467l2.31-.66a2.25 2.25 0 001.632-2.163zm0 0V2.25L9 5.25v10.303" />
              </svg>
            </div>
            <p className="text-white/40 text-sm">{VIEW_EMPTY[view]}</p>
          </div>
        ) : (
          <div className="divide-y divide-white/5">
            {songs.map((song) => (
              <div key={song.id} className="flex items-center gap-3 px-3 py-3 hover:bg-white/4 transition-colors">
                <div className="relative w-12 h-12 rounded-xl overflow-hidden bg-white/8 flex-shrink-0">
                  {song.thumbnail_url ? (
                    <Image src={song.thumbnail_url} alt={song.title} fill className="object-cover" unoptimized />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center">
                      <svg viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5 text-white/20">
                        <path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z" />
                      </svg>
                    </div>
                  )}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-white text-sm font-medium leading-tight line-clamp-2">{song.title}</p>
                  <div className="flex items-center gap-2 mt-0.5">
                    {song.artist && (
                      <span className="text-white/40 text-xs truncate max-w-[55%]">{song.artist}</span>
                    )}
                    {song.duration_sec != null && (
                      <span className="text-white/25 text-xs flex-shrink-0">{fmtDur(song.duration_sec)}</span>
                    )}
                    {song.status === "ready" && (
                      <span className="text-emerald-400 text-xs flex-shrink-0">⚡立即</span>
                    )}
                  </div>
                </div>
                <div className="flex flex-col gap-1 flex-shrink-0">
                  <button
                    onClick={() => handleAdd(song, "end")}
                    disabled={adding === song.id}
                    className={`text-base w-9 h-9 rounded-xl transition-all font-bold flex items-center justify-center ${
                      addedId === song.id
                        ? "bg-emerald-600 text-white"
                        : "bg-violet-600 hover:bg-violet-500 text-white disabled:opacity-40"
                    }`}
                    title="加入隊列"
                  >
                    {adding === song.id ? "…" : addedId === song.id ? "✓" : "+"}
                  </button>
                  {view === "favorites" && (
                    <button
                      onClick={() => unfav(song.id)}
                      className="text-[10px] w-9 h-6 rounded-lg bg-white/8 hover:bg-rose-500/20 text-rose-300/70 hover:text-rose-300 transition-colors"
                      title="取消收藏"
                    >
                      ♥
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
