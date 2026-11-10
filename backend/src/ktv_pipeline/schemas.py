"""Pydantic Schemas（request/response models）。"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ── Auth / Session ────────────────────────────────────────────────────────────

class SessionOut(BaseModel):
    """Returned after a guest joins / logs in — contains the JWT token."""
    access_token: str
    token_type: str = "bearer"
    guest: "GuestOut"


class GuestJoin(BaseModel):
    """Used when a guest joins a room.

    The frontend historically sends `password`; older code expected
    `room_password`. Accept both so a password-protected room works
    regardless of which field the client (incl. cached bundles) sends.
    """
    nickname: str = Field(min_length=1, max_length=64)
    room_id: str
    room_password: Optional[str] = None
    password: Optional[str] = None

    @property
    def effective_password(self) -> Optional[str]:
        return self.room_password or self.password


# ── Health ────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    app: str = "ktv-backend"
    version: str = "0.1.0"


# ── Room ─────────────────────────────────────────────────────────────────────

class RoomBase(BaseModel):
    id: str
    name: str


class RoomCreate(RoomBase):
    password: Optional[str] = None


class RoomOut(RoomBase):
    model_config = ConfigDict(from_attributes=True)

    is_default: bool
    created_at: datetime
    settings: Optional[dict] = None
    has_password: bool = False  # True if room is password-protected (not the hash itself)


class RoomIn(BaseModel):
    """Internal — Room with computed has_password."""
    id: str
    name: str
    is_default: bool
    created_at: datetime
    settings: Optional[dict] = None
    has_password: bool = False


# ── Guest ─────────────────────────────────────────────────────────────────────

class GuestBase(BaseModel):
    nickname: str = Field(min_length=1, max_length=64)


class GuestCreate(GuestBase):
    room_id: str
    password: Optional[str] = None


class GuestOut(GuestBase):
    model_config = ConfigDict(from_attributes=True)

    id: str
    avatar_color: Optional[str] = None
    is_admin: bool
    first_seen: datetime
    last_seen: datetime


# ── Song ──────────────────────────────────────────────────────────────────────

class SongCreate(BaseModel):
    youtube_url: str = Field(min_length=1, max_length=2048)
    room_id: str
    position: Optional[str] = "end"


class SongOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    artist: Optional[str] = None
    duration_sec: Optional[int] = None
    thumbnail_url: Optional[str] = None
    status: str = "pending"
    error_message: Optional[str] = None
    processed_at: datetime
    last_played_at: Optional[datetime] = None
    play_count: int = 0
    has_timing: bool = False
    lyrics_quality: Optional[str] = None
    lyrics_source: Optional[str] = None


# ── Queue ──────────────────────────────────────────────────────────────────────

class SongInQueue(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    artist: Optional[str] = None
    duration_sec: Optional[int] = None
    thumbnail_url: Optional[str] = None
    status: str
    has_timing: bool = False
    lyrics_source: Optional[str] = None
    # Playback tuning (Song model properties over extra_metadata) — must match
    # what the WS song.started event carries, for the Player's REST restore.
    use_original_audio: bool = False
    subtitle_offset_ms: int = 0
    av_offset_ms: int = 0


class GuestInQueue(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    nickname: str = Field(min_length=1, max_length=64)
    avatar_color: Optional[str] = None
    is_admin: bool = False


class QueueItemCreate(BaseModel):
    song_id: str
    position: Optional[str] = "end"


class QueueItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    song_id: str
    guest_id: str
    added_at: datetime
    position: int
    status: str
    played_at: Optional[datetime] = None
    manually_moved: bool = False
    song: Optional[SongInQueue] = None
    guest: Optional[GuestInQueue] = None


# Update forward ref
SessionOut.model_rebuild()