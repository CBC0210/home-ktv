"use client";

import Image from "next/image";
import { useRef, useState, useCallback, useEffect } from "react";
import type { Song, PlaybackState, ClientCommand, QueueItem } from "@/lib/types";
import {
  getLyricsText, getLyricsSource, setLyricsSource,
  getFavoriteStatus, addFavorite, removeFavorite,
  reportSongIssue, clearSongReport, type SongIssue,
} from "@/lib/api";

const ISSUE_OPTIONS: { value: SongIssue; label: string }[] = [
  { value: "clipping", label: "爆音 / 破音" },
  { value: "av_desync", label: "音畫不同步" },
  { value: "separation_noise", label: "人聲分離有雜訊" },
  { value: "other", label: "其他問題" },
];

const LYRICS_SOURCE_LABEL: Record<string, string> = {
  youtube_subtitle: "YouTube 字幕",
  amll_ttml: "AMLL TTML",
  amll_ttml_fallback_netease: "NetEase 雲音樂",
  netease: "NetEase 雲音樂",
  qq: "QQ 音樂",
  syncedlyrics: "LRCLIB",
  mojim: "魔鏡歌詞網",
  kkbox: "KKBOX",
  genius: "Genius",
};

interface Props {
  currentSong: Song | null;
  currentQueueItem: QueueItem | null;
  playback: PlaybackState;
  processing: { stage: string; percent: number } | null;
  sendCommand: (cmd: ClientCommand) => void;
  adminMode?: boolean;
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
  adminMode = false,
}: Props) {
  const progressBarRef = useRef<HTMLDivElement>(null);
  const [mainVol, setMainVol] = useState(playback.main_volume);
  const [vocalVol, setVocalVol] = useState(playback.vocal_volume);
  const [lyricsEditorOpen, setLyricsEditorOpen] = useState(false);
  const [offsetMs, setOffsetMs] = useState(0);
  const [plainLyrics, setPlainLyrics] = useState<string>("");

  // Sync volume local state when server echoes back changes (e.g., another remote adjusted it)
  useEffect(() => { setMainVol(playback.main_volume); }, [playback.main_volume]);
  useEffect(() => { setVocalVol(playback.vocal_volume); }, [playback.vocal_volume]);

  // Initialise the subtitle-delay editor from the song's saved offset
  useEffect(() => {
    setOffsetMs(currentSong?.subtitle_offset_ms ?? 0);
  }, [currentSong?.id, currentSong?.subtitle_offset_ms]);

  // Fetch plain-text lyrics when song lacks word-level timing
  useEffect(() => {
    if (!currentSong || currentSong.has_timing) {
      setPlainLyrics("");
      return;
    }
    let cancelled = false;
    getLyricsText(currentSong.id)
      .then((t) => { if (!cancelled) setPlainLyrics(t); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [currentSong?.id, currentSong?.has_timing]);

  // Apply + persist the delay (server live-pushes it to the TV)
  const applyOffset = useCallback((next: number) => {
    if (!currentSong) return;
    const clamped = Math.max(-5000, Math.min(5000, next));
    setOffsetMs(clamped);
    sendCommand({ type: "lyrics.offset", songId: currentSong.id, offsetMs: clamped });
  }, [currentSong, sendCommand]);

  // Arrow keys nudge the delay while the editor is open
  useEffect(() => {
    if (!lyricsEditorOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowLeft") { e.preventDefault(); applyOffset(offsetMs - 100); }
      else if (e.key === "ArrowRight") { e.preventDefault(); applyOffset(offsetMs + 100); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [lyricsEditorOpen, offsetMs, applyOffset]);

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
          {currentSong && <FavoriteHeart songId={currentSong.id} />}
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
              value={mainVol}
              onChange={(e) => {
                const v = parseFloat(e.target.value);
                setMainVol(v);
                sendCommand({ type: "playback.setVolume", main: v });
              }}
              className="flex-1"
              style={{ background: `linear-gradient(to right, #fff ${mainVol * 100}%, rgba(255,255,255,0.15) ${mainVol * 100}%)` }}
            />
            <span className="text-white/40 text-xs w-12 text-right flex-shrink-0 font-mono tabular-nums">
              {Math.round(mainVol * 100)}%
            </span>
          </div>
          <div className={`flex items-center gap-3 ${currentSong?.use_original_audio ? "opacity-40" : ""}`}>
            <svg viewBox="0 0 24 24" fill="currentColor" className="w-4 h-4 text-violet-400/60 flex-shrink-0">
              <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 14.5v-9l6 4.5-6 4.5z"/>
            </svg>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={vocalVol}
              disabled={!!currentSong?.use_original_audio}
              onChange={(e) => {
                const v = parseFloat(e.target.value);
                setVocalVol(v);
                sendCommand({ type: "playback.setVolume", vocal: v });
              }}
              className="flex-1 disabled:cursor-not-allowed"
              style={{ background: `linear-gradient(to right, #7c3aed ${vocalVol * 100}%, rgba(255,255,255,0.15) ${vocalVol * 100}%)` }}
            />
            <span className="text-white/40 text-xs w-12 text-right flex-shrink-0 font-mono tabular-nums">
              {Math.round(vocalVol * 100)}%
            </span>
          </div>
          {currentSong?.use_original_audio && (
            <p className="text-amber-400/70 text-[11px] px-1">
              ⚠ 此曲已回報問題，使用原始影片音訊播放，人聲調整停用。
            </p>
          )}
        </div>

        {/* Autoplay — admin only */}
        {adminMode && (
          <button
            onClick={() => sendCommand({ type: "autoplay.set", enabled: !playback.autoplay })}
            className={`flex items-center justify-between rounded-2xl px-4 py-3 border transition-colors ${
              playback.autoplay
                ? "bg-violet-600/20 border-violet-500/40"
                : "bg-white/4 border-white/8"
            }`}
          >
            <div className="text-left">
              <p className="text-white text-sm font-medium">🔀 自動播放</p>
              <p className="text-white/40 text-[11px] mt-0.5">
                隊列快空時依最後一首的曲風自動推薦並預先處理
              </p>
            </div>
            <span
              className={`w-11 h-6 rounded-full flex-shrink-0 relative transition-colors ${
                playback.autoplay ? "bg-violet-500" : "bg-white/15"
              }`}
            >
              <span
                className={`absolute top-0.5 w-5 h-5 rounded-full bg-white transition-all ${
                  playback.autoplay ? "left-[22px]" : "left-0.5"
                }`}
              />
            </span>
          </button>
        )}

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

        {/* Report a playback problem */}
        {currentSong && (
          <ReportProblem song={currentSong} adminMode={adminMode} />
        )}

        {/* Plain-text lyrics fallback (when no word timing) */}
        {currentSong && !currentSong.has_timing && (
          <PlainTextLyrics
            song={currentSong}
            text={plainLyrics}
          />
        )}

        {/* Lyrics source selector */}
        {currentSong && (
          <LyricsSourcePicker song={currentSong} />
        )}

        {/* Lyrics timing — admin only */}
        {adminMode && currentSong?.has_timing && (
          <button
            onClick={() => setLyricsEditorOpen(true)}
            className="text-xs text-amber-300/70 hover:text-amber-300 py-1 transition-colors text-center"
          >
            ⏱️ 調整字幕延遲（管理員）
          </button>
        )}
      </div>

      {/* Subtitle-delay editor modal (admin) */}
      {lyricsEditorOpen && (
        <div className="fixed inset-0 bg-black/90 z-50 flex flex-col items-center justify-center p-6">
          <div className="bg-[#1a1a1a] border border-white/10 rounded-3xl p-6 w-full max-w-sm shadow-2xl">
            <div className="text-center mb-5">
              <div className="text-3xl mb-1">⏱️</div>
              <h3 className="text-white font-bold text-lg">調整字幕延遲</h3>
              <p className="text-white/40 text-xs mt-1">
                字幕對不上時微調。可按 ← → 鍵微調，效果即時顯示在電視上。
              </p>
            </div>

            <div className="flex items-center justify-center gap-4 mb-2">
              <button
                onClick={() => applyOffset(offsetMs - 100)}
                className="w-14 h-14 rounded-2xl bg-white/8 hover:bg-white/15 text-white text-2xl font-bold active:scale-90 transition-all"
                title="字幕提前 0.1 秒"
              >
                ‹‹
              </button>
              <div className="text-center min-w-[110px]">
                <p className={`text-3xl font-bold tabular-nums ${offsetMs === 0 ? "text-white/50" : "text-amber-300"}`}>
                  {offsetMs > 0 ? "+" : ""}{(offsetMs / 1000).toFixed(1)}s
                </p>
                <p className="text-white/30 text-[10px] mt-0.5">
                  {offsetMs === 0 ? "未調整" : offsetMs > 0 ? "字幕延後" : "字幕提前"}
                </p>
              </div>
              <button
                onClick={() => applyOffset(offsetMs + 100)}
                className="w-14 h-14 rounded-2xl bg-white/8 hover:bg-white/15 text-white text-2xl font-bold active:scale-90 transition-all"
                title="字幕延後 0.1 秒"
              >
                ››
              </button>
            </div>

            <div className="flex justify-center gap-2 mb-5">
              <button
                onClick={() => applyOffset(offsetMs - 500)}
                className="px-3 py-1.5 rounded-lg bg-white/6 text-white/50 text-xs hover:bg-white/12"
              >
                −0.5s
              </button>
              <button
                onClick={() => applyOffset(0)}
                className="px-3 py-1.5 rounded-lg bg-white/6 text-white/50 text-xs hover:bg-white/12"
              >
                歸零
              </button>
              <button
                onClick={() => applyOffset(offsetMs + 500)}
                className="px-3 py-1.5 rounded-lg bg-white/6 text-white/50 text-xs hover:bg-white/12"
              >
                +0.5s
              </button>
            </div>

            <button
              onClick={() => setLyricsEditorOpen(false)}
              className="w-full py-3 rounded-2xl bg-violet-600 text-white text-sm font-medium hover:bg-violet-500 transition-colors"
            >
              完成（已自動儲存）
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function PlainTextLyrics({ song, text }: { song: Song; text: string }) {
  const sourceLabel = song.lyrics_source ? LYRICS_SOURCE_LABEL[song.lyrics_source] ?? song.lyrics_source : null;
  const searchQuery = encodeURIComponent(`${song.title} ${song.artist ?? ""}`.trim() + " 歌詞");

  if (text) {
    return (
      <div className="bg-white/4 backdrop-blur rounded-2xl p-4 border border-white/8">
        <div className="flex items-center justify-between mb-2">
          <span className="text-white/40 text-xs">純文字歌詞</span>
          {sourceLabel && (
            <span className="text-violet-300/60 text-[10px]">來源：{sourceLabel}</span>
          )}
        </div>
        <div className="max-h-64 overflow-y-auto">
          <pre className="text-white/80 text-sm whitespace-pre-wrap leading-relaxed font-sans">{text}</pre>
        </div>
      </div>
    );
  }

  // No lyrics at all — show search links
  return (
    <div className="bg-white/4 backdrop-blur rounded-2xl p-4 border border-white/8 text-center">
      <p className="text-white/50 text-sm mb-3">沒找到歌詞 — 請自行搜尋</p>
      <div className="flex flex-wrap justify-center gap-2">
        {[
          { name: "Google", url: `https://www.google.com/search?q=${searchQuery}` },
          { name: "Mojim", url: `https://mojim.com/twh_search.php?keyword=${searchQuery}` },
          { name: "Genius", url: `https://genius.com/search?q=${searchQuery}` },
          { name: "YouTube", url: `https://www.youtube.com/results?search_query=${searchQuery}` },
        ].map((l) => (
          <a
            key={l.name}
            href={l.url}
            target="_blank"
            rel="noopener noreferrer"
            className="px-3 py-1.5 rounded-full bg-white/8 hover:bg-white/15 text-white/70 text-xs transition-colors"
          >
            {l.name}
          </a>
        ))}
      </div>
    </div>
  );
}

function ReportProblem({ song, adminMode }: { song: Song; adminMode: boolean }) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  // Live: this play is already in original-audio mode (set on a prior report).
  const inOrigMode = !!song.use_original_audio;

  // Reset transient UI when the song changes.
  useEffect(() => { setOpen(false); setDone(false); }, [song.id]);

  async function submit(issue: SongIssue) {
    setBusy(true);
    try {
      await reportSongIssue(song.id, issue);
      setDone(true);
      setOpen(false);
    } catch {
      alert("回報失敗，請稍後再試");
    }
    setBusy(false);
  }

  async function revert() {
    if (!confirm("還原成分離音軌播放？（下次播放此曲生效）")) return;
    setBusy(true);
    try {
      await clearSongReport(song.id);
      setDone(false);
      alert("已還原，下次播放此曲將使用分離音軌");
    } catch {
      alert("還原失敗（需要管理員）");
    }
    setBusy(false);
  }

  return (
    <div className="bg-white/4 border border-white/8 rounded-2xl px-4 py-3">
      {inOrigMode ? (
        <div className="flex items-center justify-between gap-3">
          <p className="text-amber-400/80 text-xs leading-relaxed">
            🔊 已回報問題，使用原始音訊播放（人聲調整停用）。
          </p>
          {adminMode && (
            <button
              onClick={revert}
              disabled={busy}
              className="text-white/60 text-xs px-3 py-1.5 rounded-lg border border-white/15 flex-shrink-0 disabled:opacity-50"
            >
              還原
            </button>
          )}
        </div>
      ) : done ? (
        <p className="text-emerald-400/80 text-xs leading-relaxed">
          ✓ 已回報，下次播放此曲將改用原始影片音訊（修正爆音 / 不同步）。
        </p>
      ) : !open ? (
        <button
          onClick={() => setOpen(true)}
          className="flex items-center gap-2 text-white/55 text-xs"
        >
          <span className="text-base leading-none">⚠️</span>
          這首歌有問題？回報一下
        </button>
      ) : (
        <div className="flex flex-col gap-2">
          <p className="text-white/60 text-xs">是什麼問題？回報後下次播放會改用原始影片音訊。</p>
          <div className="grid grid-cols-2 gap-2">
            {ISSUE_OPTIONS.map((o) => (
              <button
                key={o.value}
                onClick={() => submit(o.value)}
                disabled={busy}
                className="bg-white/6 hover:bg-white/10 border border-white/10 text-white/85 text-xs rounded-lg px-3 py-2 disabled:opacity-50"
              >
                {o.label}
              </button>
            ))}
          </div>
          <button
            onClick={() => setOpen(false)}
            className="text-white/40 text-[11px] self-start mt-0.5"
          >
            取消
          </button>
        </div>
      )}
    </div>
  );
}

const SOURCE_LABELS: Record<string, string> = {
  youtube: "YouTube 字幕",
  amll_ttml: "AMLL 逐字",
  netease: "NetEase",
  qq: "QQ 音樂",
  syncedlyrics: "LRCLIB",
  mojim: "魔鏡(純文字)",
  kkbox: "KKBOX(純文字)",
  genius: "Genius(純文字)",
  none: "關閉字幕",
};

function LyricsSourcePicker({ song }: { song: Song }) {
  const [open, setOpen] = useState(false);
  const [current, setCurrent] = useState<string | null>(song.lyrics_source);
  const [available, setAvailable] = useState<Record<string, { timed: boolean }>>({});
  const [prefetched, setPrefetched] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setCurrent(song.lyrics_source);
    getLyricsSource(song.id)
      .then((info) => {
        if (cancelled) return;
        setCurrent(info.current);
        setAvailable(info.available || {});
        setPrefetched(info.prefetched ?? false);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [song.id, song.lyrics_source]);

  async function pick(src: string) {
    setBusy(src);
    setMsg(null);
    try {
      const r = await setLyricsSource(song.id, src);
      setCurrent(r.source);
      setMsg(
        src === "none" ? "✓ 已關閉字幕"
        : r.has_timing ? "✓ 已切換（有時間軸）"
        : "✓ 已切換（純文字）"
      );
      setTimeout(() => setMsg(null), 2000);
    } catch {
      setMsg("✗ 此來源找不到歌詞");
      setTimeout(() => setMsg(null), 2000);
    } finally {
      setBusy(null);
    }
  }

  // Only show sources that were actually pre-fetched, plus "none"
  const options = [...Object.keys(available), "none"];

  return (
    <div className="bg-white/4 backdrop-blur rounded-2xl border border-white/8 overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-4 py-3 text-left"
      >
        <span className="text-white/60 text-xs">
          字幕來源：<span className="text-violet-300">{current ? (SOURCE_LABELS[current] ?? current) : "—"}</span>
        </span>
        <span className="text-white/30 text-xs">{open ? "▲" : "▼ 切換"}</span>
      </button>
      {open && (
        <div className="px-3 pb-3">
          {!prefetched && (
            <p className="text-white/40 text-[11px] mb-2 px-1">
              其他來源整理中…（背景處理，稍後再開即可瞬間切換）
            </p>
          )}
          <div className="grid grid-cols-3 gap-1.5">
            {options.map((s) => {
              const timed = s !== "none" && available[s]?.timed;
              return (
                <button
                  key={s}
                  onClick={() => pick(s)}
                  disabled={busy !== null}
                  className={`text-[11px] py-2 px-1 rounded-lg transition-colors disabled:opacity-40 ${
                    current === s
                      ? "bg-violet-600 text-white"
                      : "bg-white/8 text-white/60 hover:bg-white/15"
                  }`}
                >
                  {busy === s ? "…" : (SOURCE_LABELS[s] ?? s)}
                  {s !== "none" && (
                    <span className="block text-[9px] opacity-60">
                      {timed ? "時間軸" : "純文字"}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}
      {msg && (
        <p className="px-4 pb-3 text-xs text-white/50">{msg}</p>
      )}
    </div>
  );
}

function FavoriteHeart({ songId }: { songId: string }) {
  const [fav, setFav] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setFav(false);
    getFavoriteStatus(songId)
      .then((r) => { if (!cancelled) setFav(r.favorited); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [songId]);

  async function toggle() {
    if (busy) return;
    setBusy(true);
    const next = !fav;
    setFav(next);  // optimistic
    try {
      if (next) await addFavorite(songId);
      else await removeFavorite(songId);
    } catch {
      setFav(!next);  // revert
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      onClick={toggle}
      disabled={busy}
      className="mt-3 inline-flex items-center gap-1.5 px-4 py-1.5 rounded-full bg-white/8 hover:bg-white/12 transition-all active:scale-95 disabled:opacity-50"
      aria-label={fav ? "取消收藏" : "加入收藏"}
    >
      <svg
        viewBox="0 0 24 24"
        className={`w-5 h-5 transition-colors ${fav ? "text-rose-500" : "text-white/40"}`}
        fill={fav ? "currentColor" : "none"}
        stroke="currentColor"
        strokeWidth="2"
      >
        <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z" />
      </svg>
      <span className={`text-xs font-medium ${fav ? "text-rose-400" : "text-white/50"}`}>
        {fav ? "已收藏" : "收藏"}
      </span>
    </button>
  );
}
