"use client";

import { useState, useCallback, useRef } from "react";
import Image from "next/image";
import { youtubeSearch, searchSongs, addSong, isYoutubeUrl, type YoutubeResult } from "@/lib/api";
import LeaderboardView from "./LeaderboardView";

interface Props {
  roomId: string;
  token?: string | null;
  onAdded?: () => void;
}

function formatDuration(sec: number | null): string {
  if (!sec) return "";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

type SubTab = "search" | "leaderboard";

export default function SearchView({ roomId, token = null, onAdded }: Props) {
  const [subTab, setSubTab] = useState<SubTab>("search");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<YoutubeResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [adding, setAdding] = useState<string | null>(null);
  const [addedId, setAddedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const runSearch = useCallback(async (q: string) => {
    if (!q.trim()) {
      setResults([]);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      // Run YouTube search + local cache check in parallel
      const [ytResults, cachedSongs] = await Promise.all([
        youtubeSearch(q).catch(() => [] as YoutubeResult[]),
        searchSongs(q).catch(() => []),
      ]);

      const cachedIds = new Set(cachedSongs.map((s) => s.id));

      // Merge: mark cached results with the ⚡ flag
      const merged: YoutubeResult[] = ytResults.map((r) => ({
        ...r,
        cached: cachedIds.has(r.id),
      }));

      // Prepend any cached results that didn't appear in YT search
      const ytIds = new Set(ytResults.map((r) => r.id));
      for (const s of cachedSongs) {
        if (!ytIds.has(s.id)) {
          merged.unshift({
            id: s.id,
            title: s.title,
            channel: s.artist,
            duration_sec: s.duration_sec,
            thumbnail_url: s.thumbnail_url,
            url: `https://www.youtube.com/watch?v=${s.id}`,
            cached: true,
          });
        }
      }

      setResults(merged);
    } catch {
      setError("搜尋失敗，請重試");
    } finally {
      setLoading(false);
    }
  }, []);

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const val = e.target.value;
    setQuery(val);

    // Debounce: auto-search 600ms after typing stops
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (val.trim() && !isYoutubeUrl(val)) {
      debounceRef.current = setTimeout(() => void runSearch(val), 600);
    }
  }

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (isYoutubeUrl(query)) {
      void handleAdd(query, "end");
    } else {
      void runSearch(query);
    }
  }

  function handlePaste(e: React.ClipboardEvent<HTMLInputElement>) {
    const text = e.clipboardData.getData("text");
    if (isYoutubeUrl(text)) {
      e.preventDefault();
      setQuery(text);
      void handleAdd(text, "end");
    }
  }

  async function handleAdd(url: string, position: "end" | "next" = "end") {
    const key = url;
    setAdding(key);
    setError(null);
    try {
      await addSong({ youtube_url: url, room_id: roomId, position });
      setAddedId(key);
      setTimeout(() => setAddedId(null), 2500);
      onAdded?.();
    } catch {
      setError("加入失敗，請重試");
    } finally {
      setAdding(null);
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Sub-tab selector */}
      <div className="flex gap-0 border-b border-gray-800 sticky top-0 bg-gray-950 z-10">
        <button
          onClick={() => setSubTab("search")}
          className={`flex-1 py-3 text-sm font-medium transition-colors border-b-2 ${
            subTab === "search"
              ? "border-purple-500 text-purple-400"
              : "border-transparent text-gray-500 hover:text-gray-300"
          }`}
        >
          🔍 搜尋
        </button>
        <button
          onClick={() => setSubTab("leaderboard")}
          className={`flex-1 py-3 text-sm font-medium transition-colors border-b-2 ${
            subTab === "leaderboard"
              ? "border-purple-500 text-purple-400"
              : "border-transparent text-gray-500 hover:text-gray-300"
          }`}
        >
          🏆 排行榜
        </button>
      </div>

      {/* Leaderboard sub-tab */}
      {subTab === "leaderboard" && (
        <LeaderboardView roomId={roomId} token={token} onAdded={onAdded} />
      )}

      {/* Search sub-tab */}
      {subTab === "search" && (
      <>
      {/* Search bar */}
      <form onSubmit={onSubmit} className="p-4 flex gap-2 sticky top-0 bg-gray-950 z-10">
        <input
          type="text"
          value={query}
          onChange={handleChange}
          onPaste={handlePaste}
          placeholder="搜尋歌曲 或 貼上 YouTube 連結"
          autoComplete="off"
          autoCorrect="off"
          className="flex-1 bg-gray-800 border border-gray-700 rounded-xl px-4 py-3 text-white placeholder-gray-500 focus:outline-none focus:border-purple-500 text-sm"
        />
        <button
          type="submit"
          disabled={loading || !query.trim()}
          className="bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white px-4 rounded-xl transition-colors font-medium min-w-14"
        >
          {loading ? "…" : "搜尋"}
        </button>
      </form>

      {error && <p className="px-4 text-red-400 text-sm pb-2">{error}</p>}

      {/* Results */}
      <div className="flex-1 overflow-y-auto divide-y divide-gray-800/60">
        {results.length === 0 && !loading && (
          <div className="flex flex-col items-center justify-center py-16 text-center px-8 gap-3">
            <span className="text-4xl">🎵</span>
            <p className="text-gray-400">搜尋歌曲或貼上 YouTube 連結</p>
            <p className="text-gray-600 text-xs">支援關鍵字、歌名、演唱者</p>
          </div>
        )}

        {loading && results.length === 0 && (
          <div className="flex justify-center py-12">
            <span className="text-gray-500">搜尋中…</span>
          </div>
        )}

        {results.map((item) => (
          <div key={item.id} className="flex items-center gap-3 px-4 py-3">
            {/* Thumbnail */}
            <div className="relative w-14 h-10 rounded-lg overflow-hidden bg-gray-800 flex-shrink-0">
              {item.thumbnail_url ? (
                <Image
                  src={item.thumbnail_url}
                  alt={item.title}
                  fill
                  className="object-cover"
                  unoptimized
                />
              ) : (
                <div className="w-full h-full flex items-center justify-center text-lg">🎵</div>
              )}
            </div>

            {/* Info */}
            <div className="flex-1 min-w-0">
              <p className="text-white text-sm truncate leading-tight">{item.title}</p>
              <div className="flex items-center gap-2 mt-0.5 flex-wrap">
                {item.channel && (
                  <span className="text-gray-500 text-xs truncate max-w-[120px]">
                    {item.channel}
                  </span>
                )}
                {item.duration_sec != null && (
                  <span className="text-gray-600 text-xs">
                    {formatDuration(item.duration_sec)}
                  </span>
                )}
                {item.cached && (
                  <span className="text-green-400 text-xs font-medium">⚡ 立即</span>
                )}
              </div>
            </div>

            {/* Actions */}
            <div className="flex gap-1 flex-shrink-0">
              <button
                onClick={() => handleAdd(item.url, "next")}
                disabled={adding === item.url}
                title="插播（下一首）"
                className="text-xs bg-gray-700 hover:bg-gray-600 text-gray-300 px-2 py-1.5 rounded-lg transition-colors"
              >
                插播
              </button>
              <button
                onClick={() => handleAdd(item.url, "end")}
                disabled={adding === item.url}
                className={`text-sm px-3 py-1.5 rounded-lg transition-colors font-medium min-w-10 ${
                  addedId === item.url
                    ? "bg-green-600 text-white"
                    : "bg-purple-600 hover:bg-purple-500 text-white disabled:opacity-50"
                }`}
              >
                {adding === item.url ? "…" : addedId === item.url ? "✓" : "+"}
              </button>
            </div>
          </div>
        ))}
      </div>
      </>
      )}
    </div>
  );
}
