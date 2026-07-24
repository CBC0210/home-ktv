"use client";

import { useState } from "react";
import Image from "next/image";
import type { QueueItem, ClientCommand } from "@/lib/types";
import { deleteSong } from "@/lib/api";

interface Props {
  queue: QueueItem[];
  currentQueueItemId: number | null;
  sendCommand: (cmd: ClientCommand) => void;
  adminMode?: boolean;
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

export default function QueueList({ queue, currentQueueItemId, sendCommand, adminMode = false }: Props) {
  const pending = queue.filter((q) => q.id !== currentQueueItemId && q.status !== "playing");
  const [draggingId, setDraggingId] = useState<number | null>(null);
  const [dragOverIdx, setDragOverIdx] = useState<number | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);

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

  function moveItem(fromIdx: number, toIdx: number) {
    if (fromIdx === toIdx) return;
    const reordered = [...pending];
    const [moved] = reordered.splice(fromIdx, 1);
    reordered.splice(toIdx, 0, moved);
    sendCommand({ type: "queue.reorder", queueItemIds: reordered.map((q) => q.id) });
  }

  async function handleDeleteSong(songId: string) {
    if (!confirm("確定要從資料庫永久刪除這首歌嗎？")) return;
    setDeleting(songId);
    try {
      await deleteSong(songId);
    } catch (err) {
      alert("刪除失敗：" + (err as Error).message);
    } finally {
      setDeleting(null);
    }
  }

  return (
    <div className="flex flex-col">
      {/* Header */}
      <div className="px-5 py-3 border-b border-white/6">
        <div className="flex items-center justify-between">
          <span className="text-white/50 text-sm font-medium">{pending.length} 首待播</span>
          {adminMode && (
            <span className="text-amber-300 text-[10px] uppercase tracking-wider font-bold">
              可拖曳排序 / 永久刪除
            </span>
          )}
        </div>
        {pending.length > 1 && (
          <p className="text-white/30 text-[11px] mt-1">
            🔁 同一人連續點的歌會自動錯開，輪流唱（手動拖曳排序後就不再自動調整）
          </p>
        )}
      </div>

      {/* Items */}
      <div className="divide-y divide-white/5">
        {pending.map((item, idx) => {
          const statusInfo = STATUS_LABELS[item.status] ?? { label: item.status, color: "text-white/40" };
          const isProcessing = !["ready", "pending", "failed_temp", "failed_perm"].includes(item.status);

          return (
            <div
              key={item.id}
              draggable={adminMode}
              onDragStart={() => adminMode && setDraggingId(item.id)}
              onDragEnd={() => { setDraggingId(null); setDragOverIdx(null); }}
              onDragOver={(e) => {
                if (!adminMode || draggingId === null) return;
                e.preventDefault();
                setDragOverIdx(idx);
              }}
              onDrop={(e) => {
                if (!adminMode || draggingId === null) return;
                e.preventDefault();
                const fromIdx = pending.findIndex((q) => q.id === draggingId);
                if (fromIdx !== -1) moveItem(fromIdx, idx);
                setDraggingId(null);
                setDragOverIdx(null);
              }}
              className={`flex items-center gap-3 px-4 py-3.5 hover:bg-white/3 transition-colors group ${
                adminMode ? "cursor-move" : ""
              } ${draggingId === item.id ? "opacity-40" : ""} ${
                dragOverIdx === idx && draggingId !== null && draggingId !== item.id
                  ? "border-t-2 border-amber-400"
                  : ""
              }`}
            >
              {/* Drag handle / position */}
              {adminMode ? (
                <svg viewBox="0 0 24 24" fill="currentColor" className="w-4 h-4 text-amber-400/60 flex-shrink-0">
                  <path d="M3 6h18v2H3V6zm0 5h18v2H3v-2zm0 5h18v2H3v-2z" />
                </svg>
              ) : (
                <span className="text-white/25 text-xs w-5 text-center flex-shrink-0 font-mono">
                  {idx + 1}
                </span>
              )}

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

              {/* Action buttons — admin only (guests can't delete others' songs) */}
              {adminMode && (
                <div className="flex items-center gap-1 flex-shrink-0">
                  <button
                    onClick={() => sendCommand({ type: "queue.remove", queueItemId: item.id })}
                    className="text-white/20 hover:text-red-400 transition-colors p-1.5 rounded-xl hover:bg-red-400/10"
                    title="從隊列移除"
                  >
                    <svg viewBox="0 0 24 24" fill="currentColor" className="w-4 h-4">
                      <path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z" />
                    </svg>
                  </button>
                  <button
                    onClick={() => handleDeleteSong(item.song_id)}
                    disabled={deleting === item.song_id}
                    className="text-amber-400/60 hover:text-amber-300 transition-colors p-1.5 rounded-xl hover:bg-amber-400/10 disabled:opacity-40"
                    title="從資料庫永久刪除（含媒體檔）"
                  >
                    <svg viewBox="0 0 24 24" fill="currentColor" className="w-4 h-4">
                      <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
                    </svg>
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
