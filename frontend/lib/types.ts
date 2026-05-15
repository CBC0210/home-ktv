export interface Room {
  id: string;
  name: string;
  has_password: boolean;
  is_default: boolean;
  created_at: string;
  settings: Record<string, unknown>;
}

export interface Song {
  id: string;
  title: string;
  artist: string | null;
  duration_sec: number | null;
  thumbnail_url: string | null;
  processed_at: string | null;
  last_played_at: string | null;
  play_count: number;
  lyrics_source: string | null;
  lyrics_quality: string | null;
  has_timing: boolean;
  status:
    | "pending"
    | "downloading"
    | "separating"
    | "fetching_lyrics"
    | "aligning"
    | "packaging"
    | "ready"
    | "failed_temp"
    | "failed_perm";
  error_message: string | null;
  files: Record<string, string> | null;
  metadata: Record<string, unknown> | null;
}

export interface Guest {
  id: string;
  nickname: string;
  avatar_color: string | null;
  is_admin: boolean;
}

export interface QueueItem {
  id: number;
  room_id: string;
  song_id: string;
  guest_id: string;
  added_at: string;
  position: number;
  status: string;
  played_at: string | null;
  manually_moved: boolean;
  song?: Song;
  guest?: Guest;
}

export interface PlaybackState {
  is_playing: boolean;
  current_song_id: string | null;
  current_queue_item_id: number | null;
  position_sec: number;
  main_volume: number;
  vocal_volume: number;
  pitch_semitones: number;
  speed_rate: number;
}

export type ServerEvent =
  | { type: "queue.updated"; queue: QueueItem[] }
  | { type: "song.started"; song: Song; queueItem: QueueItem }
  | { type: "song.progress"; positionSec: number }
  | { type: "song.ended"; queueItemId: number }
  | {
      type: "song.processing";
      queueItemId: number;
      stage: string;
      percent: number;
    }
  | { type: "guests.updated"; guests: Guest[] }
  | { type: "playback.state"; state: PlaybackState }
  | { type: "reaction"; emoji: string; from: string }
  | { type: "activity"; text: string; actor: string }
  | { type: "system.error"; message: string }
  | { type: "system.restarted" }
  | { type: "lyrics.updated"; songId: string }
  // Commands forwarded from Remote → Server → Player
  | { type: "playback.play" }
  | { type: "playback.pause" }
  | { type: "playback.seek"; positionSec: number }
  | { type: "playback.skip" }
  | { type: "playback.replay" }
  | { type: "playback.setVolume"; main?: number; vocal?: number };

export type ClientCommand =
  | { type: "queue.add"; youtubeId: string; position?: "end" | "next" }
  | { type: "queue.remove"; queueItemId: number }
  | { type: "queue.reorder"; queueItemIds: number[] }
  | { type: "playback.play" }
  | { type: "playback.pause" }
  | { type: "playback.skip" }
  | { type: "playback.replay" }
  | { type: "playback.seek"; positionSec: number }
  | { type: "playback.setVolume"; main?: number; vocal?: number }
  | { type: "playback.setPitch"; semitones: number }
  | { type: "playback.setSpeed"; rate: number }
  | { type: "reaction.send"; emoji: string }
  | { type: "lyrics.edit"; songId: string; ass: string }
  | { type: "guest.updateNickname"; nickname: string };

export interface GuestSession {
  guest: Guest;
  token: string;
  roomId: string;
}
