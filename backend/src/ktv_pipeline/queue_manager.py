"""Queue management — ordering, fair rotation, song-to-play selection."""
from __future__ import annotations

import logging
from typing import Optional, List, Tuple

from sqlalchemy.orm import Session

from ktv_pipeline.models import QueueItem, Song, Guest, PlayHistory

log = logging.getLogger(__name__)


class QueueManager:
    """Manages the queue with fair rotation ordering.

    The fair rotation algorithm:
    - When adding a song, it goes to the end (position = max + 1).
    - When picking the next song to play, prefer guests who haven't played recently.
    - A guest is "recent" if their last played song was within the last N songs played.
    - `manually_moved=True` items respect the manually set position and are not reordered.
    """

    # Number of recent songs considered "recent" for rotation purposes
    RECENT_WINDOW = 4

    def __init__(self, session: Session):
        self.session = session

    def get_queue(self, room_id: str) -> List[QueueItem]:
        """Return the current queue for a room, ordered by position.

        Includes pending (waiting for pipeline), processing (pipeline running),
        and ready (processed, waiting to play) items. Excludes playing/done/failed.
        """
        return (
            self.session.query(QueueItem)
            .filter_by(room_id=room_id)
            .filter(QueueItem.status.in_(["playing", "pending", "processing", "ready"]))
            .order_by(QueueItem.position)
            .all()
        )

    def add_song(
        self,
        room_id: str,
        song_id: str,
        guest_id: str,
        position: str = "end",
    ) -> QueueItem:
        """Add a song to the queue. Returns the new QueueItem.

        position: "end" (default), "next" (after current position), or integer position
        """
        # Verify song exists
        song = self.session.query(Song).filter_by(id=song_id).first()
        if not song:
            raise ValueError(f"Song {song_id} not found")

        existing = self.session.query(QueueItem).filter(
            QueueItem.room_id == room_id,
            QueueItem.song_id == song_id,
            QueueItem.status.in_(["pending", "processing", "ready", "playing"]),
        ).first()
        if existing:
            raise ValueError(f"Song {song_id} already in queue (status={existing.status}, id={existing.id})")

        if position == "end":
            max_pos = self._get_max_position(room_id)
            new_pos = max_pos + 1
        elif position == "next":
            # Insert right after the current "playing" item
            current = self.session.query(QueueItem).filter_by(
                room_id=room_id, status="playing"
            ).first()
            base_pos = current.position + 1 if current else 1
            # Shift all items at or after base_pos up by 1
            self._shift_positions(room_id, base_pos, shift=+1)
            new_pos = base_pos
        else:
            # position is a specific integer
            new_pos = int(position)
            self._shift_positions(room_id, new_pos, shift=+1)

        # If song is already processed, start it as "ready" not "pending"
        initial_status = "ready" if (song and song.status == "ready") else "pending"
        item = QueueItem(
            room_id=room_id,
            song_id=song_id,
            guest_id=guest_id,
            position=new_pos,
            status=initial_status,
        )
        self.session.add(item)
        self.session.commit()
        self.session.refresh(item)
        return item

    def remove_item(self, item_id: int) -> bool:
        """Remove a queue item by ID. Returns True if removed."""
        item = self.session.query(QueueItem).filter_by(id=item_id).first()
        if not item:
            return False
        self.session.delete(item)
        self.session.commit()
        return True

    def reorder(self, room_id: str, ordered_item_ids: List[int]) -> None:
        """Reorder the queue by setting positions to match the order in `ordered_item_ids`."""
        for idx, item_id in enumerate(ordered_item_ids, start=1):
            item = self.session.query(QueueItem).filter_by(id=item_id, room_id=room_id).first()
            if item:
                item.position = idx
                item.manually_moved = True
        self.session.commit()

    def select_next_item(self, room_id: str) -> Optional[QueueItem]:
        """Select the next item to play using fair rotation.

        Returns the next QueueItem or None if queue is empty.
        """
        queue = self.get_queue(room_id)
        if not queue:
            return None

        # Find who played most recently
        recent_guest_ids = self._get_recent_guests(room_id, limit=self.RECENT_WINDOW)

        # Try to pick from a guest not in the recent list (fair rotation)
        candidates = [item for item in queue if item.guest_id not in recent_guest_ids]
        if candidates:
            return candidates[0]  # Already sorted by position

        # Fall back to position order (no fair rotation available)
        return queue[0]

    def mark_playing(self, item_id: int) -> Optional[QueueItem]:
        """Mark a queue item as 'playing'."""
        # Clear any existing playing item for this room
        item = self.session.query(QueueItem).filter_by(id=item_id).first()
        if not item:
            return None
        # Clear previous playing
        self.session.query(QueueItem).filter_by(
            room_id=item.room_id, status="playing"
        ).update({"status": "done"})
        item.status = "playing"
        self.session.commit()
        self.session.refresh(item)
        return item

    def mark_done(self, item_id: int) -> None:
        """Mark a queue item as done and record play history."""
        item = self.session.query(QueueItem).filter_by(id=item_id).first()
        if not item:
            return
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        item.status = "done"
        item.played_at = now

        song = self.session.query(Song).filter_by(id=item.song_id).first()
        history = PlayHistory(
            song_id=item.song_id,
            guest_id=item.guest_id,
            room_id=item.room_id,
            played_at=now,
            duration_sec=song.duration_sec if song else None,
        )
        self.session.add(history)

        if song:
            song.play_count = (song.play_count or 0) + 1
            song.last_played_at = now

        self.session.commit()

    def get_currently_playing(self, room_id: str) -> Optional[QueueItem]:
        return self.session.query(QueueItem).filter_by(
            room_id=room_id, status="playing"
        ).first()

    def _get_max_position(self, room_id: str) -> int:
        result = self.session.query(QueueItem.position).filter_by(room_id=room_id).order_by(
            QueueItem.position.desc()
        ).first()
        return result[0] if result else 0

    def _shift_positions(self, room_id: str, from_pos: int, shift: int) -> None:
        items = self.session.query(QueueItem).filter(
            QueueItem.room_id == room_id,
            QueueItem.position >= from_pos,
            QueueItem.status.in_(["pending", "processing"]),
        ).all()
        for item in items:
            item.position += shift

    def _get_recent_guests(self, room_id: str, limit: int = 4) -> List[str]:
        """Return guest IDs of the most recently played songs (for fair rotation)."""
        played = (
            self.session.query(PlayHistory.guest_id)
            .filter_by(room_id=room_id)
            .order_by(PlayHistory.played_at.desc())
            .limit(limit)
            .all()
        )
        return [p.guest_id for p in played]