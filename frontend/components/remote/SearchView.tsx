"use client";

import { useState, useCallback } from "react";
import Image from "next/image";
import { searchSongs, addSong, isYoutubeUrl } from "@/lib/api";
import type { Song } from "@/lib/types";

interface Props {
  roomId: string;
  onAdded?: () => void;
}

export default function SearchView({ roomId, onAdded }: Props) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Song[]>([]);
  const [loading, setLoading] = useState(false);
  const [adding, setAdding] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [addedId, setAddedId] = useState<string | null>(null);

  const handleSearch = useCallback(
    async (q: string) => {
      if (!q.trim()) return;
      setLoading(true);
      setError(null);
      try {
        // YouTube URL → add directly
        if (isYoutubeUrl(q)) {
          await handleAdd(q, "end");
          return;
        }
        const songs = await searchSongs(q);
        setResults(songs);
      } catch {
        setError("搜尋失敗，請重試");
      } finally {
        setLoading(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [roomId]
  );

  async function handleAdd(url: string, position: "end" | "next" = "end") {
    setAdding(url);
    setError(null);
    try {
      await addSong({ youtube_url: url, room_id: roomId, position });
      setAddedId(url);
      setTimeout(() => setAddedId(null), 2000);
      onAdded?.();
    } catch {
      setError("加入失敗，請重試");
    } finally {
      setAdding(null);
    }
  }

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    void handleSearch(query);
  }

  function handlePaste(e: React.ClipboardEvent<HTMLInputElement>) {
    const text = e.clipboardData.getData("text");
    if (isYoutubeUrl(text)) {
      e.preventDefault();
      setQuery(text);
      void handleAdd(text, "end");
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Search bar */}
      <form onSubmit={onSubmit} className="p-4 flex gap-2">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onPaste={handlePaste}
          placeholder="搜尋歌曲 或 貼上 YouTube 連結"
          className="flex-1 bg-gray-800 border border-gray-700 rounded-xl px-4 py-3 text-white placeholder-gray-500 focus:outline-none focus:border-purple-500 text-sm"
        />
        <button
          type="submit"
          disabled={loading || !query.trim()}
          className="bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white px-4 rounded-xl transition-colors font-medium"
        >
          {loading ? "…" : "搜尋"}
        </button>
      </form>

      {error && (
        <p className="px-4 text-red-400 text-sm">{error}</p>
      )}

      {/* Results */}
      <div className="flex-1 overflow-y-auto divide-y divide-gray-800">
        {results.length === 0 && !loading && (
          <div className="flex flex-col items-center justify-center py-16 text-center px-8 gap-3">
            <span className="text-4xl">🔍</span>
            <p className="text-gray-400">搜尋歌曲或貼上 YouTube 連結</p>
          </div>
        )}

        {results.map((song) => (
          <div key={song.id} className="flex items-center gap-3 px-4 py-3">
            <div className="relative w-12 h-12 rounded-lg overflow-hidden bg-gray-800 flex-shrink-0">
              {song.thumbnail_url ? (
                <Image
                  src={song.thumbnail_url}
                  alt={song.title}
                  fill
                  className="object-cover"
                  unoptimized
                />
              ) : (
                <div className="w-full h-full flex items-center justify-center text-xl">
                  🎵
                </div>
              )}
            </div>

            <div className="flex-1 min-w-0">
              <p className="text-white text-sm truncate">{song.title}</p>
              {song.artist && (
                <p className="text-gray-400 text-xs truncate">{song.artist}</p>
              )}
              <div className="flex gap-2 mt-0.5">
                {song.status === "ready" && (
                  <span className="text-green-400 text-xs">⚡ 立即</span>
                )}
                {song.play_count > 0 && (
                  <span className="text-gray-500 text-xs">
                    已唱 {song.play_count} 次
                  </span>
                )}
              </div>
            </div>

            <div className="flex gap-1">
              <button
                onClick={() => handleAdd(`https://youtube.com/watch?v=${song.id}`, "next")}
                disabled={adding === song.id}
                className="text-xs bg-gray-700 hover:bg-gray-600 text-white px-2 py-1 rounded-lg transition-colors"
                title="插播 (下一首)"
              >
                插播
              </button>
              <button
                onClick={() => handleAdd(`https://youtube.com/watch?v=${song.id}`, "end")}
                disabled={adding === song.id}
                className={`text-xs px-3 py-1 rounded-lg transition-colors font-medium ${
                  addedId === song.id
                    ? "bg-green-600 text-white"
                    : "bg-purple-600 hover:bg-purple-500 text-white"
                }`}
              >
                {adding === song.id ? "…" : addedId === song.id ? "✓" : "+"}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
