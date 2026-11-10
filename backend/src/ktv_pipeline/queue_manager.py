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

    # Statuses that mean a queue item is still active (visible in the queue).
    ACTIVE_STATUSES = [
        "playing", "pending", "processing", "ready",
        # Pipeline stages — written by PipelineOrchestrator._update_state
        "downloading", "separating", "fetching_lyrics", "aligning", "packaging",
    ]

    def get_queue(self, room_id: str) -> List[QueueItem]:
        """Return the current queue for a room, ordered by position.

        Includes playing + every state where a song is still working toward
        being playable. Excludes done / failed.
        """
        return (
            self.session.query(QueueItem)
            .filter_by(room_id=room_id)
            .filter(QueueItem.status.in_(self.ACTIVE_STATUSES))
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
        if self.session.query(QueueItem).filter(QueueItem.room_id == room_id, QueueItem.status.in_(self.ACTIVE_STATUSES)).count() >= 200:
            raise ValueError("Room queue is full (200 songs)")
        # Verify song exists
        song = self.session.query(Song).filter_by(id=song_id).first()
        if not song:
            raise ValueError(f"Song {song_id} not found")

        # Duplicate guard — but the CURRENTLY-PLAYING song is fair game:
        # spec §6.2's「🔁 加回隊列」re-queues the song being sung right now.
        dup_statuses = [s for s in self.ACTIVE_STATUSES if s != "playing"]
        existing = self.session.query(QueueItem).filter(
            QueueItem.room_id == room_id,
            QueueItem.song_id == song_id,
            QueueItem.status.in_(dup_statuses),
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

    def apply_fair_order(self, room_id: str) -> List[QueueItem]:
        """Materialise fair rotation into queue POSITIONS (spec §4.3).

        Rotation used to be applied only at pick time (pick_next_ready), so
        the TV's「下一首」HUD and every Remote's queue list showed plain
        insertion order — NOT the order songs would actually play. This
        rewrites positions so that displayed order == play order; it is
        deterministic and idempotent, and is re-run (then broadcast) on every
        queue change.

        Slot rules (same spirit as the old pick-time logic):
        - Walk the waiting list slot by slot; each slot takes the earliest
          non-pinned item whose requester is NOT in the recent window
          (last RECENT_WINDOW completed plays + the current singer, sliding
          as slots are assigned). If everyone is "recent", position order.
        - manually_moved items are PINNED to their current rank untouched.
        """
        playing = self.get_currently_playing(room_id)
        items = [qi for qi in self.get_queue(room_id) if qi.status != "playing"]

        if len(items) > 1:
            pinned = {rank: qi for rank, qi in enumerate(items) if qi.manually_moved}
            pool = [qi for qi in items if not qi.manually_moved]
            recent = self._get_recent_guests(room_id, limit=self.RECENT_WINDOW)
            if playing is not None:
                recent = [playing.guest_id] + recent
            ordered: List[QueueItem] = []
            for rank in range(len(items)):
                chosen = pinned.get(rank)
                if chosen is None:
                    window = set(recent[: self.RECENT_WINDOW])
                    chosen = next(
                        (qi for qi in pool if qi.guest_id not in window),
                        pool[0] if pool else None,
                    )
                    pool.remove(chosen)
                ordered.append(chosen)
                recent = [chosen.guest_id] + recent  # simulate this play
            items = ordered

        # Renumber sequentially: playing item first, then the fair order.
        pos = 1
        if playing is not None:
            playing.position = pos
            pos += 1
        for qi in items:
            qi.position = pos
            pos += 1
        self.session.commit()
        return ([playing] if playing else []) + items

    def pick_next_ready(self, room_id: str) -> Optional[QueueItem]:
        """Pick the next item to play: the first READY one in display order.

        Fair rotation lives in apply_fair_order (re-applied here right before
        picking), so what plays is exactly what the queue displays showed.
        """
        self.apply_fair_order(room_id)
        from ktv_pipeline.playback_assets import playback_assets_ready
        candidates = (
            self.session.query(QueueItem)
            .join(Song, Song.id == QueueItem.song_id)
            .filter(QueueItem.room_id == room_id, QueueItem.status == "ready")
            .filter(Song.status == "ready")
            .order_by(QueueItem.position)
            .all()
        )
        for item in candidates:
            if playback_assets_ready(self.session.get(Song, item.song_id)):
                return item
            log.warning("Skipping incomplete ready item %s (%s)", item.id, item.song_id)
        return None

    def mark_playing(self, item_id: int) -> Optional[QueueItem]:
        """Mark a queue item as 'playing'."""
        # Clear any existing playing item for this room
        item = self.session.query(QueueItem).filter_by(id=item_id).first()
        if not item:
            return None
        from ktv_pipeline.playback_assets import playback_assets_ready
        song = self.session.get(Song, item.song_id)
        if item.status != "ready" or not song or song.status != "ready" or not playback_assets_ready(song):
            return None
        # Clear previous playing
        self.session.query(QueueItem).filter_by(
            room_id=item.room_id, status="playing"
        ).update({"status": "done"})
        item.status = "playing"
        self.session.commit()
        self.session.refresh(item)
        return item

    def mark_done(self, item_id: int, completed: bool = True) -> None:
        """Mark a queue item as done.

        Play history + play_count are recorded only when ``completed`` is True.
        Per spec §9.1 a play counts as completed once ≥80% was sung, so an
        early skip (``completed=False``) marks the item done without inserting
        a PlayHistory row or bumping play_count — keeping leaderboards honest.
        """
        item = self.session.query(QueueItem).filter_by(id=item_id).first()
        if not item:
            return
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        item.status = "done"
        item.played_at = now

        if completed:
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
            QueueItem.status.in_(self.ACTIVE_STATUSES),
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
