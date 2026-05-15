"use client";

import { useState, useEffect } from "react";
import { useKtvStore, type PlayerTheme } from "@/lib/stores";
import { getRoomStats, getProcessingStats, type RoomStats, type ProcessingStats } from "@/lib/api";

// Recharts lazy import
import { PieChart, Pie, Cell, Tooltip as ReTooltip, BarChart, Bar, XAxis, YAxis, Cell as BarCell } from "recharts";

const THEMES: { id: PlayerTheme; label: string; preview: string }[] = [
  { id: "default", label: "預設暗色", preview: "bg-gray-900" },
  { id: "party", label: "派對", preview: "bg-gradient-to-r from-pink-800 to-purple-800" },
  { id: "elegant", label: "典雅", preview: "bg-slate-900" },
  { id: "retro", label: "復古", preview: "bg-amber-900" },
];

interface Props {
  room: { id: string; name: string; has_password: boolean };
  session: {
    guest: { id: string; nickname: string; avatar_color: string | null; is_admin: boolean };
    token: string;
  };
  guests: Array<{ id: string; nickname: string; avatar_color: string | null; is_admin: boolean }>;
  onLeave: () => void;
  adminMode?: boolean;
  onKick?: (guestId: string) => void;
}

// ── Sub-components ────────────────────────────────────────────────────────────

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="bg-gray-800 rounded-xl p-3 text-center">
      <p className="text-xl font-bold text-white">{value}</p>
      <p className="text-xs text-gray-400 mt-0.5">{label}</p>
    </div>
  );
}

// ── Processing Pie Chart ──────────────────────────────────────────────────────
function ProcessingPieChart({ data }: { data: ProcessingStats }) {
  const COLORS = ["#6b7280", "#f59e0b", "#10b981", "#ef4444"];

  const chartData = [
    { name: "待處理", value: data.pending, color: COLORS[0] },
    { name: "處理中", value: data.processing, color: COLORS[1] },
    { name: "已完成", value: data.ready, color: COLORS[2] },
    { name: "失敗", value: data.failed_perm + data.failed_temp, color: COLORS[3] },
  ].filter((d) => d.value > 0);

  if (chartData.length === 0) {
    return (
      <div className="bg-gray-800 rounded-xl p-4">
        <p className="text-gray-400 text-sm mb-3">處理狀態</p>
        <p className="text-gray-500 text-sm text-center py-6">尚無歌曲</p>
      </div>
    );
  }

  return (
    <div className="bg-gray-800 rounded-xl p-4">
      <p className="text-gray-400 text-sm mb-3">處理狀態</p>
      <div className="flex items-center gap-4">
        <PieChart width={100} height={100}>
          <Pie
            data={chartData}
            cx={50}
            cy={50}
            innerRadius={28}
            outerRadius={42}
            dataKey="value"
            strokeWidth={2}
          >
            {chartData.map((_, i) => (
              <Cell key={`cell-${i}`} fill={COLORS[i]} />
            ))}
          </Pie>
          <ReTooltip
            formatter={(value) => [String(value), "歌曲數"]}
            contentStyle={{ background: "#1f2937", border: "none", borderRadius: "8px", color: "#fff", fontSize: "12px" }}
          />
        </PieChart>
        <div className="flex flex-col gap-1.5">
          {chartData.map((d) => (
            <div key={d.name} className="flex items-center gap-2 text-xs">
              <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: d.color }} />
              <span className="text-gray-400">{d.name}</span>
              <span className="text-white font-medium ml-auto pl-2">{d.value}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Top Songs Bar Chart ──────────────────────────────────────────────────────
function TopSongsChart({ songs }: { songs: RoomStats["top_songs"] }) {
  if (!songs || songs.length === 0) {
    return (
      <div className="bg-gray-800 rounded-xl p-4">
        <p className="text-gray-400 text-sm mb-3">熱門歌曲</p>
        <p className="text-gray-500 text-sm text-center py-6">尚無播放記錄</p>
      </div>
    );
  }

  const chartData = songs.slice(0, 5).map((s) => ({
    name: s.title.length > 12 ? s.title.slice(0, 12) + "…" : s.title,
    play_count: s.play_count,
  }));

  const GRADIENT_COLORS = ["#a78bfa", "#8b5cf6", "#7c3aed", "#6d28d9", "#5b21b6"];

  return (
    <div className="bg-gray-800 rounded-xl p-4">
      <p className="text-gray-400 text-sm mb-3">熱門歌曲（播放次數）</p>
      <BarChart
        layout="vertical"
        width={260}
        height={songs.slice(0, 5).length * 36 + 20}
        data={chartData}
        margin={{ left: 0, right: 8 }}
      >
        <XAxis type="number" hide />
        <YAxis
          type="category"
          dataKey="name"
          tick={{ fill: "#9ca3af", fontSize: 11 }}
          width={100}
          axisLine={false}
          tickLine={false}
        />
        <ReTooltip
          formatter={(value) => [`${value} 次`, "播放"]}
          contentStyle={{ background: "#1f2937", border: "none", borderRadius: "8px", color: "#fff", fontSize: "12px" }}
          cursor={{ fill: "rgba(255,255,255,0.05)" }}
        />
        <Bar dataKey="play_count" radius={[0, 4, 4, 0]} maxBarSize={18}>
          {[0, 1, 2, 3, 4].map((i) => (
            <BarCell key={`cell-${i}`} fill={GRADIENT_COLORS[i]} />
          ))}
        </Bar>
      </BarChart>
    </div>
  );
}

// ── Total Plays Stats ─────────────────────────────────────────────────────────
function TotalPlaysCard({ stats }: { stats: RoomStats }) {
  const hours = Math.round((stats.total_play_duration_sec || 0) / 3600);
  return (
    <div className="bg-gray-800 rounded-xl p-4">
      <p className="text-gray-400 text-sm mb-3">播放統計</p>
      <div className="grid grid-cols-3 gap-2">
        <StatCard label="總播放次數" value={stats.total_songs_played || 0} />
        <StatCard label="不同歌曲" value={stats.unique_songs || 0} />
        <StatCard label="總時長" value={`${hours}h`} />
      </div>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export default function RoomTab({ room, session, guests, onLeave, adminMode = false, onKick }: Props) {
  const [copied, setCopied] = useState(false);
  const { theme, setTheme } = useKtvStore();
  const [stats, setStats] = useState<RoomStats | null>(null);
  const [procStats, setProcStats] = useState<ProcessingStats | null>(null);
  const [loadingStats, setLoadingStats] = useState(false);

  const roomUrl =
    typeof window !== "undefined"
      ? `${window.location.origin}/r/${room.id}/remote`
      : `/r/${room.id}/remote`;

  useEffect(() => {
    let cancelled = false;
    setLoadingStats(true);
    Promise.all([getRoomStats(room.id), getProcessingStats(room.id)])
      .then(([s, p]) => {
        if (!cancelled) {
          setStats(s);
          setProcStats(p);
        }
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoadingStats(false);
      });
    return () => { cancelled = true; };
  }, [room.id]);

  function copyLink() {
    navigator.clipboard.writeText(roomUrl).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

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

      {/* Processing pie chart */}
      {procStats !== null && <ProcessingPieChart data={procStats} />}

      {/* Stats loading skeleton */}
      {loadingStats && (
        <div className="bg-gray-800 rounded-xl p-4">
          <p className="text-gray-400 text-sm mb-2">載入統計中…</p>
          <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
            <div className="h-full bg-purple-500 rounded-full animate-pulse w-1/3" />
          </div>
        </div>
      )}

      {/* Total plays */}
      {stats !== null && !loadingStats && <TotalPlaysCard stats={stats} />}

      {/* Top songs chart */}
      {stats !== null && !loadingStats && (
        <TopSongsChart songs={stats.top_songs ?? []} />
      )}

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
              {adminMode && g.id !== session.guest.id && (
                <button
                  onClick={() => {
                    if (confirm(`將 ${g.nickname} 踢出房間？`)) onKick?.(g.id);
                  }}
                  className="ml-auto text-rose-400/70 hover:text-rose-300 text-xs px-2 py-1 rounded-lg hover:bg-rose-500/10 transition-colors"
                  title="踢出"
                >
                  踢出
                </button>
              )}
            </div>
          ))}
          {guests.length === 0 && (
            <p className="text-gray-500 text-sm">暫無其他用戶</p>
          )}
        </div>
      </div>

      {/* Leave */}
      <button
        onClick={onLeave}
        className="w-full text-sm text-gray-500 hover:text-red-400 py-2 transition-colors"
      >
        離開房間（清除身份）
      </button>

      {/* Credit */}
      <div className="text-center pt-4 pb-2 border-t border-white/5 mt-2">
        <p className="text-white/40 text-xs font-medium tracking-wide">響窩 Echonest</p>
        <p className="text-white/25 text-[11px] mt-1">
          由 CBC 製作 ·{" "}
          <a
            href="https://github.com/CBC0210/home-ktv"
            target="_blank"
            rel="noopener noreferrer"
            className="underline hover:text-violet-400 transition-colors"
          >
            GitHub
          </a>
        </p>
      </div>
    </div>
  );
}