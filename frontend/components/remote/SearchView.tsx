"use client";

import { useState, useCallback, useRef } from "react";
import Image from "next/image";
import { youtubeSearch, searchSongs, addSong, isYoutubeUrl, type YoutubeResult } from "@/lib/api";
import LeaderboardView from "./LeaderboardView";
import LibraryView from "./LibraryView";
import SongBankView from "./SongBankView";

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

type SubTab = "search" | "bank" | "library" | "leaderboard";

const SUBTAB_LABEL: Record<SubTab, string> = {
  search: "搜尋",
  bank: "曲庫",
  library: "資料庫",
  leaderboard: "排行榜",
};

export default function SearchView({ roomId, token = null, onAdded }: Props) {
  const [subTab, setSubTab] = useState<SubTab>("search");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<YoutubeResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [adding, setAdding] = useState<string | null>(null);
  const [addedId, setAddedId] = useState<string | null>(null);
  const [addedUrl, setAddedUrl] = useState(false); // feedback for direct URL add
  const [error, setError] = useState<string | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const runSearch = useCallback(async (q: string) => {
    if (!q.trim()) { setResults([]); return; }
    setLoading(true);
    setError(null);
    try {
      const [ytResults, cachedSongs] = await Promise.all([
        youtubeSearch(q).catch(() => [] as YoutubeResult[]),
        searchSongs(q).catch(() => []),
      ]);
      const cachedIds = new Set(cachedSongs.map((s) => s.id));
      const merged: YoutubeResult[] = ytResults.map((r) => ({ ...r, cached: cachedIds.has(r.id) }));
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
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (val.trim() && !isYoutubeUrl(val)) {
      debounceRef.current = setTimeout(() => void runSearch(val), 600);
    }
  }

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (isYoutubeUrl(query)) void handleAdd(query, "end");
    else void runSearch(query);
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
    const isUrlOnly = results.length === 0; // direct URL submit, no result rows
    setAdding(url);
    setError(null);
    try {
      await addSong({ youtube_url: url, room_id: roomId, position });
      if (isUrlOnly) {
        setAddedUrl(true);
        setQuery("");
        setTimeout(() => setAddedUrl(false), 2500);
      } else {
        setAddedId(url);
        setTimeout(() => setAddedId(null), 2500);
      }
      onAdded?.();
    } catch {
      setError("加入失敗，請重試");
    } finally {
      setAdding(null);
    }
  }

  return (
    <div className="flex flex-col h-full">
      {/* Sub-tabs */}
      <div className="flex border-b border-white/8 sticky top-0 bg-[#0a0a0a]/95 backdrop-blur-md z-10">
        {(["search", "bank", "library", "leaderboard"] as SubTab[]).map((t) => (
          <button
            key={t}
            onClick={() => setSubTab(t)}
            className={`flex-1 py-3.5 text-sm font-medium transition-colors relative ${
              subTab === t ? "text-violet-400" : "text-white/40 hover:text-white/70"
            }`}
          >
            {SUBTAB_LABEL[t]}
            {subTab === t && (
              <span className="absolute bottom-0 left-1/2 -translate-x-1/2 w-8 h-0.5 bg-violet-400 rounded-full" />
            )}
          </button>
        ))}
      </div>

      {subTab === "leaderboard" && (
        <LeaderboardView roomId={roomId} token={token} onAdded={onAdded} />
      )}

      {subTab === "bank" && (
        <SongBankView roomId={roomId} onAdded={onAdded} />
      )}

      {subTab === "library" && (
        <LibraryView roomId={roomId} onAdded={onAdded} />
      )}

      {subTab === "search" && (
        <>
          {/* Search bar */}
          <form onSubmit={onSubmit} className="p-4 sticky top-[49px] bg-[#0a0a0a]/95 backdrop-blur-md z-10">
            <div className="flex gap-2">
              <div className="flex-1 relative">
                <svg viewBox="0 0 24 24" fill="currentColor" className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-white/30 pointer-events-none">
                  <path d="M15.5 14h-.79l-.28-.27C15.41 12.59 16 11.11 16 9.5 16 5.91 13.09 3 9.5 3S3 5.91 3 9.5 5.91 16 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z" />
                </svg>
                <input
                  type="text"
                  value={query}
                  onChange={handleChange}
                  onPaste={handlePaste}
                  placeholder="搜尋歌曲或貼上 YouTube / Bilibili 連結"
                  autoComplete="off"
                  autoCorrect="off"
                  className="w-full bg-white/8 border border-white/10 rounded-2xl pl-10 pr-4 py-3 text-white placeholder-white/25 focus:outline-none focus:border-violet-500/50 focus:bg-white/10 transition-all text-sm"
                />
              </div>
              <button
                type="submit"
                disabled={loading || !!adding || !query.trim()}
                className={`px-4 rounded-2xl transition-all font-medium text-sm min-w-14 h-full ${
                  addedUrl
                    ? "bg-emerald-600 text-white"
                    : "bg-violet-600 hover:bg-violet-500 disabled:opacity-40 text-white"
                }`}
              >
                {adding && results.length === 0 ? (
                  <svg className="animate-spin w-4 h-4 mx-auto" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                  </svg>
                ) : addedUrl ? "✓ 已加入" : loading ? (
                  <svg className="animate-spin w-4 h-4 mx-auto" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                  </svg>
                ) : isYoutubeUrl(query) ? "加入" : "搜尋"}
              </button>
            </div>
            {error && (
              <p className="text-red-400 text-xs mt-2 pl-1">{error}</p>
            )}
          </form>

          {/* Results */}
          <div className="flex-1 overflow-y-auto">
            {results.length === 0 && !loading && (
              <div className="flex flex-col items-center justify-center py-20 text-center px-8 gap-4">
                <div className="w-20 h-20 rounded-full bg-white/5 flex items-center justify-center">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="w-9 h-9 text-white/25">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
                  </svg>
                </div>
                <div>
                  <p className="text-white/50 font-medium">搜尋歌曲</p>
                  <p className="text-white/25 text-sm mt-1">支援關鍵字、歌名、演唱者</p>
                  <p className="text-white/20 text-xs mt-0.5">或貼上 YouTube / Bilibili 連結直接加入</p>
                </div>
              </div>
            )}

            {loading && results.length === 0 && (
              <div className="flex flex-col items-center py-16 gap-3">
                <div className="w-8 h-8 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
                <span className="text-white/30 text-sm">搜尋中…</span>
              </div>
            )}

            <div className="divide-y divide-white/5">
              {results.map((item) => (
                <div key={item.id} className="flex items-start gap-3 px-3 py-3 hover:bg-white/4 transition-colors">
                  {/* Thumbnail */}
                  <div className="relative w-14 h-10 mt-0.5 rounded-lg overflow-hidden bg-white/8 flex-shrink-0">
                    {item.thumbnail_url ? (
                      <Image src={item.thumbnail_url} alt={item.title} fill className="object-cover" unoptimized />
                    ) : (
                      <div className="w-full h-full flex items-center justify-center">
                        <svg viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5 text-white/20">
                          <path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z" />
                        </svg>
                      </div>
                    )}
                    {item.cached && (
                      <div className="absolute inset-0 bg-emerald-500/20 flex items-end justify-end p-0.5">
                        <span className="text-emerald-400 text-[9px] font-bold bg-black/60 rounded px-1 leading-4">⚡</span>
                      </div>
                    )}
                  </div>

                  {/* Info — wraps to 2 lines so long titles stay readable */}
                  <div className="flex-1 min-w-0">
                    <p className="text-white text-sm font-medium leading-snug line-clamp-2 break-words">{item.title}</p>
                    <div className="flex items-center gap-2 mt-1 flex-wrap">
                      {item.channel && (
                        <span className="text-white/40 text-xs truncate max-w-[60%]">{item.channel}</span>
                      )}
                      {item.duration_sec != null && (
                        <span className="text-white/25 text-xs flex-shrink-0">{formatDuration(item.duration_sec)}</span>
                      )}
                      {item.cached && (
                        <span className="text-emerald-400 text-xs font-medium flex-shrink-0">⚡立即</span>
                      )}
                    </div>
                  </div>

                  {/* Actions — only the + button stays inline; insert-next via secondary tap */}
                  <div className="flex flex-col gap-1 flex-shrink-0">
                    <button
                      onClick={() => handleAdd(item.url, "end")}
                      disabled={adding === item.url}
                      className={`text-base w-9 h-9 rounded-xl transition-all font-bold flex items-center justify-center ${
                        addedId === item.url
                          ? "bg-emerald-600 text-white"
                          : "bg-violet-600 hover:bg-violet-500 text-white disabled:opacity-40"
                      }`}
                      title="加入隊列"
                    >
                      {adding === item.url ? (
                        <svg className="animate-spin w-3.5 h-3.5" viewBox="0 0 24 24" fill="none">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                        </svg>
                      ) : addedId === item.url ? "✓" : "+"}
                    </button>
                    <button
                      onClick={() => handleAdd(item.url, "next")}
                      disabled={adding === item.url}
                      title="插播"
                      className="text-[10px] w-9 h-6 rounded-lg bg-white/8 hover:bg-white/15 text-white/55 hover:text-white transition-colors disabled:opacity-40 font-medium"
                    >
                      插播
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
