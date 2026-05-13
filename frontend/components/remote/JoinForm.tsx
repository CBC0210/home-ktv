"use client";

import { useState } from "react";
import { joinRoom } from "@/lib/api";
import type { GuestSession } from "@/lib/types";

interface Props {
  roomId: string;
  hasPassword: boolean;
  onJoined: (session: GuestSession) => void;
}

export default function JoinForm({ roomId, hasPassword, onJoined }: Props) {
  const [nickname, setNickname] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!nickname.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const { guest, token } = await joinRoom({
        room_id: roomId,
        nickname: nickname.trim(),
        password: hasPassword ? password : undefined,
      });
      const session: GuestSession = { guest, token, roomId };
      localStorage.setItem(`ktv_session_${roomId}`, JSON.stringify(session));
      onJoined(session);
    } catch {
      setError(hasPassword ? "密碼錯誤或無法加入，請重試" : "無法加入，請重試");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="relative min-h-screen bg-[#0a0a0a] flex items-center justify-center p-6 overflow-hidden">
      {/* Background glow orbs */}
      <div className="absolute top-1/4 left-1/2 -translate-x-1/2 w-96 h-96 bg-violet-600/20 rounded-full blur-3xl animate-pulse-glow pointer-events-none" />
      <div className="absolute bottom-1/4 left-1/4 w-64 h-64 bg-purple-800/15 rounded-full blur-3xl animate-pulse-glow pointer-events-none" style={{ animationDelay: "1.5s" }} />

      <div className="relative w-full max-w-sm">
        {/* Logo */}
        <div className="flex flex-col items-center mb-10">
          <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-violet-500 to-purple-700 flex items-center justify-center shadow-lg shadow-violet-900/50 mb-4 animate-float">
            <svg viewBox="0 0 24 24" fill="white" className="w-10 h-10">
              <path d="M12 3a9 9 0 110 18A9 9 0 0112 3zm0 2a7 7 0 100 14A7 7 0 0012 5zm0 3a4 4 0 110 8 4 4 0 010-8zm0 2a2 2 0 100 4 2 2 0 000-4z"/>
              <circle cx="12" cy="12" r="1.5" fill="white"/>
            </svg>
          </div>
          <h1 className="text-white text-2xl font-bold tracking-tight">Home KTV</h1>
          <p className="text-white/40 text-sm mt-1 font-mono">/{roomId}</p>
        </div>

        {/* Card */}
        <div className="bg-white/5 backdrop-blur-xl border border-white/10 rounded-3xl p-6 shadow-2xl">
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            {hasPassword && (
              <div className="flex flex-col gap-1.5">
                <label className="text-white/50 text-xs font-medium uppercase tracking-wider pl-1">
                  房間密碼
                </label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="輸入房間密碼"
                  className="w-full bg-white/8 border border-white/10 rounded-2xl px-4 py-3.5 text-white placeholder-white/25 focus:outline-none focus:border-violet-500/60 focus:bg-white/10 transition-all text-sm"
                  required
                />
              </div>
            )}

            <div className="flex flex-col gap-1.5">
              <label className="text-white/50 text-xs font-medium uppercase tracking-wider pl-1">
                你的暱稱
              </label>
              <input
                type="text"
                value={nickname}
                onChange={(e) => setNickname(e.target.value)}
                placeholder="輸入暱稱"
                maxLength={20}
                className="w-full bg-white/8 border border-white/10 rounded-2xl px-4 py-3.5 text-white placeholder-white/25 focus:outline-none focus:border-violet-500/60 focus:bg-white/10 transition-all text-sm"
                required
                autoFocus
              />
            </div>

            {error && (
              <p className="text-red-400 text-sm text-center bg-red-500/10 rounded-xl py-2.5 border border-red-500/20">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={loading || !nickname.trim()}
              className="w-full bg-gradient-to-r from-violet-600 to-purple-600 hover:from-violet-500 hover:to-purple-500 disabled:opacity-40 disabled:cursor-not-allowed text-white font-semibold py-3.5 rounded-2xl transition-all shadow-lg shadow-violet-900/40 active:scale-[0.98] mt-1"
            >
              {loading ? (
                <span className="flex items-center justify-center gap-2">
                  <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                  </svg>
                  加入中…
                </span>
              ) : "進入房間"}
            </button>
          </form>
        </div>

        <p className="text-center text-white/20 text-xs mt-6">Home KTV · 家庭卡拉 OK 系統</p>
      </div>
    </div>
  );
}
