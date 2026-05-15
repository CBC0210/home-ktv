"""SQLAlchemy ORM Models。"""
import uuid
from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import String, Integer, Boolean, DateTime, Text, JSON, ForeignKey
from sqlalchemy.orm import relationship, Mapped, mapped_column

from .database import Base


def now_utc():
    return datetime.now(timezone.utc)


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    password_hash: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    # Separate password for Remote admin-mode (queue/DB elevated ops).
    # Changeable from /admin web page. Default seeded at startup when NULL.
    admin_password_hash: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    created_by: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    settings: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    queue_items: Mapped[List["QueueItem"]] = relationship(back_populates="room")


class Guest(Base):
    __tablename__ = "guests"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    nickname: Mapped[str] = mapped_column(String(64), nullable=False)
    avatar_color: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)

    queue_items: Mapped[List["QueueItem"]] = relationship(back_populates="guest")
    play_history: Mapped[List["PlayHistory"]] = relationship(back_populates="guest")
    favorites: Mapped[List["Favorite"]] = relationship(back_populates="guest")


class Song(Base):
    __tablename__ = "songs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    artist: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    duration_sec: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    last_played_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    play_count: Mapped[int] = mapped_column(Integer, default=0)
    files: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    lyrics_source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    lyrics_quality: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    has_timing: Mapped[bool] = mapped_column(Boolean, default=False)
    extra_metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    queue_items: Mapped[List["QueueItem"]] = relationship(back_populates="song")
    play_history: Mapped[List["PlayHistory"]] = relationship(back_populates="song")
    favorites: Mapped[List["Favorite"]] = relationship(back_populates="song")


class QueueItem(Base):
    __tablename__ = "queue_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    room_id: Mapped[str] = mapped_column(String(64), ForeignKey("rooms.id"), nullable=False)
    song_id: Mapped[str] = mapped_column(String(64), ForeignKey("songs.id"), nullable=False)
    guest_id: Mapped[str] = mapped_column(String(64), ForeignKey("guests.id"), nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    played_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    manually_moved: Mapped[bool] = mapped_column(Boolean, default=False)
    last_heartbeat: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    room: Mapped["Room"] = relationship("Room", back_populates="queue_items")
    song: Mapped["Song"] = relationship("Song", back_populates="queue_items")
    guest: Mapped["Guest"] = relationship("Guest", back_populates="queue_items")


class PlayHistory(Base):
    __tablename__ = "play_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    song_id: Mapped[str] = mapped_column(String(64), ForeignKey("songs.id"), nullable=False)
    guest_id: Mapped[str] = mapped_column(String(64), ForeignKey("guests.id"), nullable=False)
    room_id: Mapped[str] = mapped_column(String(64), ForeignKey("rooms.id"), nullable=False)
    played_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    duration_sec: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    reactions: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    song: Mapped["Song"] = relationship("Song", back_populates="play_history")
    guest: Mapped["Guest"] = relationship("Guest", back_populates="play_history")


class Favorite(Base):
    __tablename__ = "favorites"

    guest_id: Mapped[str] = mapped_column(String(64), ForeignKey("guests.id"), primary_key=True)
    song_id: Mapped[str] = mapped_column(String(64), ForeignKey("songs.id"), primary_key=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)

    guest: Mapped["Guest"] = relationship("Guest", back_populates="favorites")
    song: Mapped["Song"] = relationship("Song", back_populates="favorites")


class ErrorLog(Base):
    __tablename__ = "error_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=now_utc)
    category: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    severity: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
