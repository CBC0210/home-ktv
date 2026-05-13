"use client";

import Image from "next/image";
import { useRef, useState, useCallback } from "react";
import type { Song, PlaybackState, ClientCommand, QueueItem } from "@/lib/types";
import { getLyricsAss } from "@/lib/api";

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

function IconPlay() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className="w-7 h-7 ml-0.5">
      <path d="M8 5v14l11-7z" />
    </svg>
  );
}
function IconPause() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className="w-7 h-7">
      <path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z" />
    </svg>
  );
}
function IconSkipNext() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className="w-6 h-6">
      <path d="M6 18l8.5-6L6 6v12zm2-8.14L11.03 12 8 14.14V9.86zM16 6h2v12h-2z" />
    </svg>
  );
}
function IconReplay() {
  return (
    <svg viewBox="0 0 24 24" fill="currentColor" className="w-6 h-6">
      <path d="M12 5V1L7 6l5 5V7c3.31 0 6 2.69 6 6s-2.69 6-6 6-6-2.69-6-6H4c0 4.42 3.58 8 8 8s8-3.58 8-8-3.58-8-8-8z" />
    </svg>
  );
}

export default function NowPlaying({
  currentSong,
  currentQueueItem,
  playback,
  processing,
  sendCommand,
}: Props) {
  const progressBarRef = useRef<HTMLDivElement>(null);
  const [lyricsEditorOpen, setLyricsEditorOpen] = useState(false);
  const [assContent, setAssContent] = useState("");
  const [lyricsLoading, setLyricsLoading] = useState(false);
  const [lyricsSaving, setLyricsSaving] = useState(false);

  const openLyricsEditor = useCallback(async () => {
    if (!currentSong) return;
    setLyricsLoading(true);
    setLyricsEditorOpen(true);
    try {
      const content = await getLyricsAss(currentSong.id);
      setAssContent(content);
    } finally {
      setLyricsLoading(false);
    }
  }, [currentSong]);

  function saveLyrics() {
    if (!currentSong || !assContent.trim()) return;
    setLyricsSaving(true);
    sendCommand({ type: "lyrics.edit", songId: currentSong.id, ass: assContent });
    setTimeout(() => {
      setLyricsSaving(false);
      setLyricsEditorOpen(false);
    }, 800);
  }

  function handleSeek(e: React.MouseEvent<HTMLDivElement>) {
    const bar = progressBarRef.current;
    if (!bar || !currentSong?.duration_sec) return;
    const rect = bar.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    sendCommand({ type: "playback.seek", positionSec: ratio * currentSong.duration_sec });
  }

  // ── Empty state ──────────────────────────────────────────────────────────────
  if (!currentSong && !processing) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] text-center p-8 gap-5">
        <div className="w-24 h-24 rounded-full bg-white/5 flex items-center justify-center">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="w-10 h-10 text-white/30">
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 9l10.5-3m0 6.553v3.75a2.25 2.25 0 01-1.632 2.163l-1.32.377a1.803 1.803 0 01-.99-3.467l2.31-.66a2.25 2.25 0 001.632-2.163zm0 0V2.25L9 5.25v10.303m0 0v3.75a2.25 2.25 0 01-1.632 2.163l-1.32.377a1.803 1.803 0 01-.99-3.467l2.31-.66A2.25 2.25 0 009 15.553z" />
          </svg>
        </div>
        <div>
          <p className="text-white/60 text-lg font-medium">目前沒有播放</p>
          <p className="text-white/30 text-sm mt-1">前往搜尋頁面點歌吧</p>
        </div>
      </div>
    );
  }

  const duration = currentSong?.duration_sec ?? 0;
  const progress = duration > 0 ? (playback.position_sec / duration) * 100 : 0;
  const thumbUrl = currentSong?.thumbnail_url;

  return (
    <div className="relative flex flex-col min-h-screen overflow-hidden">
      {/* Blurred album art background */}
      {thumbUrl && (
        <div className="absolute inset-0 z-0">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={thumbUrl}
            alt=""
            aria-hidden
            className="w-full h-full object-cover scale-110"
            style={{ filter: "blur(40px) saturate(1.4) brightness(0.35)" }}
          />
          <div className="absolute inset-0 bg-gradient-to-b from-black/20 via-black/50 to-black/90" />
        </div>
      )}
      {!thumbUrl && (
        <div className="absolute inset-0 z-0 bg-gradient-to-b from-violet-950/50 to-[#0a0a0a]" />
      )}

      {/* Content */}
      <div className="relative z-10 flex flex-col gap-6 px-6 pt-8 pb-6">
        {/* Album art */}
        <div className="flex justify-center">
          <div className="relative w-64 h-64 rounded-2xl overflow-hidden shadow-2xl shadow-black/70 ring-1 ring-white/10">
            {thumbUrl ? (
              <Image
                src={thumbUrl}
                alt={currentSong?.title ?? ""}
                fill
                className="object-cover"
                unoptimized
              />
            ) : (
              <div className="w-full h-full bg-white/5 flex items-center justify-center">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1" className="w-20 h-20 text-white/20">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 9l10.5-3m0 6.553v3.75a2.25 2.25 0 01-1.632 2.163l-1.32.377a1.803 1.803 0 01-.99-3.467l2.31-.66a2.25 2.25 0 001.632-2.163zm0 0V2.25L9 5.25v10.303m0 0v3.75a2.25 2.25 0 01-1.632 2.163l-1.32.377a1.803 1.803 0 01-.99-3.467l2.31-.66A2.25 2.25 0 009 15.553z" />
                </svg>
              </div>
            )}
          </div>
        </div>

        {/* Song info */}
        <div className="text-center">
          <h2 className="text-white font-bold text-xl leading-tight line-clamp-2">
            {currentSong?.title ?? "處理中…"}
          </h2>
          {currentSong?.artist && (
            <p className="text-white/60 text-sm mt-1">{currentSong.artist}</p>
          )}
          {currentQueueItem?.guest?.nickname && (
            <p className="text-violet-400 text-xs mt-1.5 font-medium">
              ♪ {currentQueueItem.guest.nickname} 點的
            </p>
          )}
        </div>

        {/* Processing bar */}
        {processing && (
          <div className="bg-white/8 backdrop-blur rounded-2xl p-4 border border-white/10">
            <div className="flex justify-between text-sm mb-2.5">
              <span className="text-amber-400 font-medium">
                {STAGE_LABELS[processing.stage] ?? processing.stage}
              </span>
              <span className="text-white/50">{processing.percent}%</span>
            </div>
            <div className="h-1.5 bg-white/10 rounded-full overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-violet-500 to-purple-400 rounded-full transition-all duration-300"
                style={{ width: `${processing.percent}%` }}
              />
            </div>
          </div>
        )}

        {/* Progress bar */}
        {currentSong && (
          <div className="flex flex-col gap-1">
            <div
              ref={progressBarRef}
              onClick={handleSeek}
              className="relative h-1.5 bg-white/15 rounded-full cursor-pointer group"
            >
              <div
                className="h-full bg-white rounded-full relative transition-all"
                style={{ width: `${progress}%` }}
              >
                <div className="absolute right-0 top-1/2 -translate-y-1/2 translate-x-1/2 w-3.5 h-3.5 bg-white rounded-full shadow-md opacity-0 group-hover:opacity-100 transition-opacity" />
              </div>
            </div>
            <div className="flex justify-between text-xs text-white/40 px-0.5">
              <span>{formatTime(playback.position_sec)}</span>
              <span>{formatTime(duration)}</span>
            </div>
          </div>
        )}

        {/* Playback controls */}
        <div className="flex items-center justify-center gap-8">
          <button
            onClick={() => sendCommand({ type: "playback.replay" })}
            className="text-white/50 hover:text-white transition-colors active:scale-90 p-2"
          >
            <IconReplay />
          </button>

          <button
            onClick={() =>
              sendCommand({
                type: playback.is_playing ? "playback.pause" : "playback.play",
              })
            }
            className="w-16 h-16 rounded-full bg-white flex items-center justify-center text-black shadow-xl hover:scale-105 active:scale-95 transition-transform"
          >
            {playback.is_playing ? <IconPause /> : <IconPlay />}
          </button>

          <button
            onClick={() => sendCommand({ type: "playback.skip" })}
            className="text-white/50 hover:text-white transition-colors active:scale-90 p-2"
          >
            <IconSkipNext />
          </button>
        </div>

        {/* Volume controls */}
        <div className="flex flex-col gap-4 px-1">
          <div className="flex items-center gap-3">
            <svg viewBox="0 0 24 24" fill="currentColor" className="w-4 h-4 text-white/40 flex-shrink-0">
              <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02z"/>
            </svg>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={playback.main_volume}
              onChange={(e) =>
                sendCommand({ type: "playback.setVolume", main: parseFloat(e.target.value) })
              }
              className="flex-1"
            />
            <svg viewBox="0 0 24 24" fill="currentColor" className="w-4 h-4 text-white/40 flex-shrink-0">
              <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/>
            </svg>
          </div>
          <div className="flex items-center gap-3">
            <svg viewBox="0 0 24 24" fill="currentColor" className="w-4 h-4 text-violet-400/60 flex-shrink-0">
              <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 14.5v-9l6 4.5-6 4.5z"/>
            </svg>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={playback.vocal_volume}
              onChange={(e) =>
                sendCommand({ type: "playback.setVolume", vocal: parseFloat(e.target.value) })
              }
              className="flex-1"
              style={{ background: `linear-gradient(to right, #7c3aed ${playback.vocal_volume * 100}%, rgba(255,255,255,0.15) ${playback.vocal_volume * 100}%)` }}
            />
            <span className="text-white/30 text-xs w-6 text-right flex-shrink-0">
              人聲
            </span>
          </div>
        </div>

        {/* Reactions */}
        <div className="flex justify-around px-4">
          {["🔥", "👏", "😂", "❤️", "🎉"].map((emoji) => (
            <button
              key={emoji}
              onClick={() => sendCommand({ type: "reaction.send", emoji })}
              className="text-2xl hover:scale-125 active:scale-110 transition-transform p-2"
            >
              {emoji}
            </button>
          ))}
        </div>

        {/* Lyrics edit */}
        {currentSong?.has_timing && (
          <button
            onClick={openLyricsEditor}
            className="text-xs text-white/25 hover:text-white/50 py-1 transition-colors text-center"
          >
            ✏️ 編輯歌詞時間軸
          </button>
        )}
      </div>

      {/* Lyrics editor modal */}
      {lyricsEditorOpen && (
        <div className="fixed inset-0 bg-black/90 z-50 flex flex-col">
          <div className="flex items-center justify-between px-5 py-4 border-b border-white/10">
            <h3 className="text-white font-semibold text-sm">編輯 ASS 時間軸</h3>
            <button
              onClick={() => setLyricsEditorOpen(false)}
              className="text-white/50 hover:text-white w-8 h-8 flex items-center justify-center rounded-full hover:bg-white/10 transition-all"
            >
              ✕
            </button>
          </div>
          <div className="flex-1 overflow-hidden flex flex-col p-4 gap-3">
            {lyricsLoading ? (
              <div className="flex-1 flex items-center justify-center">
                <p className="text-white/40 text-sm">載入歌詞中…</p>
              </div>
            ) : (
              <textarea
                value={assContent}
                onChange={(e) => setAssContent(e.target.value)}
                className="flex-1 bg-white/5 text-white text-xs font-mono p-4 rounded-2xl resize-none outline-none border border-white/10 focus:border-violet-500/50 transition-colors"
                spellCheck={false}
                placeholder="ASS 內容…"
              />
            )}
            <div className="flex gap-2">
              <button
                onClick={() => setLyricsEditorOpen(false)}
                className="flex-1 py-3 rounded-2xl bg-white/8 text-white/70 text-sm hover:bg-white/12 transition-colors"
              >
                取消
              </button>
              <button
                onClick={saveLyrics}
                disabled={lyricsSaving || lyricsLoading || !assContent.trim()}
                className="flex-1 py-3 rounded-2xl bg-violet-600 text-white text-sm hover:bg-violet-500 transition-colors disabled:opacity-40"
              >
                {lyricsSaving ? "儲存中…" : "儲存並更新"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
