import type { Room, Song, QueueItem, Guest } from "./types";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

// Module-level guest auth token, set after joinRoom succeeds
let _guestToken: string | null = null;
export const setGuestToken = (token: string | null) => { _guestToken = token; };
export const getGuestToken = () => _guestToken;

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const initHeaders: Record<string, string> =
    init?.headers && typeof init.headers === "object" && !Array.isArray(init.headers)
      ? (init.headers as Record<string, string>)
      : {};
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...initHeaders,
  };
  if (_guestToken) headers["Authorization"] = `Bearer ${_guestToken}`;
  const res = await fetch(`${BASE}${path}`, {
    credentials: "include",
    ...init,
    headers,
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
  apiFetch<Song>("/api/songs", {
    method: "POST",
    body: JSON.stringify(data),
  });

// Queue
export const getQueue = (roomId: string) =>
  apiFetch<QueueItem[]>(`/api/queue/room/${roomId}`);
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
  apiFetch<void>(`/api/queue/room/${roomId}/reorder`, {
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
  apiFetch<{ guest: Guest; access_token: string; token_type: string }>("/api/guests/join", {
    method: "POST",
    body: JSON.stringify(data),
  }).then(r => ({ guest: r.guest, token: r.access_token }));
export const getMe = () => apiFetch<Guest>("/api/guests/me");
export const getOnlineGuests = (roomId: string) =>
  apiFetch<Guest[]>(`/api/guests/online/${roomId}`);

// Admin
export const adminLogin = (password: string) =>
  apiFetch<{ access_token: string; guest: Guest }>("/api/auth/admin/login", {
    method: "POST",
    body: JSON.stringify({ password }),
  }).then((r) => ({ token: r.access_token }));

// Room stats
export interface RoomStats {
  room_id: string;
  total_songs_played: number;
  unique_songs: number;
  total_play_duration_sec: number;
  avg_rating: number | null;
  top_songs: Array<{
    song_id: string;
    title: string;
    artist: string | null;
    thumbnail_url: string | null;
    play_count: number;
    total_duration_sec: number;
  }>;
  recent_plays: Array<{
    song_id: string;
    played_at: string | null;
    duration_sec: number | null;
    rating: number | null;
  }>;
}
export const getRoomStats = (roomId: string) =>
  apiFetch<RoomStats>(`/api/rooms/${roomId}/stats`);

// Processing stats
export interface ProcessingStats {
  pending: number;
  processing: number;
  ready: number;
  failed_perm: number;
  failed_temp: number;
}
export const getProcessingStats = (roomId: string) =>
  apiFetch<ProcessingStats>(`/api/rooms/${roomId}/stats/processing`);

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

// Room admin mode
export async function verifyRoomAdmin(roomId: string, password: string): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(`/api/rooms/${roomId}/admin/verify`, {
    method: "POST",
    body: JSON.stringify({ password }),
  });
}

export async function setRoomAdminPassword(roomId: string, newPassword: string): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(`/api/rooms/${roomId}/admin-password`, {
    method: "PATCH",
    body: JSON.stringify({ new_password: newPassword }),
  });
}

export async function deleteSong(songId: string): Promise<void> {
  await apiFetch<{ status: string }>(`/api/admin/songs/${songId}`, { method: "DELETE" });
}

// Lyrics
export async function getLyricsAss(songId: string): Promise<string> {
  const base = process.env.NEXT_PUBLIC_API_URL ?? "";
  // Cache-bust so live ASS edits via WS show immediately on next subtitle init
  const res = await fetch(`${base}/songs/${songId}/lyrics.ass?t=${Date.now()}`, {
    credentials: "include",
    cache: "no-store",
  });
  if (!res.ok) return "";
  return res.text();
}

export interface LyricsSourceInfo {
  song_id: string;
  current: string | null;
  preferred: string | null;
  has_timing: boolean;
  available: Record<string, { timed: boolean }>;
  prefetched: boolean;
}

export const getLyricsSource = (songId: string) =>
  apiFetch<LyricsSourceInfo>(`/api/songs/${songId}/lyrics/source`);

export const setLyricsSource = (songId: string, source: string) =>
  apiFetch<{ ok: boolean; source: string; has_timing: boolean }>(
    `/api/songs/${songId}/lyrics/source`,
    { method: "POST", body: JSON.stringify({ source }) },
  );

// ── Per-song problem report → original-audio playback override ──────────────

export type SongIssue = "clipping" | "av_desync" | "separation_noise" | "other";

export interface SongReportInfo {
  song_id: string;
  use_original_audio: boolean;
  reports: { at: string; nickname: string | null; issue: string }[];
  report_count: number;
}

export const getSongReport = (songId: string) =>
  apiFetch<SongReportInfo>(`/api/songs/${songId}/report`);

export const reportSongIssue = (songId: string, issue: SongIssue) =>
  apiFetch<{ ok: boolean; use_original_audio: boolean; report_count: number }>(
    `/api/songs/${songId}/report`,
    { method: "POST", body: JSON.stringify({ issue }) },
  );

/** Admin only — revert to separated-audio playback (history kept). */
export const clearSongReport = (songId: string) =>
  apiFetch<{ ok: boolean; use_original_audio: boolean }>(
    `/api/songs/${songId}/report`,
    { method: "DELETE" },
  );

export async function getLyricsText(songId: string): Promise<string> {
  const base = process.env.NEXT_PUBLIC_API_URL ?? "";
  const res = await fetch(`${base}/songs/${songId}/lyrics.txt`, { credentials: "include" });
  if (!res.ok) return "";
  return res.text();
}

export const updateLyricsAss = (songId: string, ass: string) =>
  apiFetch<{ status: string; bytes: number }>(`/songs/${songId}/lyrics`, {
    method: "PUT",
    body: JSON.stringify({ ass }),
  });

// Leaderboard
export interface LeaderboardItem {
  rank: number;
  song_id: string;
  title: string;
  artist: string | null;
  thumbnail_url: string | null;
  duration_sec: number | null;
  play_count: number;
  last_played_at: string | null;
}

export type LeaderboardCategory = "all_time" | "monthly_hot" | "personal";

export const getLeaderboard = (category: LeaderboardCategory = "all_time", limit = 10) =>
  apiFetch<LeaderboardItem[]>(
    `/api/songs/leaderboard?category=${category}&limit=${limit}`
  );

// Video URL/ID detection — YouTube or Bilibili
export function extractYoutubeId(input: string): string | null {
  const s = input.trim();
  const bv = s.match(/(BV[0-9A-Za-z]{10})/);
  if (bv) return bv[1];
  const patterns = [
    /(?:youtube\.com\/watch\?v=|youtu\.be\/)([A-Za-z0-9_-]{11})/,
    /youtube\.com\/shorts\/([A-Za-z0-9_-]{11})/,
    /^([A-Za-z0-9_-]{11})$/,
  ];
  for (const p of patterns) {
    const m = s.match(p);
    if (m) return m[1];
  }
  return null;
}

/** True for a YouTube *or* Bilibili link/id — i.e. a direct-add, not a search. */
export function isYoutubeUrl(input: string): boolean {
  return /youtube\.com|youtu\.be|bilibili\.com|(?:^|\/)BV[0-9A-Za-z]{10}/.test(input);
}
// ── Admin API ─────────────────────────────────────────────────────────────────

export class AdminAuthError extends Error {}

export async function adminApiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = typeof window !== "undefined" ? localStorage.getItem("admin_token") : null;
  const initHeaders =
    init?.headers && typeof init.headers === "object" && !Array.isArray(init.headers)
      ? (init.headers as Record<string, string>)
      : {};
  const res = await fetch(`${BASE}${path}`, {
    credentials: "include",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...initHeaders,
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });
  if (res.status === 401 || res.status === 403) {
    // Token expired/invalid → drop it and tell the page to show login
    if (typeof window !== "undefined") {
      localStorage.removeItem("admin_token");
      window.dispatchEvent(new Event("admin-auth-expired"));
    }
    throw new AdminAuthError("登入已過期，請重新登入");
  }
  if (!res.ok) {
    let detail = "";
    try { detail = (await res.json())?.detail ?? ""; } catch { /* ignore */ }
    throw new Error(`${detail || `HTTP ${res.status}`}`);
  }
  return res.json() as Promise<T>;
}

export interface AdminRoomDetail {
  room: { id: string; name: string; is_default: boolean; has_password: boolean; has_admin_password: boolean; created_at: string | null };
  online_guests: Array<{ id: string; nickname: string; avatar_color: string | null; is_admin: boolean; plays_here: number; last_seen: string | null }>;
  online_count: number;
  queue: Array<{ id: number; status: string; position: number; song_id: string; title: string; artist: string | null; song_status: string | null; has_timing: boolean | null; lyrics_source: string | null; requested_by: string | null }>;
  queue_count: number;
  processing_breakdown: Record<string, number>;
  stats: { total_played: number; unique_songs: number };
}

export interface AdminGuestDetail {
  guest: { id: string; nickname: string; avatar_color: string | null; is_admin: boolean; first_seen: string | null; last_seen: string | null };
  total_plays: number;
  history: Array<{ id: string; title: string; artist: string | null; played_at: string | null; room_id: string }>;
  favorites: Array<{ id: string; title: string; artist: string | null }>;
}

export const adminGetRoomDetail = (roomId: string) =>
  adminApiFetch<AdminRoomDetail>(`/api/admin/rooms/${roomId}/detail`);

export const adminGetGuestDetail = (guestId: string) =>
  adminApiFetch<AdminGuestDetail>(`/api/admin/guests/${guestId}/detail`);

export interface AdminRoomItem {
  id: string;
  name: string;
  is_default: boolean;
  has_password: boolean;
  created_at: string | null;
  settings: Record<string, unknown> | null;
}

export interface ErrorLogEntry {
  id: number;
  occurred_at: string | null;
  category: string | null;
  severity: string | null;
  message: string;
  context: Record<string, unknown> | null;
  resolved_at: string | null;
  resolution: string | null;
}

export interface CacheStats {
  media: { bytes: number; human: string };
  cache: { bytes: number; human: string };
  logs: { bytes: number; human: string };
  tmp: { bytes: number; human: string };
  total: { bytes: number; human: string };
}

export interface SystemStatus {
  gpu: { available: boolean; name?: string; memory_total_mb?: number; memory_used_mb?: number };
  db_connected: boolean;
  db_path: string;
  pipeline: { pending_count: number };
  songs: { total: number; ready: number; failed: number };
}

export const adminListRooms = () =>
  adminApiFetch<AdminRoomItem[]>("/api/admin/rooms");

export const adminCreateRoom = (data: { id: string; name: string; password?: string }) =>
  adminApiFetch<AdminRoomItem>("/api/admin/rooms", {
    method: "POST",
    body: JSON.stringify(data),
  });

export const adminDeleteRoom = (roomId: string) =>
  adminApiFetch<{ status: string; deleted: string }>(`/api/admin/rooms/${roomId}`, {
    method: "DELETE",
  });

export const adminChangeRoomPassword = (roomId: string, password: string | null) =>
  adminApiFetch<{ status: string; room_id: string; has_password: boolean }>(
    `/api/admin/rooms/${roomId}/password`,
    { method: "PATCH", body: JSON.stringify({ password }) }
  );

export const adminListErrorLogs = (params?: { resolved?: boolean; limit?: number; offset?: number }) => {
  const qs = new URLSearchParams();
  if (params?.resolved !== undefined) qs.set("resolved", String(params.resolved));
  if (params?.limit) qs.set("limit", String(params.limit));
  if (params?.offset) qs.set("offset", String(params.offset));
  const q = qs.toString();
  return adminApiFetch<{ total: number; entries: ErrorLogEntry[] }>(
    `/api/admin/error-logs${q ? `?${q}` : ""}`
  );
};

export const adminResolveErrorLog = (logId: number, resolution?: string) =>
  adminApiFetch<{ status: string; log_id: number; resolved_at: string }>(
    `/api/admin/error-logs/${logId}/resolve`,
    { method: "POST", body: JSON.stringify({ resolution }) }
  );

export const adminResolveAllErrorLogs = () =>
  adminApiFetch<{ status: string; resolved_count: number }>(
    "/api/admin/error-logs/resolve-all",
    { method: "POST" }
  );

export interface SonglistInfo {
  total: number;
  by_lang: Record<string, { total: number; loaded: number; failed: number }>;
  progress: {
    running: boolean; lang: string; total: number; done: number;
    ok: number; failed: number; skipped: number; current: string;
  };
  songs: { lang: string; artist: string; title: string; status: string }[];
}

export const adminGetSonglist = () =>
  adminApiFetch<SonglistInfo>("/api/admin/songlist");

export const adminPreloadSonglist = (lang: string) =>
  adminApiFetch<{ started: boolean; lang: string; count: number }>(
    `/api/admin/songlist/preload?lang=${encodeURIComponent(lang)}`,
    { method: "POST" }
  );

export const adminGetCacheStats = () =>
  adminApiFetch<CacheStats>("/api/admin/cache-stats");

export const adminClearCache = (what: "all" | "cache" | "tmp" = "all") =>
  adminApiFetch<{ status: string; cleared: Array<{ dir: string; files_removed: number; bytes_freed: number }> }>(
    "/api/admin/cache/clear",
    { method: "POST", body: JSON.stringify({ what }) }
  );

export interface SavedSong {
  id: string; title: string; artist: string | null; status: string;
  play_count: number; has_timing: boolean; lyrics_source: string | null;
  duration_sec: number | null; last_played_at: string | null;
  bytes: number; human: string;
}
export const adminListSavedSongs = () =>
  adminApiFetch<{ songs: SavedSong[]; count: number; total_bytes: number; total_human: string }>(
    "/api/admin/songs"
  );
export const adminDeleteSavedSong = (songId: string) =>
  adminApiFetch<{ status: string; deleted: string }>(
    `/api/admin/songs/${songId}`, { method: "DELETE" }
  );

export const adminClearAllSongs = () =>
  adminApiFetch<{ status: string; songs: number; queue_items: number }>(
    "/api/admin/songs", { method: "DELETE" }
  );

export const adminClearLeaderboard = (roomId?: string) =>
  adminApiFetch<{ status: string; removed: number; scope: string }>(
    `/api/admin/leaderboard${roomId ? `?room_id=${roomId}` : ""}`,
    { method: "DELETE" }
  );

export const adminGetSystemStatus = () =>
  adminApiFetch<SystemStatus>("/api/admin/system-status");

// ── Library: favorites / history / recommendations ──────────────────────────

export interface LibrarySong {
  id: string;
  title: string;
  artist: string | null;
  duration_sec: number | null;
  thumbnail_url: string | null;
  status: string;
  has_timing: boolean;
  play_count: number;
  favorited: boolean;
}

export const getFavorites = () =>
  apiFetch<LibrarySong[]>("/api/library/favorites");

export const getHistory = () =>
  apiFetch<LibrarySong[]>("/api/library/history");

export const getRecommendations = () =>
  apiFetch<LibrarySong[]>("/api/library/recommendations");

export const getFavoriteStatus = (songId: string) =>
  apiFetch<{ song_id: string; favorited: boolean }>(
    `/api/library/favorites/${songId}/status`
  );

export const addFavorite = (songId: string) =>
  apiFetch<{ ok: boolean; favorited: boolean }>(
    `/api/library/favorites/${songId}`,
    { method: "POST" }
  );

export const removeFavorite = (songId: string) =>
  apiFetch<{ ok: boolean; favorited: boolean }>(
    `/api/library/favorites/${songId}`,
    { method: "DELETE" }
  );
