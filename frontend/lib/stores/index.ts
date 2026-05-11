"use client";

import { create } from "zustand";
import type { Room, Song, Guest, QueueItem, PlaybackState, GuestSession } from "../types";

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

  // Actions
  setRoom: (room: Room) => void;
  setSession: (session: GuestSession | null) => void;
  setQueue: (queue: QueueItem[]) => void;
  setCurrentSong: (song: Song | null, item: QueueItem | null) => void;
  setPlayback: (state: PlaybackState) => void;
  setGuests: (guests: Guest[]) => void;
  setProcessing: (p: { stage: string; percent: number } | null) => void;
  updatePosition: (positionSec: number) => void;
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

  setRoom: (room) => set({ room }),
  setSession: (session) => set({ session }),
  setQueue: (queue) => set({ queue }),
  setCurrentSong: (currentSong, currentQueueItem) =>
    set({ currentSong, currentQueueItem }),
  setPlayback: (playback) => set({ playback }),
  setGuests: (guests) => set({ guests }),
  setProcessing: (processing) => set({ processing }),
  updatePosition: (positionSec) =>
    set((s) => ({ playback: { ...s.playback, position_sec: positionSec } })),
}));
