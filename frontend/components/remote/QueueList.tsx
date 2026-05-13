"use client";

import Image from "next/image";
import type { QueueItem, ClientCommand } from "@/lib/types";

interface Props {
  queue: QueueItem[];
  currentQueueItemId: number | null;
  sendCommand: (cmd: ClientCommand) => void;
}

const STATUS_LABELS: Record<string, { label: string; color: string }> = {
  pending:        { label: "等待中",   color: "text-white/40" },
  downloading:    { label: "下載中",   color: "text-amber-400" },
  separating:     { label: "分離人聲", color: "text-amber-400" },
  fetching_lyrics:{ label: "抓取歌詞", color: "text-amber-400" },
  aligning:       { label: "對齊字幕", color: "text-amber-400" },
  packaging:      { label: "封裝",     color: "text-amber-400" },
  ready:          { label: "就緒",     color: "text-emerald-400" },
  failed_temp:    { label: "暫時失敗", color: "text-red-400" },
  failed_perm:    { label: "無法處理", color: "text-red-400" },
  playing:        { label: "播放中",   color: "text-violet-400" },
};

export default function QueueList({ queue, currentQueueItemId, sendCommand }: Props) {
  const pending = queue.filter((q) => q.id !== currentQueueItemId && q.status !== "playing");

  if (pending.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] text-center p-8 gap-5">
        <div className="w-24 h-24 rounded-full bg-white/5 flex items-center justify-center">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="w-10 h-10 text-white/25">
            <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 12h16.5m-16.5 3.75h16.5M3.75 19.5h16.5M5.625 4.5h12.75a1.875 1.875 0 010 3.75H5.625a1.875 1.875 0 010-3.75z" />
          </svg>
        </div>
        <div>
          <p className="text-white/50 font-medium">隊列是空的</p>
          <p className="text-white/25 text-sm mt-1">前往搜尋頁面加入歌曲</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3.5 border-b border-white/6">
        <span className="text-white/50 text-sm font-medium">{pending.length} 首待播</span>
      </div>

      {/* Items */}
      <div className="divide-y divide-white/5">
        {pending.map((item, idx) => {
          const statusInfo = STATUS_LABELS[item.status] ?? { label: item.status, color: "text-white/40" };
          const isProcessing = !["ready", "pending", "failed_temp", "failed_perm"].includes(item.status);

          return (
            <div key={item.id} className="flex items-center gap-3 px-4 py-3.5 hover:bg-white/3 transition-colors group">
              {/* Position number */}
              <span className="text-white/25 text-xs w-5 text-center flex-shrink-0 font-mono">
                {idx + 1}
              </span>

              {/* Thumbnail */}
              <div className="relative w-12 h-12 rounded-xl overflow-hidden bg-white/8 flex-shrink-0">
                {item.song?.thumbnail_url ? (
                  <Image
                    src={item.song.thumbnail_url}
                    alt={item.song.title}
                    fill
                    className="object-cover"
                    unoptimized
                  />
                ) : (
                  <div className="w-full h-full flex items-center justify-center">
                    <svg viewBox="0 0 24 24" fill="currentColor" className="w-5 h-5 text-white/20">
                      <path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z" />
                    </svg>
                  </div>
                )}
                {isProcessing && (
                  <div className="absolute inset-0 bg-black/50 flex items-center justify-center">
                    <div className="w-4 h-4 border-2 border-amber-400 border-t-transparent rounded-full animate-spin" />
                  </div>
                )}
              </div>

              {/* Song info */}
              <div className="flex-1 min-w-0">
                <p className="text-white text-sm truncate font-medium leading-tight">
                  {item.song?.title ?? item.song_id}
                </p>
                <div className="flex items-center gap-2 mt-0.5">
                  {item.guest?.nickname && (
                    <span className="text-violet-400 text-xs">{item.guest.nickname}</span>
                  )}
                  {item.status !== "ready" && item.status !== "pending" && (
                    <span className={`text-xs ${statusInfo.color}`}>
                      {statusInfo.label}
                    </span>
                  )}
                </div>
              </div>

              {/* Remove button */}
              <button
                onClick={() => sendCommand({ type: "queue.remove", queueItemId: item.id })}
                className="text-white/20 hover:text-red-400 transition-colors p-1.5 rounded-xl hover:bg-red-400/10 opacity-0 group-hover:opacity-100"
                title="移除"
              >
                <svg viewBox="0 0 24 24" fill="currentColor" className="w-4 h-4">
                  <path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z" />
                </svg>
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
