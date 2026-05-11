import type { Room, Song, QueueItem, Guest } from "./types";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    ...init,
  });
  if (!res.ok) throw new Error(`API ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

// Rooms
export const getRooms = () => apiFetch<Room[]>("/api/rooms");
export const getRoom = (id: string) => apiFetch<Room>(`/api/rooms/${id}`);
export const createRoom = (data: {
  id: string;
  name: string;
  password?: string;
}) =>
  apiFetch<Room>("/api/rooms", {
    method: "POST",
    body: JSON.stringify(data),
  });

// Songs
export const searchSongs = (q: string) =>
  apiFetch<Song[]>(`/api/songs/search?q=${encodeURIComponent(q)}`);

export interface YoutubeResult {
  id: string;
  title: string;
  channel: string | null;
  duration_sec: number | null;
  thumbnail_url: string | null;
  url: string;
  cached: boolean;
}
export const youtubeSearch = (q: string, limit = 10) =>
  apiFetch<YoutubeResult[]>(
    `/api/songs/youtube-search?q=${encodeURIComponent(q)}&limit=${limit}`
  );
export const getSong = (id: string) => apiFetch<Song>(`/api/songs/${id}`);
export const getSongStatus = (id: string) =>
  apiFetch<{ status: string; error?: string }>(`/api/songs/${id}/status`);
export const addSong = (data: {
  youtube_url: string;
  room_id: string;
  position?: "end" | "next";
}) =>
  apiFetch<QueueItem>("/api/songs/", {
    method: "POST",
    body: JSON.stringify(data),
  });

// Queue
export const getQueue = (roomId: string) =>
  apiFetch<QueueItem[]>(`/api/queue?room_id=${roomId}`);
export const addToQueue = (data: {
  song_id: string;
  room_id: string;
  position?: "end" | "next";
}) =>
  apiFetch<QueueItem>("/api/queue", {
    method: "POST",
    body: JSON.stringify(data),
  });
export const removeFromQueue = (itemId: number) =>
  apiFetch<void>(`/api/queue/${itemId}`, { method: "DELETE" });
export const reorderQueue = (roomId: string, itemIds: number[]) =>
  apiFetch<void>(`/api/rooms/${roomId}/reorder`, {
    method: "PATCH",
    body: JSON.stringify({ item_ids: itemIds }),
  });
export const markPlaying = (itemId: number) =>
  apiFetch<void>(`/api/queue/${itemId}/play`, { method: "POST" });
export const markDone = (itemId: number) =>
  apiFetch<void>(`/api/queue/${itemId}/done`, { method: "POST" });

// Guests
export const joinRoom = (data: {
  room_id: string;
  nickname: string;
  password?: string;
}) =>
  apiFetch<{ guest: Guest; token: string }>("/api/guests/join", {
    method: "POST",
    body: JSON.stringify(data),
  });
export const getMe = () => apiFetch<Guest>("/api/guests/me");

// Admin
export const adminLogin = (password: string) =>
  apiFetch<{ token: string }>("/api/auth/admin/login", {
    method: "POST",
    body: JSON.stringify({ password }),
  });

// Streaming URLs (client-side construction)
export function streamUrl(songId: string): string {
  return `${BASE}/songs/${songId}/stream.m3u8`;
}
export function audioUrl(
  songId: string,
  filename: "vocals.wav" | "no_vocals.wav"
): string {
  return `${BASE}/songs/${songId}/audio/${filename}`;
}
export function lyricsUrl(songId: string): string {
  return `${BASE}/songs/${songId}/lyrics.ass`;
}

// YouTube URL detection
export function extractYoutubeId(input: string): string | null {
  const patterns = [
    /(?:youtube\.com\/watch\?v=|youtu\.be\/)([A-Za-z0-9_-]{11})/,
    /youtube\.com\/shorts\/([A-Za-z0-9_-]{11})/,
    /^([A-Za-z0-9_-]{11})$/,
  ];
  for (const p of patterns) {
    const m = input.match(p);
    if (m) return m[1];
  }
  return null;
}

export function isYoutubeUrl(input: string): boolean {
  return /youtube\.com|youtu\.be/.test(input);
}
