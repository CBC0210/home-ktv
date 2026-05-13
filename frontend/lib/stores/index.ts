"use client";

import { create } from "zustand";
import type { Room, Song, Guest, QueueItem, PlaybackState, GuestSession } from "../types";

export type PlayerTheme = "default" | "party" | "elegant" | "retro";

/** CSS classes for each theme applied to the standby screen root div */
export const THEME_STYLES: Record<
  PlayerTheme,
  { bg: string; accentText: string; headerText: string }
> = {
  default: {
    bg: "bg-gray-950 bg-gradient-to-br from-purple-950/60 via-gray-950 to-indigo-950/40",
    accentText: "text-purple-400",
    headerText: "text-white",
  },
  party: {
    bg: "bg-gray-900 bg-gradient-to-br from-pink-900/70 via-purple-900/60 to-indigo-900/70",
    accentText: "text-pink-400",
    headerText: "text-white",
  },
  elegant: {
    bg: "bg-slate-950 bg-gradient-to-br from-blue-950/80 via-slate-950 to-slate-900",
    accentText: "text-sky-400",
    headerText: "text-slate-100",
  },
  retro: {
    bg: "bg-stone-900 bg-gradient-to-br from-amber-950/50 via-stone-900 to-yellow-950/30",
    accentText: "text-amber-400",
    headerText: "text-amber-100",
  },
};

interface KtvStore {
  // Room & session
  room: Room | null;
  session: GuestSession | null;

  // Playback
  playback: PlaybackState;
  currentSong: Song | null;
  currentQueueItem: QueueItem | null;

  // Queue
  queue: QueueItem[];

  // Connected guests
  guests: Guest[];

  // Processing overlay
  processing: { stage: string; percent: number } | null;

  // Theme
  theme: PlayerTheme;

  // Actions
  setRoom: (room: Room) => void;
  setSession: (session: GuestSession | null) => void;
  setQueue: (queue: QueueItem[]) => void;
  setCurrentSong: (song: Song | null, item: QueueItem | null) => void;
  setPlayback: (state: Partial<PlaybackState>) => void;
  setGuests: (guests: Guest[]) => void;
  setProcessing: (p: { stage: string; percent: number } | null) => void;
  updatePosition: (positionSec: number) => void;
  setTheme: (theme: PlayerTheme) => void;
  setIsPlaying: (isPlaying: boolean) => void;
}

const defaultPlayback: PlaybackState = {
  is_playing: false,
  current_song_id: null,
  current_queue_item_id: null,
  position_sec: 0,
  main_volume: 1,
  vocal_volume: 0,
  pitch_semitones: 0,
  speed_rate: 1,
};

export const useKtvStore = create<KtvStore>((set) => ({
  room: null,
  session: null,
  playback: defaultPlayback,
  currentSong: null,
  currentQueueItem: null,
  queue: [],
  guests: [],
  processing: null,
  theme: "default",

  setRoom: (room) => set({ room }),
  setSession: (session) => set({ session }),
  setQueue: (queue) => set({ queue }),
  setCurrentSong: (currentSong, currentQueueItem) =>
    set({ currentSong, currentQueueItem }),
  setPlayback: (patch) => set((s) => ({ playback: { ...s.playback, ...patch } })),
  setGuests: (guests) => set({ guests }),
  setProcessing: (processing) => set({ processing }),
  updatePosition: (positionSec) =>
    set((s) => ({ playback: { ...s.playback, position_sec: positionSec } })),
  setTheme: (theme) => set({ theme }),
  setIsPlaying: (isPlaying) =>
    set((s) => ({ playback: { ...s.playback, is_playing: isPlaying } })),
}));
