"use client";

import Image from "next/image";
import { useRef } from "react";
import type { Song, PlaybackState, ClientCommand, QueueItem } from "@/lib/types";

interface Props {
  currentSong: Song | null;
  currentQueueItem: QueueItem | null;
  playback: PlaybackState;
  processing: { stage: string; percent: number } | null;
  sendCommand: (cmd: ClientCommand) => void;
}

const STAGE_LABELS: Record<string, string> = {
  downloading: "下載中",
  separating: "分離人聲",
  fetching_lyrics: "抓取歌詞",
  aligning: "對齊字幕",
  packaging: "封裝 HLS",
};

function formatTime(sec: number): string {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export default function NowPlaying({
  currentSong,
  currentQueueItem,
  playback,
  processing,
  sendCommand,
}: Props) {
  const progressBarRef = useRef<HTMLDivElement>(null);

  function handleSeek(e: React.MouseEvent<HTMLDivElement>) {
    const bar = progressBarRef.current;
    if (!bar || !currentSong?.duration_sec) return;
    const rect = bar.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    sendCommand({ type: "playback.seek", positionSec: ratio * currentSong.duration_sec });
  }

  if (!currentSong && !processing) {
    return (
      <div className="flex flex-col items-center justify-center flex-1 text-center p-8 gap-4">
        <span className="text-6xl">🎵</span>
        <p className="text-gray-400 text-lg">目前沒有播放中的歌曲</p>
        <p className="text-gray-600 text-sm">前往搜尋頁面點歌吧！</p>
      </div>
    );
  }

  const duration = currentSong?.duration_sec ?? 0;
  const progress = duration > 0 ? (playback.position_sec / duration) * 100 : 0;

  return (
    <div className="flex flex-col p-4 gap-5">
      {/* Cover art */}
      <div className="flex justify-center">
        <div className="relative w-48 h-48 rounded-2xl overflow-hidden bg-gray-800">
          {currentSong?.thumbnail_url ? (
            <Image
              src={currentSong.thumbnail_url}
              alt={currentSong.title}
              fill
              className="object-cover"
              unoptimized
            />
          ) : (
            <div className="w-full h-full flex items-center justify-center text-5xl">
              🎵
            </div>
          )}
        </div>
      </div>

      {/* Song info */}
      <div className="text-center">
        <h2 className="text-white font-semibold text-lg line-clamp-2">
          {currentSong?.title ?? "處理中…"}
        </h2>
        {currentSong?.artist && (
          <p className="text-gray-400 text-sm mt-1">{currentSong.artist}</p>
        )}
        {currentQueueItem?.guest?.nickname && (
          <p className="text-purple-400 text-xs mt-1">
            {currentQueueItem.guest.nickname} 點的
          </p>
        )}
      </div>

      {/* Processing bar */}
      {processing && (
        <div className="bg-gray-800 rounded-xl p-4">
          <div className="flex justify-between text-sm mb-2">
            <span className="text-yellow-400">
              {STAGE_LABELS[processing.stage] ?? processing.stage}
            </span>
            <span className="text-gray-400">{processing.percent}%</span>
          </div>
          <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-yellow-500 transition-all"
              style={{ width: `${processing.percent}%` }}
            />
          </div>
        </div>
      )}

      {/* Progress bar — click to seek */}
      {currentSong && (
        <div>
          <div
            ref={progressBarRef}
            onClick={handleSeek}
            className="h-3 bg-gray-700 rounded-full overflow-hidden cursor-pointer active:opacity-80 group relative"
            title="點擊跳轉"
          >
            <div
              className="h-full bg-purple-500 rounded-full transition-all group-hover:bg-purple-400"
              style={{ width: `${progress}%` }}
            />
          </div>
          <div className="flex justify-between text-xs text-gray-500 mt-1">
            <span>{formatTime(playback.position_sec)}</span>
            <span>{formatTime(duration)}</span>
          </div>
        </div>
      )}

      {/* Controls */}
      <div className="flex items-center justify-center gap-6">
        <button
          onClick={() => sendCommand({ type: "playback.replay" })}
          className="text-gray-400 hover:text-white transition-colors text-2xl"
          title="重播"
        >
          ⏮
        </button>
        <button
          onClick={() =>
            sendCommand({
              type: playback.is_playing ? "playback.pause" : "playback.play",
            })
          }
          className="w-16 h-16 rounded-full bg-purple-600 hover:bg-purple-500 text-white text-3xl flex items-center justify-center transition-colors"
        >
          {playback.is_playing ? "⏸" : "▶"}
        </button>
        <button
          onClick={() => sendCommand({ type: "playback.skip" })}
          className="text-gray-400 hover:text-white transition-colors text-2xl"
          title="下一首"
        >
          ⏭
        </button>
      </div>

      {/* Volume controls */}
      <div className="bg-gray-800 rounded-xl p-4 flex flex-col gap-3">
        <div className="flex items-center gap-3">
          <span className="text-gray-400 text-sm w-16">主音量</span>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={playback.main_volume}
            onChange={(e) =>
              sendCommand({
                type: "playback.setVolume",
                main: parseFloat(e.target.value),
              })
            }
            className="flex-1 accent-purple-500"
          />
          <span className="text-gray-400 text-xs w-8 text-right">
            {Math.round(playback.main_volume * 100)}
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-gray-400 text-sm w-16">人聲</span>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={playback.vocal_volume}
            onChange={(e) =>
              sendCommand({
                type: "playback.setVolume",
                vocal: parseFloat(e.target.value),
              })
            }
            className="flex-1 accent-purple-500"
          />
          <span className="text-gray-400 text-xs w-8 text-right">
            {Math.round(playback.vocal_volume * 100)}
          </span>
        </div>
      </div>

      {/* Reactions */}
      <div className="flex justify-center gap-4">
        {["🔥", "👏", "😂", "❤️", "🎉"].map((emoji) => (
          <button
            key={emoji}
            onClick={() => sendCommand({ type: "reaction.send", emoji })}
            className="text-2xl hover:scale-125 transition-transform"
          >
            {emoji}
          </button>
        ))}
      </div>
    </div>
  );
}
