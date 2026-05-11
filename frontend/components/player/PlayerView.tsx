"use client";

import { useEffect, useRef, useCallback } from "react";
import { useKtvStore } from "@/lib/stores";
import { useWebSocket } from "@/lib/ws";
import { getQueue, streamUrl } from "@/lib/api";
import type { ServerEvent, ClientCommand } from "@/lib/types";
import SubtitleLayer from "./SubtitleLayer";

interface Props {
  roomId: string;
}

const STAGE_LABELS: Record<string, string> = {
  downloading: "下載中",
  separating: "分離人聲",
  fetching_lyrics: "抓取歌詞",
  aligning: "對齊字幕",
  packaging: "封裝 HLS",
};

export default function PlayerView({ roomId }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const hlsRef = useRef<import("hls.js").default | null>(null);

  const {
    currentSong,
    currentQueueItem,
    queue,
    playback,
    processing,
    setQueue,
    setCurrentSong,
    setPlayback,
    setProcessing,
    updatePosition,
  } = useKtvStore();

  const handleEvent = useCallback(
    (event: ServerEvent) => {
      if (event.type === "queue.updated") setQueue(event.queue);
      else if (event.type === "song.started")
        setCurrentSong(event.song, event.queueItem);
      else if (event.type === "song.progress") updatePosition(event.positionSec);
      else if (event.type === "song.ended") setCurrentSong(null, null);
      else if (event.type === "playback.state") setPlayback(event.state);
      else if (event.type === "song.processing")
        setProcessing({ stage: event.stage, percent: event.percent });
    },
    [setQueue, setCurrentSong, updatePosition, setPlayback, setProcessing]
  );

  const { sendCommand } = useWebSocket(roomId, null, "player", handleEvent);
  // sendCommand kept for future player.playing status
  void sendCommand;

  // Load initial queue
  useEffect(() => {
    getQueue(roomId)
      .then(setQueue)
      .catch(() => {});
  }, [roomId, setQueue]);

  // HLS setup when song changes
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    if (!currentSong || currentSong.status !== "ready") {
      hlsRef.current?.destroy();
      hlsRef.current = null;
      video.src = "";
      return;
    }

    const src = streamUrl(currentSong.id);

    import("hls.js").then(({ default: Hls }) => {
      hlsRef.current?.destroy();

      if (Hls.isSupported()) {
        const hls = new Hls({ enableWorker: false });
        hlsRef.current = hls;
        hls.loadSource(src);
        hls.attachMedia(video);
        hls.on(Hls.Events.MANIFEST_PARSED, () => {
          video.play().catch(() => {});
        });
      } else if (video.canPlayType("application/vnd.apple.mpegurl")) {
        video.src = src;
        video.play().catch(() => {});
      }
    });

    return () => {
      hlsRef.current?.destroy();
      hlsRef.current = null;
    };
  }, [currentSong]);

  // Sync play/pause from playback state
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    if (playback.is_playing && video.paused) video.play().catch(() => {});
    if (!playback.is_playing && !video.paused) video.pause();
  }, [playback.is_playing]);

  const nextItem = queue.find(
    (q) => q.id !== currentQueueItem?.id && q.status !== "playing"
  );

  // Standby screen
  if (!currentSong) {
    return (
      <div className="relative min-h-screen bg-gray-950 flex flex-col items-center justify-center overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-purple-950/50 to-gray-950" />

        <div className="relative z-10 flex flex-col items-center gap-8 text-center px-8">
          <h1 className="text-5xl font-bold text-white tracking-tight">
            🎤 Home KTV
          </h1>
          <p className="text-gray-400 text-xl">等待點歌中…</p>

          {/* QR code placeholder */}
          <div className="bg-white rounded-2xl p-6 w-48 h-48 flex flex-col items-center justify-center gap-2">
            <div className="text-gray-900 text-xs font-mono text-center break-all">
              {typeof window !== "undefined"
                ? window.location.origin + `/r/${roomId}/remote`
                : `/r/${roomId}/remote`}
            </div>
          </div>

          <p className="text-gray-500 text-sm">
            用手機掃 QR Code 或直接輸入網址點歌
          </p>

          {queue.length > 0 && (
            <div className="bg-gray-800/80 rounded-xl px-6 py-4 w-full max-w-sm">
              <p className="text-gray-400 text-sm mb-2">隊列中</p>
              {queue.slice(0, 3).map((item) => (
                <div key={item.id} className="text-white text-sm py-1 truncate">
                  {item.song?.title ?? item.song_id}
                  {item.status !== "ready" && (
                    <span className="ml-2 text-yellow-400 text-xs">
                      {STAGE_LABELS[item.status] ?? item.status}
                    </span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Processing overlay */}
        {processing && (
          <div className="absolute bottom-8 left-1/2 -translate-x-1/2 bg-gray-800/90 rounded-xl px-8 py-4 text-center">
            <p className="text-white font-medium">
              {STAGE_LABELS[processing.stage] ?? processing.stage}
            </p>
            <div className="w-48 h-1.5 bg-gray-700 rounded-full mt-2 overflow-hidden">
              <div
                className="h-full bg-purple-500 transition-all"
                style={{ width: `${processing.percent}%` }}
              />
            </div>
            <p className="text-gray-400 text-xs mt-1">{processing.percent}%</p>
          </div>
        )}
      </div>
    );
  }

  // Playing screen
  return (
    <div className="relative w-screen h-screen bg-black overflow-hidden">
      {/* Video layer */}
      <video
        ref={videoRef}
        className="absolute inset-0 w-full h-full object-contain"
        playsInline
        muted
      />

      {/* Subtitle layer */}
      <SubtitleLayer song={currentSong} positionSec={playback.position_sec} />

      {/* Top-left info */}
      <div className="absolute top-4 left-4 bg-black/50 backdrop-blur-sm rounded-lg px-4 py-2">
        <p className="text-white font-medium text-sm">
          {currentSong.title}
        </p>
        {currentSong.artist && (
          <p className="text-gray-300 text-xs">{currentSong.artist}</p>
        )}
        {currentQueueItem?.guest?.nickname && (
          <p className="text-purple-300 text-xs">
            {currentQueueItem.guest.nickname} 點的
          </p>
        )}
      </div>

      {/* Bottom: next up */}
      {nextItem && (
        <div className="absolute bottom-4 right-4 bg-black/50 backdrop-blur-sm rounded-lg px-4 py-2 max-w-xs">
          <p className="text-gray-400 text-xs">下一首</p>
          <p className="text-white text-sm truncate">
            {nextItem.song?.title ?? nextItem.song_id}
          </p>
          {nextItem.guest?.nickname && (
            <p className="text-gray-400 text-xs">
              {nextItem.guest.nickname} 點的
            </p>
          )}
        </div>
      )}

      {/* Processing overlay */}
      {processing && (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 bg-gray-800/90 rounded-xl px-8 py-3 text-center">
          <p className="text-white text-sm">
            {STAGE_LABELS[processing.stage] ?? processing.stage} —{" "}
            {processing.percent}%
          </p>
        </div>
      )}
    </div>
  );
}
