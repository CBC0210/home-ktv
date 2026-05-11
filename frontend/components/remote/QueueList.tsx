"use client";

import Image from "next/image";
import type { QueueItem, ClientCommand } from "@/lib/types";

interface Props {
  queue: QueueItem[];
  currentQueueItemId: number | null;
  sendCommand: (cmd: ClientCommand) => void;
}

const STATUS_LABELS: Record<string, string> = {
  pending: "等待中",
  downloading: "下載中",
  separating: "分離人聲",
  fetching_lyrics: "抓取歌詞",
  aligning: "對齊字幕",
  packaging: "封裝",
  ready: "就緒",
  failed_temp: "暫時失敗",
  failed_perm: "⚠ 失敗",
  playing: "播放中",
};

export default function QueueList({
  queue,
  currentQueueItemId,
  sendCommand,
}: Props) {
  const pending = queue.filter(
    (q) => q.id !== currentQueueItemId && q.status !== "playing"
  );

  if (pending.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center flex-1 text-center p-8 gap-4">
        <span className="text-5xl">📋</span>
        <p className="text-gray-400 text-lg">隊列是空的</p>
        <p className="text-gray-600 text-sm">前往搜尋頁面加入歌曲</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col divide-y divide-gray-800">
      <div className="flex items-center justify-between px-4 py-2">
        <span className="text-gray-400 text-sm">{pending.length} 首待播</span>
      </div>

      {pending.map((item, idx) => (
        <div key={item.id} className="flex items-center gap-3 px-4 py-3">
          <span className="text-gray-600 text-sm w-5 text-center">
            {idx + 1}
          </span>

          {/* Thumbnail */}
          <div className="relative w-12 h-12 rounded-lg overflow-hidden bg-gray-800 flex-shrink-0">
            {item.song?.thumbnail_url ? (
              <Image
                src={item.song.thumbnail_url}
                alt={item.song.title}
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

          {/* Song info */}
          <div className="flex-1 min-w-0">
            <p className="text-white text-sm truncate">
              {item.song?.title ?? item.song_id}
            </p>
            <div className="flex items-center gap-2 mt-0.5">
              {item.guest?.nickname && (
                <span className="text-purple-400 text-xs">
                  {item.guest.nickname}
                </span>
              )}
              {item.status !== "ready" && (
                <span
                  className={`text-xs ${item.status.startsWith("failed") ? "text-red-400" : "text-yellow-400"}`}
                >
                  {STATUS_LABELS[item.status] ?? item.status}
                </span>
              )}
            </div>
          </div>

          {/* Actions */}
          <div className="flex gap-1">
            <button
              onClick={() =>
                sendCommand({ type: "queue.remove", queueItemId: item.id })
              }
              className="text-gray-600 hover:text-red-400 transition-colors p-1"
              title="從隊列移除"
            >
              ✕
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}
