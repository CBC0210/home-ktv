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
    <div className="min-h-screen bg-gray-950 flex items-center justify-center p-6">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <span className="text-5xl">🎤</span>
          <h1 className="text-2xl font-bold text-white mt-3">加入房間</h1>
          <p className="text-gray-400 mt-1 font-mono text-sm">/{roomId}</p>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          {hasPassword && (
            <div>
              <label className="block text-sm text-gray-400 mb-1">
                房間密碼
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="輸入房間密碼"
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-3 text-white placeholder-gray-500 focus:outline-none focus:border-purple-500"
                required
              />
            </div>
          )}

          <div>
            <label className="block text-sm text-gray-400 mb-1">你的暱稱</label>
            <input
              type="text"
              value={nickname}
              onChange={(e) => setNickname(e.target.value)}
              placeholder="輸入暱稱"
              maxLength={20}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-4 py-3 text-white placeholder-gray-500 focus:outline-none focus:border-purple-500"
              required
            />
          </div>

          {error && (
            <p className="text-red-400 text-sm text-center">{error}</p>
          )}

          <button
            type="submit"
            disabled={loading || !nickname.trim()}
            className="w-full bg-purple-600 hover:bg-purple-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold py-3 rounded-lg transition-colors"
          >
            {loading ? "加入中…" : "進入房間"}
          </button>
        </form>
      </div>
    </div>
  );
}
