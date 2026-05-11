"use client";

import type { Room, Guest, GuestSession } from "@/lib/types";
import { useState } from "react";

interface Props {
  room: Room;
  session: GuestSession;
  guests: Guest[];
  onLeave: () => void;
}

export default function RoomTab({ room, session, guests, onLeave }: Props) {
  const [copied, setCopied] = useState(false);

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
