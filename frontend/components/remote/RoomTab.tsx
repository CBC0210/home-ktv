"use client";

import type { Room, Guest, GuestSession } from "@/lib/types";
import type { RoomStats } from "@/lib/api";
import { useState, useEffect } from "react";
import Image from "next/image";
import { useKtvStore, type PlayerTheme } from "@/lib/stores";
import { getRoomStats } from "@/lib/api";

const THEMES: { id: PlayerTheme; label: string; preview: string }[] = [
  { id: "default", label: "預設暗色", preview: "bg-gray-900" },
  { id: "party", label: "派對", preview: "bg-gradient-to-r from-pink-800 to-purple-800" },
  { id: "elegant", label: "典雅", preview: "bg-slate-900" },
  { id: "retro", label: "復古", preview: "bg-amber-900" },
];

interface Props {
  room: Room;
  session: GuestSession;
  guests: Guest[];
  onLeave: () => void;
}

function formatDuration(sec: number | null): string {
  if (!sec) return "0m";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (h > 0) return `${h}小時${m}分`;
  return `${m}分`;
}

function RatingStars({ rating }: { rating: number }) {
  const full = Math.floor(rating);
  return (
    <span className="text-amber-400">
      {"★".repeat(full)}{"☆".repeat(Math.max(0, 5 - full))}
    </span>
  );
}

export default function RoomTab({ room, session, guests, onLeave }: Props) {
  const [copied, setCopied] = useState(false);
  const [stats, setStats] = useState<RoomStats | null>(null);
  const { theme, setTheme } = useKtvStore();

  const roomUrl =
    typeof window !== "undefined"
      ? `${window.location.origin}/r/${room.id}/remote`
      : `/r/${room.id}/remote`;

  function copyLink() {
    navigator.clipboard.writeText(roomUrl).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  // Load room stats
  useEffect(() => {
    getRoomStats(room.id)
      .then(setStats)
      .catch(() => {});
  }, [room.id]);

  return (
    <div className="p-4 flex flex-col gap-5">
      {/* Room info */}
      <div className="bg-gray-800 rounded-xl p-4">
        <h2 className="text-white font-semibold text-lg">{room.name}</h2>
        <p className="text-gray-400 text-sm font-mono mt-0.5">/{room.id}</p>

        <button
          onClick={copyLink}
          className="mt-3 w-full text-sm bg-gray-700 hover:bg-gray-600 text-white py-2 rounded-lg transition-colors"
        >
          {copied ? "✓ 已複製連結" : "複製房間連結"}
        </button>
      </div>

      {/* Current user */}
      <div className="bg-gray-800 rounded-xl p-4">
        <p className="text-gray-400 text-sm mb-2">你的身份</p>
        <div className="flex items-center gap-3">
          <div
            className="w-10 h-10 rounded-full flex items-center justify-center text-white font-bold text-sm"
            style={{ backgroundColor: session.guest.avatar_color ?? "#7c3aed" }}
          >
            {session.guest.nickname.slice(0, 1).toUpperCase()}
          </div>
          <div>
            <p className="text-white font-medium">{session.guest.nickname}</p>
            {session.guest.is_admin && (
              <p className="text-yellow-400 text-xs">管理員</p>
            )}
          </div>
        </div>
      </div>

      {/* Online guests */}
      <div className="bg-gray-800 rounded-xl p-4">
        <p className="text-gray-400 text-sm mb-3">
          在線用戶 ({guests.length})
        </p>
        <div className="flex flex-col gap-2">
          {guests.map((g) => (
            <div key={g.id} className="flex items-center gap-2">
              <div
                className="w-8 h-8 rounded-full flex items-center justify-center text-white text-xs font-bold"
                style={{ backgroundColor: g.avatar_color ?? "#7c3aed" }}
              >
                {g.nickname.slice(0, 1).toUpperCase()}
              </div>
              <span className="text-white text-sm">{g.nickname}</span>
              {g.is_admin && (
                <span className="text-yellow-400 text-xs">管理員</span>
              )}
              {g.id === session.guest.id && (
                <span className="text-gray-500 text-xs">(你)</span>
              )}
            </div>
          ))}
          {guests.length === 0 && (
            <p className="text-gray-500 text-sm">暫無其他用戶</p>
          )}
        </div>
      </div>

      {/* Stats */}
      {stats && (
        <div className="bg-gray-800 rounded-xl p-4">
          <p className="text-gray-400 text-sm mb-3">播放統計</p>
          <div className="grid grid-cols-3 gap-3 mb-4">
            <div className="bg-gray-700/50 rounded-lg px-3 py-2 text-center">
              <p className="text-white text-lg font-bold">{stats.total_songs_played}</p>
              <p className="text-gray-500 text-xs">已唱</p>
            </div>
            <div className="bg-gray-700/50 rounded-lg px-3 py-2 text-center">
              <p className="text-white text-lg font-bold">{stats.unique_songs}</p>
              <p className="text-gray-500 text-xs">不重複</p>
            </div>
            <div className="bg-gray-700/50 rounded-lg px-3 py-2 text-center">
              <p className="text-white text-lg font-bold">{formatDuration(stats.total_play_duration_sec)}</p>
              <p className="text-gray-500 text-xs">總時長</p>
            </div>
          </div>

          {stats.avg_rating != null && (
            <div className="flex items-center gap-2 mb-3">
              <span className="text-gray-400 text-sm">平均評分</span>
              <RatingStars rating={stats.avg_rating} />
              <span className="text-gray-300 text-sm">{stats.avg_rating.toFixed(1)}</span>
            </div>
          )}

          {stats.top_songs.length > 0 && (
            <div>
              <p className="text-gray-400 text-xs mb-2">熱門歌曲</p>
              <div className="flex flex-col gap-1">
                {stats.top_songs.slice(0, 5).map((s, i) => (
                  <div key={s.song_id} className="flex items-center gap-2 text-xs">
                    <span className={`w-4 text-center font-bold ${i === 0 ? "text-amber-400" : "text-gray-600"}`}>
                      {i + 1}
                    </span>
                    <div className="relative w-7 h-5 rounded overflow-hidden bg-gray-700 flex-shrink-0">
                      {s.thumbnail_url ? (
                        <Image
                          src={s.thumbnail_url}
                          alt={s.title}
                          fill
                          className="object-cover"
                          unoptimized
                        />
                      ) : (
                        <span className="text-xs text-center w-full">🎵</span>
                      )}
                    </div>
                    <span className="text-gray-300 flex-1 truncate">{s.title}</span>
                    <span className="text-gray-500">{s.play_count}次</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Theme switcher */}
      <div className="bg-gray-800 rounded-xl p-4">
        <p className="text-gray-400 text-sm mb-3">Player 主題</p>
        <div className="grid grid-cols-2 gap-2">
          {THEMES.map((t) => (
            <button
              key={t.id}
              onClick={() => setTheme(t.id)}
              className={`flex items-center gap-2 rounded-lg px-3 py-2 text-sm transition-all ${
                theme === t.id
                  ? "ring-2 ring-purple-500 bg-gray-700 text-white"
                  : "bg-gray-700/50 text-gray-400 hover:text-white hover:bg-gray-700"
              }`}
            >
              <span className={`w-4 h-4 rounded-sm flex-shrink-0 ${t.preview}`} />
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {/* Leave */}
      <button
        onClick={onLeave}
        className="w-full text-sm text-gray-500 hover:text-red-400 py-2 transition-colors"
      >
        離開房間（清除身份）
      </button>
    </div>
  );
}