"use client";

import { useState, useEffect, useCallback } from "react";
import Image from "next/image";
import { addSong, browseLibrary, type BankSong } from "@/lib/api";
import { useKtvStore } from "@/lib/stores";
import AddButtons from "./AddButtons";

interface Props {
  roomId: string;
  onAdded?: () => void;
}

const LANGS: { key: string; label: string }[] = [
  { key: "all", label: "全部" },
  { key: "zh", label: "華語" },
  { key: "en", label: "西洋" },
  { key: "tw", label: "台語" },
  { key: "ja", label: "日文" },
  { key: "ko", label: "韓文" },
  { key: "other", label: "其他" },
];

function fmtDur(sec: number | null): string {
  if (!sec) return "";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function SongBankView({ roomId, onAdded }: Props) {
  const [lang, setLang] = useState("all");
  const [q, setQ] = useState("");
  const [data, setData] = useState<{ total: number; counts: Record<string, number>; songs: BankSong[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState<string | null>(null);
  const [addedId, setAddedId] = useState<string | null>(null);
  const currentSong = useKtvStore((s) => s.currentSong);

  const load = useCallback(async (lg: string, query: string) => {
    setLoading(true);
    try {
      setData(await browseLibrary(lg, query, 200));
    } catch {
      setData({ total: 0, counts: {}, songs: [] });
    } finally {
      setLoading(false);
    }
  }, []);

  // Debounced reload on language / query change.
  useEffect(() => {
    const id = setTimeout(() => void load(lang, q), q ? 300 : 0);
    return () => clearTimeout(id);
  }, [lang, q, load]);

  async function handleAdd(song: BankSong, position: "end" | "next") {
    setAdding(song.id);
    // Nothing playing? A cached pick should jump ahead of anything still
    // processing and start immediately, not wait behind it.
    const pos = position === "end" && !currentSong ? "next" : position;
    try {
      await addSong({ youtube_url: song.id, room_id: roomId, position: pos });
      setAddedId(song.id);
      setTimeout(() => setAddedId(null), 2000);
      onAdded?.();
    } catch {
      /* ignore */
    } finally {
      setAdding(null);
    }
  }

  const counts = data?.counts ?? {};

  return (
    <div className="flex flex-col h-full">
      {/* Search within the bank */}
      <div className="p-3 sticky top-[49px] bg-[#0a0a0a]/95 backdrop-blur-md z-10">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="在曲庫中找歌名或歌手"
          className="w-full bg-white/6 border border-white/10 rounded-xl px-4 py-2.5 text-sm text-white placeholder-white/30 outline-none focus:border-violet-500/50"
        />
        {/* Language chips */}
        <div className="flex gap-1.5 mt-2.5 overflow-x-auto pb-1 -mx-1 px-1">
          {LANGS.map((l) => {
            const c = l.key === "all"
              ? Object.values(counts).reduce((a, b) => a + b, 0)
              : counts[l.key] ?? 0;
            if (l.key !== "all" && l.key !== lang && c === 0) return null;
            return (
              <button
                key={l.key}
                onClick={() => setLang(l.key)}
                className={`flex-shrink-0 text-xs px-3 py-1.5 rounded-full transition-colors ${
                  lang === l.key
                    ? "bg-violet-600 text-white"
                    : "bg-white/8 text-white/55 hover:bg-white/15"
                }`}
              >
                {l.label}<span className="opacity-50 ml-1">{c}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto px-3 pb-4">
        {loading ? (
          <p className="text-white/40 text-sm text-center py-10">載入中…</p>
        ) : !data || data.songs.length === 0 ? (
          <p className="text-white/40 text-sm text-center py-10">
            這個分類還沒有已快取的歌曲<br />
            <span className="text-white/25 text-xs">（管理員可在後台「預裝歌單」批次預載）</span>
          </p>
        ) : (
          <div className="flex flex-col gap-1.5">
            {data.songs.map((s) => (
              <div
                key={s.id}
                className="flex items-center gap-3 bg-white/4 border border-white/8 rounded-xl p-2"
              >
                <div className="relative w-14 h-14 flex-shrink-0 rounded-lg overflow-hidden bg-white/5">
                  {s.thumbnail_url && (
                    <Image src={s.thumbnail_url} alt="" fill className="object-cover" unoptimized />
                  )}
                  <span className="absolute bottom-0 right-0 bg-black/70 text-[10px] text-white px-1 rounded-tl">
                    ⚡{fmtDur(s.duration_sec)}
                  </span>
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-white text-sm leading-snug line-clamp-2 break-words">{s.title}</p>
                  <p className="text-white/45 text-xs truncate mt-0.5">
                    {s.artist || "—"}{s.has_timing ? " · 有字幕" : ""}
                  </p>
                </div>
                <AddButtons
                  adding={adding === s.id}
                  added={addedId === s.id}
                  onAdd={(pos) => handleAdd(s, pos)}
                />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
