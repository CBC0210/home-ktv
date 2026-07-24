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
  { value: "subtitle_timing", label: "字幕對不上時間" },
  { value: "wrong_lyrics", label: "字幕是別首歌" },
  { value: "other", label: "其他問題" },
];
const AUDIO_ISSUES = new Set<SongIssue>([
  "clipping", "av_desync", "separation_noise", "other",
]);

const LYRICS_SOURCE_LABEL: Record<string, string> = {
  youtube_subtitle: "YouTube 字幕",
  bilibili_subtitle: "Bilibili 字幕",
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
  const [avEditorOpen, setAvEditorOpen] = useState(false);
  const [offsetMs, setOffsetMs] = useState(0);
  const [avMs, setAvMs] = useState(0);
  const [plainLyrics, setPlainLyrics] = useState<string>("");

  // Sync volume local state when server echoes back changes (e.g., another remote adjusted it)
  useEffect(() => { setMainVol(playback.main_volume); }, [playback.main_volume]);
  useEffect(() => { setVocalVol(playback.vocal_volume); }, [playback.vocal_volume]);

  // Initialise the subtitle-delay editor from the song's saved offset
  useEffect(() => {
    setOffsetMs(currentSong?.subtitle_offset_ms ?? 0);
  }, [currentSong?.id, currentSong?.subtitle_offset_ms]);

  // Initialise the A/V fine-tune from the song's saved offset
  useEffect(() => {
    setAvMs(currentSong?.av_offset_ms ?? 0);
  }, [currentSong?.id, currentSong?.av_offset_ms]);

  const applyAv = useCallback((next: number) => {
    if (!currentSong) return;
    const clamped = Math.max(-2000, Math.min(2000, Math.round(next / 10) * 10));
    setAvMs(clamped);
    sendCommand({ type: "av.offset", songId: currentSong.id, offsetMs: clamped });
  }, [currentSong, sendCommand]);

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

  // Apply + persist the delay (server live-pushes it to the TV).
  // No range limit — lyrics from a wrong cut can be off by minutes, and the
  // user is calibrating by eye anyway.
  const applyOffset = useCallback((next: number) => {
    if (!currentSong) return;
    const v = Math.round(next / 100) * 100;
    setOffsetMs(v);
    sendCommand({ type: "lyrics.offset", songId: currentSong.id, offsetMs: v });
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
            {/* Skip buttons — easier than dragging the bar */}
            <div className="flex items-center justify-center gap-2 mt-1.5">
              {([-10, -5, 5, 10] as const).map((d) => (
                <button
                  key={d}
                  onClick={() => {
                    const t = Math.max(
                      0,
                      Math.min(duration || 1e9, playback.position_sec + d),
                    );
                    sendCommand({ type: "playback.seek", positionSec: t });
                  }}
                  className="flex-1 max-w-20 bg-white/6 hover:bg-white/12 text-white/80 text-sm rounded-lg py-1.5 transition-colors"
                >
                  {d > 0 ? `+${d}s` : `${d}s`}
                </button>
              ))}
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

        {/* Autoplay — compact, anyone can toggle */}
        <button
          onClick={() => sendCommand({ type: "autoplay.set", enabled: !playback.autoplay })}
          title="隊列快空時依最後一首的曲風自動推薦並預先處理"
          className={`flex items-center justify-center gap-2 rounded-full px-3 py-1.5 text-xs border transition-colors self-center ${
            playback.autoplay
              ? "bg-violet-600/20 border-violet-500/40 text-violet-200"
              : "bg-white/4 border-white/8 text-white/50"
          }`}
        >
          <span>🔀 自動播放</span>
          <span
            className={`w-8 h-4 rounded-full flex-shrink-0 relative transition-colors ${
              playback.autoplay ? "bg-violet-500" : "bg-white/15"
            }`}
          >
            <span
              className={`absolute top-0.5 w-3 h-3 rounded-full bg-white transition-all ${
                playback.autoplay ? "left-[18px]" : "left-0.5"
              }`}
            />
          </span>
        </button>

        {/* Reactions — recents + custom picker */}
        <EmojiReactions onSend={(emoji) => sendCommand({ type: "reaction.send", emoji })} />

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

        {/* Fine-tune triggers. Subtitle delay is open to everyone (字幕對不
            上時人人可調); A/V micro-tune stays admin-only. */}
        {currentSong && (currentSong.has_timing || (adminMode && !currentSong.use_original_audio)) && (
          <div className="flex items-center justify-center gap-4">
            {currentSong.has_timing && (
              <button
                onClick={() => setLyricsEditorOpen(true)}
                className="text-xs text-amber-300/70 hover:text-amber-300 py-1 transition-colors"
              >
                ⏱️ 字幕延遲{offsetMs ? `（${offsetMs > 0 ? "+" : ""}${(offsetMs / 1000).toFixed(1)}s）` : ""}
              </button>
            )}
            {adminMode && !currentSong.use_original_audio && (
              <button
                onClick={() => setAvEditorOpen(true)}
                className="text-xs text-amber-300/70 hover:text-amber-300 py-1 transition-colors"
              >
                🎬 影音微調{avMs ? `（${avMs > 0 ? "+" : ""}${avMs}ms）` : ""}
              </button>
            )}
          </div>
        )}
      </div>

      {/* Subtitle-delay editor modal (admin) */}
      {lyricsEditorOpen && (
        <div className="fixed inset-0 bg-black/90 z-50 flex flex-col items-center justify-center p-6">
          <div className="bg-[#1a1a1a] border border-white/10 rounded-3xl p-6 w-full max-w-sm shadow-2xl">
            <div className="text-center mb-4">
              <div className="text-3xl mb-1">⏱️</div>
              <h3 className="text-white font-bold text-lg">校正字幕時間</h3>
              <p className="text-white/40 text-xs mt-1">
                看電視、聽人聲，按照你看到的症狀按下面的按鈕，效果即時。
              </p>
            </div>

            {/* Current value */}
            <div className="text-center mb-4">
              <p className={`text-3xl font-bold tabular-nums ${offsetMs === 0 ? "text-white/50" : "text-amber-300"}`}>
                {offsetMs > 0 ? "+" : ""}{(offsetMs / 1000).toFixed(1)}s
              </p>
              <p className="text-white/30 text-[10px] mt-0.5">
                {offsetMs === 0 ? "未調整" : offsetMs > 0 ? "字幕已延後" : "字幕已提前"}（不限範圍）
              </p>
            </div>

            {/* Symptom: subtitles arrive too EARLY → push them later (+) */}
            <div className="rounded-2xl bg-sky-500/8 border border-sky-400/15 p-3 mb-2.5">
              <p className="text-sky-300/90 text-xs font-medium mb-2">
                🐇 字幕跑太快（還沒唱到，字幕就先亮）→ 延後字幕
              </p>
              <div className="grid grid-cols-3 gap-2">
                {[200, 1000, 5000].map((step) => (
                  <button
                    key={`later-${step}`}
                    onClick={() => applyOffset(offsetMs + step)}
                    className="py-2.5 rounded-xl bg-sky-500/15 hover:bg-sky-500/25 text-sky-200 text-sm font-semibold active:scale-95 transition-all"
                  >
                    +{step >= 1000 ? `${step / 1000}s` : "0.2s"}
                  </button>
                ))}
              </div>
            </div>

            {/* Symptom: subtitles arrive too LATE → pull them earlier (−) */}
            <div className="rounded-2xl bg-rose-500/8 border border-rose-400/15 p-3 mb-3">
              <p className="text-rose-300/90 text-xs font-medium mb-2">
                🐢 字幕慢半拍（唱過了，字幕才亮）→ 提前字幕
              </p>
              <div className="grid grid-cols-3 gap-2">
                {[200, 1000, 5000].map((step) => (
                  <button
                    key={`earlier-${step}`}
                    onClick={() => applyOffset(offsetMs - step)}
                    className="py-2.5 rounded-xl bg-rose-500/15 hover:bg-rose-500/25 text-rose-200 text-sm font-semibold active:scale-95 transition-all"
                  >
                    −{step >= 1000 ? `${step / 1000}s` : "0.2s"}
                  </button>
                ))}
              </div>
            </div>

            <p className="text-white/25 text-[10px] text-center mb-3">
              訣竅：差很多先按 5s 大步找到位置，再用 0.2s 細調。鍵盤 ← → 可 0.1s 微調。
            </p>

            <div className="flex gap-2">
              <button
                onClick={() => applyOffset(0)}
                className="px-4 py-3 rounded-2xl bg-white/6 text-white/60 text-sm hover:bg-white/12 transition-colors"
              >
                歸零
              </button>
              <button
                onClick={() => setLyricsEditorOpen(false)}
                className="flex-1 py-3 rounded-2xl bg-violet-600 text-white text-sm font-medium hover:bg-violet-500 transition-colors"
              >
                完成（已自動儲存）
              </button>
            </div>
          </div>
        </div>
      )}

      {/* A/V fine-tune modal (admin) — same UX as the subtitle-delay one */}
      {avEditorOpen && (
        <div className="fixed inset-0 bg-black/90 z-50 flex flex-col items-center justify-center p-6">
          <div className="bg-[#1a1a1a] border border-white/10 rounded-3xl p-6 w-full max-w-sm shadow-2xl">
            <div className="text-center mb-5">
              <div className="text-3xl mb-1">🎬</div>
              <h3 className="text-white font-bold text-lg">影音同步微調</h3>
              <p className="text-white/40 text-xs mt-1">
                影片比音樂慢就調＋，音樂比影片慢就調－。已自動補償音訊延遲，這裡只做細修，效果即時。
              </p>
            </div>

            <div className="flex items-center justify-center gap-4 mb-2">
              <button
                onClick={() => applyAv(avMs - 100)}
                className="w-14 h-14 rounded-2xl bg-white/8 hover:bg-white/15 text-white text-2xl font-bold active:scale-90 transition-all"
                title="音樂提前 100ms"
              >
                ‹‹
              </button>
              <div className="text-center min-w-[110px]">
                <p className={`text-3xl font-bold tabular-nums ${avMs === 0 ? "text-white/50" : "text-amber-300"}`}>
                  {avMs > 0 ? "+" : ""}{avMs}<span className="text-base">ms</span>
                </p>
                <p className="text-white/30 text-[10px] mt-0.5">
                  {avMs === 0 ? "未調整" : avMs > 0 ? "音樂提前" : "音樂延後"}
                </p>
              </div>
              <button
                onClick={() => applyAv(avMs + 100)}
                className="w-14 h-14 rounded-2xl bg-white/8 hover:bg-white/15 text-white text-2xl font-bold active:scale-90 transition-all"
                title="音樂延後 100ms"
              >
                ››
              </button>
            </div>

            <div className="flex justify-center gap-2 mb-5">
              <button onClick={() => applyAv(avMs - 20)}
                className="px-3 py-1.5 rounded-lg bg-white/6 text-white/50 text-xs hover:bg-white/12">
                −20
              </button>
              <button onClick={() => applyAv(0)}
                className="px-3 py-1.5 rounded-lg bg-white/6 text-white/50 text-xs hover:bg-white/12">
                歸零
              </button>
              <button onClick={() => applyAv(avMs + 20)}
                className="px-3 py-1.5 rounded-lg bg-white/6 text-white/50 text-xs hover:bg-white/12">
                ＋20
              </button>
            </div>

            <button
              onClick={() => setAvEditorOpen(false)}
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

function lyricsSearchLinks(song: Song) {
  const q = encodeURIComponent(`${song.title} ${song.artist ?? ""}`.trim() + " 歌詞");
  return [
    { name: "Google", url: `https://www.google.com/search?q=${q}` },
    { name: "Mojim", url: `https://mojim.com/twh_search.php?keyword=${q}` },
    { name: "Genius", url: `https://genius.com/search?q=${q}` },
    { name: "YouTube", url: `https://www.youtube.com/results?search_query=${q}` },
  ];
}

function LyricsSearchLinkRow({ song }: { song: Song }) {
  return (
    <div className="flex flex-wrap justify-center gap-2">
      {lyricsSearchLinks(song).map((l) => (
        <a
          key={l.name}
          href={l.url}
          target="_blank"
          rel="noopener noreferrer"
          className="px-3 py-1.5 rounded-full bg-white/8 hover:bg-white/15 text-white/70 text-xs transition-colors"
        >
          {l.name} ↗
        </a>
      ))}
    </div>
  );
}

function PlainTextLyrics({ song, text }: { song: Song; text: string }) {
  const sourceLabel = song.lyrics_source ? LYRICS_SOURCE_LABEL[song.lyrics_source] ?? song.lyrics_source : null;

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
        {/* Quick external search — the fetched text may be incomplete or the
            wrong song; always leave an escape hatch to look it up yourself. */}
        <div className="mt-3 pt-3 border-t border-white/8">
          <p className="text-white/30 text-[10px] text-center mb-2">歌詞不對或不完整？自行搜尋：</p>
          <LyricsSearchLinkRow song={song} />
        </div>
      </div>
    );
  }

  // No lyrics at all — show search links
  return (
    <div className="bg-white/4 backdrop-blur rounded-2xl p-4 border border-white/8 text-center">
      <p className="text-white/50 text-sm mb-3">沒找到歌詞 — 請自行搜尋</p>
      <LyricsSearchLinkRow song={song} />
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

  const [lastIssue, setLastIssue] = useState<SongIssue>("other");

  async function submit(issue: SongIssue) {
    setBusy(true);
    try {
      await reportSongIssue(song.id, issue);
      setLastIssue(issue);
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

  // Collapsed: a small unobtrusive link, not a big card.
  if (!open && !done && !inOrigMode) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="self-center text-white/35 hover:text-white/60 text-[11px] py-0.5 transition-colors"
      >
        ⚠️ 這首歌有問題？回報
      </button>
    );
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
          {AUDIO_ISSUES.has(lastIssue)
            ? "✓ 已回報，下次播放此曲將改用原始影片音訊（修正爆音 / 不同步）。"
            : lastIssue === "wrong_lyrics"
            ? "✓ 已回報字幕是別首歌 — 已立即關閉錯誤字幕。可在下方「歌詞來源」挑正確的，或用搜尋連結自行查歌詞。"
            : "✓ 已回報字幕對不上，已記錄；可用「字幕延遲」按鈕校正。"}
        </p>
      ) : (
        <div className="flex flex-col gap-2">
          <p className="text-white/60 text-xs">
            是什麼問題？音訊類下次播放改用原始音訊；字幕是別首歌會立即關閉錯誤字幕。
          </p>
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

// Row 1 is these five, fixed forever. Row 2 is up to 5 user-added
// custom emoji (FIFO — a 6th evicts the oldest), persisted locally.
const DEFAULT_EMOJI = ["🔥", "👏", "😂", "❤️", "🎉"];
const QUICK_PALETTE = [
  "😍", "🤩", "😭", "🙌", "💯", "✨", "🎤", "🎸",
  "😎", "🤘", "👑", "💪", "🫶", "😱", "🤣", "🥰",
  "🍻", "🌟", "💃", "🕺", "👀", "🙏", "🥳", "🎊",
];
const CUSTOM_KEY = "ktv_custom_emoji";
const MAX_CUSTOM = 5;

function EmojiReactions({ onSend }: { onSend: (e: string) => void }) {
  const [customs, setCustoms] = useState<string[]>([]);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState("");

  useEffect(() => {
    try {
      const arr = JSON.parse(localStorage.getItem(CUSTOM_KEY) || "[]");
      if (Array.isArray(arr)) setCustoms(arr.slice(-MAX_CUSTOM));
    } catch { /* ignore */ }
  }, []);

  function addCustom(raw: string) {
    const e = (raw || "").trim();
    // Accept a single emoji (possibly ZWJ/skin-tone); reject empty / pasted text.
    if (!e || e.length > 8 || DEFAULT_EMOJI.includes(e)) return;
    setCustoms((cur) => {
      const next = [...cur.filter((x) => x !== e), e].slice(-MAX_CUSTOM);
      try { localStorage.setItem(CUSTOM_KEY, JSON.stringify(next)); } catch { /* ignore */ }
      return next;
    });
    setDraft("");
    setAdding(false);
  }

  return (
    <div className="px-4 flex flex-col gap-2">
      {/* Row 1 — fixed defaults */}
      <div className="flex items-center justify-around">
        {DEFAULT_EMOJI.map((emoji) => (
          <button
            key={emoji}
            onClick={() => onSend(emoji)}
            className="text-2xl hover:scale-125 active:scale-110 transition-transform p-2"
          >
            {emoji}
          </button>
        ))}
      </div>

      {/* Row 2 — custom slots + add */}
      <div className="flex items-center justify-around">
        {customs.map((emoji) => (
          <button
            key={emoji}
            onClick={() => onSend(emoji)}
            className="text-2xl hover:scale-125 active:scale-110 transition-transform p-2"
            title="長按可在「＋」重新管理"
          >
            {emoji}
          </button>
        ))}
        {Array.from({ length: Math.max(0, MAX_CUSTOM - customs.length) }).map((_, i) => (
          <span key={`ph${i}`} className="text-2xl p-2 opacity-15 select-none">·</span>
        ))}
        <button
          onClick={() => setAdding((v) => !v)}
          title="加入自己的表情（最多 5 個，滿了會擠掉最舊的）"
          className={`w-9 h-9 rounded-full text-sm flex-shrink-0 transition-colors ${
            adding ? "bg-violet-600 text-white" : "bg-white/8 text-white/50 hover:bg-white/15"
          }`}
        >
          ＋
        </button>
      </div>

      {adding && (
        <div className="bg-white/4 border border-white/8 rounded-2xl p-3 flex flex-col gap-2">
          <div className="flex gap-2">
            <input
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") addCustom(draft); }}
              placeholder="貼上或用鍵盤選一個表情"
              maxLength={8}
              autoFocus
              className="flex-1 bg-white/6 border border-white/10 rounded-lg px-3 py-2 text-lg text-white outline-none focus:border-violet-500/50"
            />
            <button
              onClick={() => addCustom(draft)}
              disabled={!draft.trim()}
              className="px-4 rounded-lg bg-violet-600 hover:bg-violet-500 disabled:opacity-40 text-white text-sm font-medium"
            >
              加入
            </button>
          </div>
          <div className="grid grid-cols-8 gap-1">
            {QUICK_PALETTE.map((emoji) => (
              <button
                key={emoji}
                onClick={() => addCustom(emoji)}
                className="text-xl hover:scale-125 active:scale-110 transition-transform p-1.5"
              >
                {emoji}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

const SOURCE_LABELS: Record<string, string> = {
  youtube: "YouTube 字幕",
  youtube_subtitle: "YouTube 字幕",
  bilibili: "Bilibili 字幕",
  bilibili_subtitle: "Bilibili 字幕",
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

  // Bilibili videos: the embedded-captions slot reads "Bilibili 字幕".
  const isBili = song.id.length === 12 && song.id.startsWith("BV");
  const srcLabel = (s: string) =>
    isBili && (s === "youtube" || s === "youtube_subtitle")
      ? "Bilibili 字幕"
      : (SOURCE_LABELS[s] ?? s);

  return (
    <div className="bg-white/4 backdrop-blur rounded-2xl border border-white/8 overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-4 py-3 text-left"
      >
        <span className="text-white/60 text-xs">
          字幕來源：<span className="text-violet-300">{current ? srcLabel(current) : "—"}</span>
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
                  {busy === s ? "…" : srcLabel(s)}
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
