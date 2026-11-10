"""Tests for queue_manager.py — fair rotation, add/remove/reorder."""
import pytest
from datetime import datetime, timezone

from ktv_pipeline.queue_manager import QueueManager
from ktv_pipeline.database import get_db_session
from ktv_pipeline.models import Room, Guest, Song, QueueItem, PlayHistory


@pytest.fixture
def session():
    with get_db_session() as sess:
        # Full cleanup — delete ALL data for test room (prevents position conflicts)
        sess.query(QueueItem).filter_by(room_id="test-queue-room").delete(synchronize_session=False)
        sess.query(PlayHistory).filter_by(room_id="test-queue-room").delete(synchronize_session=False)
        sess.query(Room).filter_by(id="test-queue-room").delete(synchronize_session=False)
        sess.query(Guest).filter(Guest.nickname.in_(["Alice", "Bob", "Carol"])).delete(synchronize_session=False)
        sess.query(Song).filter(Song.id.in_(["song1", "song2", "song3"])).delete(synchronize_session=False)
        sess.commit()
        yield sess


@pytest.fixture
def setup_room(session):
    room = Room(id="test-queue-room", name="Test Room")
    guest_alice = Guest(nickname="Alice", avatar_color="#7c3aed")
    guest_bob = Guest(nickname="Bob", avatar_color="#059669")
    guest_carol = Guest(nickname="Carol", avatar_color="#dc2626")
    song1 = Song(id="song1", title="Song One", artist="Artist A")
    song2 = Song(id="song2", title="Song Two", artist="Artist B")
    song3 = Song(id="song3", title="Song Three", artist="Artist C")
    session.add_all([room, guest_alice, guest_bob, guest_carol, song1, song2, song3])
    session.commit()
    return {"room_id": room.id, "alice": guest_alice, "bob": guest_bob, "carol": guest_carol}


def _prepare_ready(session, item):
    from ktv_pipeline.config import settings
    song = session.get(Song, item.song_id)
    song.status = "ready"
    item.status = "ready"
    video = settings.data_dir / "media" / item.song_id / "video.mp4"
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(b"video fixture")
    audio = settings.data_dir / "cache" / "demucs" / item.song_id
    audio.mkdir(parents=True, exist_ok=True)
    for stem in ("vocals", "no_vocals"):
        (audio / (stem + ".opus")).write_bytes(b"audio fixture")
    session.commit()


class TestAddToQueue:
    def test_add_song_end(self, session, setup_room):
        mgr = QueueManager(session)
        item = mgr.add_song(room_id="test-queue-room", song_id="song1", guest_id=setup_room["alice"].id)
        assert item.position == 1
        assert item.status == "pending"
        assert item.song_id == "song1"

    def test_add_multiple_songs_increments_position(self, session, setup_room):
        mgr = QueueManager(session)
        item1 = mgr.add_song(room_id="test-queue-room", song_id="song1", guest_id=setup_room["alice"].id)
        item2 = mgr.add_song(room_id="test-queue-room", song_id="song2", guest_id=setup_room["bob"].id)
        assert item2.position > item1.position

    def test_add_duplicate_song_raises(self, session, setup_room):
        mgr = QueueManager(session)
        mgr.add_song(room_id="test-queue-room", song_id="song1", guest_id=setup_room["alice"].id)
        with pytest.raises(ValueError, match="already in queue"):
            mgr.add_song(room_id="test-queue-room", song_id="song1", guest_id=setup_room["bob"].id)

    def test_add_nonexistent_song_raises(self, session, setup_room):
        mgr = QueueManager(session)
        with pytest.raises(ValueError, match="not found"):
            mgr.add_song(room_id="test-queue-room", song_id="nonexistent", guest_id=setup_room["alice"].id)


class TestPickNextReady:
    """Fair-rotation selection over READY items (spec §4.3)."""

    def _make_ready(self, session, room_id, song_id, guest_id):
        item = QueueItem(room_id=room_id, song_id=song_id, guest_id=guest_id,
                         position=QueueManager(session)._get_max_position(room_id) + 1,
                         status="ready")
        session.add(item)
        session.commit()
        session.refresh(item)
        _prepare_ready(session, item)
        return item

    def test_pick_returns_none_when_no_ready(self, session, setup_room):
        mgr = QueueManager(session)
        # A pending item is not ready → nothing to pick.
        mgr.add_song(room_id="test-queue-room", song_id="song1", guest_id=setup_room["alice"].id)
        assert mgr.pick_next_ready("test-queue-room") is None

    def test_pick_skips_recent_singer_for_fairness(self, session, setup_room):
        """Alice just sang; with Alice's and Bob's songs both ready, Bob's is
        picked next even though Alice's has the earlier position."""
        alice, bob = setup_room["alice"].id, setup_room["bob"].id
        a1 = self._make_ready(session, "test-queue-room", "song1", alice)
        b1 = self._make_ready(session, "test-queue-room", "song2", bob)
        # Record that Alice just played something (makes her "recent").
        session.add(PlayHistory(song_id="song3", guest_id=alice,
                                room_id="test-queue-room",
                                played_at=datetime.now(timezone.utc)))
        session.commit()
        picked = QueueManager(session).pick_next_ready("test-queue-room")
        assert picked.id == b1.id  # Bob gets a turn, not Alice's earlier song

    def test_manually_moved_is_honored_even_if_recent(self, session, setup_room):
        """A manually-moved song at the front plays next regardless of rotation."""
        alice = setup_room["alice"].id
        a1 = self._make_ready(session, "test-queue-room", "song1", alice)
        a1.manually_moved = True
        session.add(PlayHistory(song_id="song3", guest_id=alice,
                                room_id="test-queue-room",
                                played_at=datetime.now(timezone.utc)))
        session.commit()
        picked = QueueManager(session).pick_next_ready("test-queue-room")
        assert picked.id == a1.id


class TestMarkDoneCompletion:
    """§9.1 — only a ≥80% play records history / bumps play_count."""

    def test_completed_records_history_and_count(self, session, setup_room):
        mgr = QueueManager(session)
        item = mgr.add_song(room_id="test-queue-room", song_id="song1", guest_id=setup_room["alice"].id)
        mgr.mark_done(item.id, completed=True)
        hist = session.query(PlayHistory).filter_by(room_id="test-queue-room", song_id="song1").count()
        song = session.query(Song).filter_by(id="song1").first()
        assert hist == 1
        assert (song.play_count or 0) == 1

    def test_incomplete_skip_does_not_record(self, session, setup_room):
        mgr = QueueManager(session)
        item = mgr.add_song(room_id="test-queue-room", song_id="song2", guest_id=setup_room["bob"].id)
        mgr.mark_done(item.id, completed=False)
        hist = session.query(PlayHistory).filter_by(room_id="test-queue-room", song_id="song2").count()
        song = session.query(Song).filter_by(id="song2").first()
        assert hist == 0
        assert (song.play_count or 0) == 0
        # …but the queue item is still marked done.
        assert session.query(QueueItem).filter_by(id=item.id).first().status == "done"


class TestRemoveFromQueue:
    def test_remove_existing_item(self, session, setup_room):
        mgr = QueueManager(session)
        item = mgr.add_song(room_id="test-queue-room", song_id="song1", guest_id=setup_room["alice"].id)
        result = mgr.remove_item(item.id)
        assert result is True
        remaining = mgr.get_queue("test-queue-room")
        assert len(remaining) == 0

    def test_remove_nonexistent_item(self, session):
        mgr = QueueManager(session)
        result = mgr.remove_item(99999)
        assert result is False


class TestReorder:
    def test_reorder_sets_positions(self, session, setup_room):
        mgr = QueueManager(session)
        item1 = mgr.add_song(room_id="test-queue-room", song_id="song1", guest_id=setup_room["alice"].id)
        item2 = mgr.add_song(room_id="test-queue-room", song_id="song2", guest_id=setup_room["bob"].id)
        item3 = mgr.add_song(room_id="test-queue-room", song_id="song3", guest_id=setup_room["carol"].id)

        # Reorder: item3, item1, item2
        mgr.reorder("test-queue-room", [item3.id, item1.id, item2.id])

        # Verify new positions
        session.expire_all()
        item1_new = session.query(QueueItem).filter_by(id=item1.id).first()
        item2_new = session.query(QueueItem).filter_by(id=item2.id).first()
        item3_new = session.query(QueueItem).filter_by(id=item3.id).first()
        assert item1_new.position == 2
        assert item2_new.position == 3
        assert item3_new.position == 1

    def test_reorder_marks_manually_moved(self, session, setup_room):
        mgr = QueueManager(session)
        item1 = mgr.add_song(room_id="test-queue-room", song_id="song1", guest_id=setup_room["alice"].id)
        item2 = mgr.add_song(room_id="test-queue-room", song_id="song2", guest_id=setup_room["bob"].id)
        mgr.reorder("test-queue-room", [item2.id, item1.id])
        session.expire_all()
        item1_updated = session.query(QueueItem).filter_by(id=item1.id).first()
        assert item1_updated.manually_moved is True


class TestSelectNext:
    def test_select_next_empty_queue(self, session, setup_room):
        mgr = QueueManager(session)
        result = mgr.select_next_item("test-queue-room")
        assert result is None

    def test_select_next_simple_fair_rotation(self, session, setup_room):
        """Test fair rotation: Alice played recently, Carol hasn't — Carol is picked.

        After Alice's song finishes (with PlayHistory entry), both Bob and Carol
        have items in the queue. Bob also has a PlayHistory entry, so Carol wins
        by being the only guest without recent playback.
        """
        mgr = QueueManager(session)
        item1 = mgr.add_song(room_id="test-queue-room", song_id="song1", guest_id=setup_room["alice"].id)
        item2 = mgr.add_song(room_id="test-queue-room", song_id="song2", guest_id=setup_room["bob"].id)
        item3 = mgr.add_song(room_id="test-queue-room", song_id="song3", guest_id=setup_room["carol"].id)

        # Add PlayHistory for both Alice AND Bob (simulating they played before)
        for guest_id in [setup_room["alice"].id, setup_room["bob"].id]:
            history = PlayHistory(
                song_id="song1",
                guest_id=guest_id,
                room_id="test-queue-room",
                played_at=datetime.now(timezone.utc),
            )
            session.add(history)
        session.commit()

        # Alice and Bob already in recent guests (from PlayHistory added above).
        # Carol has NOT played recently and has no PlayHistory entry.
        # Fair rotation should pick Carol (the only candidate not in recent list).
        # Both alice and bob are in recent, so position order is irrelevant.
        selected = mgr.select_next_item("test-queue-room")
        assert selected.id == item3.id

        # Mark item1 as done (Alice's song finished playing)
        _prepare_ready(session, item1)
        mgr.mark_playing(item1.id)
        mgr.mark_done(item1.id)

        # Carol hasn't played (no PlayHistory), Bob has → Carol should be picked
        selected2 = mgr.select_next_item("test-queue-room")
        assert selected2.id == item3.id

    def test_select_next_respects_manually_moved(self, session, setup_room):
        """Manually reordered items respect their order."""
        mgr = QueueManager(session)
        item1 = mgr.add_song(room_id="test-queue-room", song_id="song1", guest_id=setup_room["alice"].id)
        item2 = mgr.add_song(room_id="test-queue-room", song_id="song2", guest_id=setup_room["bob"].id)
        item3 = mgr.add_song(room_id="test-queue-room", song_id="song3", guest_id=setup_room["carol"].id)

        # Carol moved to first manually
        mgr.reorder("test-queue-room", [item3.id, item1.id, item2.id])

        selected = mgr.select_next_item("test-queue-room")
        assert selected.id == item3.id


class TestMarkPlaying:
    def test_mark_playing_clears_previous_playing(self, session, setup_room):
        mgr = QueueManager(session)
        item1 = mgr.add_song(room_id="test-queue-room", song_id="song1", guest_id=setup_room["alice"].id)
        item2 = mgr.add_song(room_id="test-queue-room", song_id="song2", guest_id=setup_room["bob"].id)

        _prepare_ready(session, item1)
        mgr.mark_playing(item1.id)
        _prepare_ready(session, item2)
        mgr.mark_playing(item2.id)

        session.expire_all()
        item1_updated = session.query(QueueItem).filter_by(id=item1.id).first()
        assert item1_updated.status == "done"

class TestApplyFairOrder:
    """apply_fair_order materialises rotation into positions, so what the TV
    「下一首」HUD and the Remote queue display IS the real play order."""

    def _titles_in_order(self, session, room_id):
        mgr = QueueManager(session)
        return [qi.guest_id for qi in mgr.get_queue(room_id) if qi.status != "playing"]

    def test_interleaves_consecutive_songs_from_same_guest(self, session, setup_room):
        mgr = QueueManager(session)
        a, b = setup_room["alice"].id, setup_room["bob"].id
        mgr.add_song(room_id="test-queue-room", song_id="song1", guest_id=a)
        mgr.add_song(room_id="test-queue-room", song_id="song2", guest_id=a)
        mgr.add_song(room_id="test-queue-room", song_id="song3", guest_id=b)
        ordered = mgr.apply_fair_order("test-queue-room")
        guests = [qi.guest_id for qi in ordered]
        # Alice's second song must NOT come directly after her first —
        # Bob's slots in between.
        assert guests[0] == a
        assert guests[1] == b
        assert guests[2] == a
        # And the stored positions reflect exactly that order.
        assert self._titles_in_order(session, "test-queue-room") == guests

    def test_idempotent(self, session, setup_room):
        mgr = QueueManager(session)
        a, b = setup_room["alice"].id, setup_room["bob"].id
        mgr.add_song(room_id="test-queue-room", song_id="song1", guest_id=a)
        mgr.add_song(room_id="test-queue-room", song_id="song2", guest_id=a)
        mgr.add_song(room_id="test-queue-room", song_id="song3", guest_id=b)
        first = [qi.id for qi in mgr.apply_fair_order("test-queue-room")]
        second = [qi.id for qi in mgr.apply_fair_order("test-queue-room")]
        assert first == second

    def test_manually_moved_stays_pinned(self, session, setup_room):
        mgr = QueueManager(session)
        a, b = setup_room["alice"].id, setup_room["bob"].id
        i1 = mgr.add_song(room_id="test-queue-room", song_id="song1", guest_id=a)
        i2 = mgr.add_song(room_id="test-queue-room", song_id="song2", guest_id=a)
        mgr.add_song(room_id="test-queue-room", song_id="song3", guest_id=b)
        # User dragged Alice's second song to stay right after her first.
        i2_db = session.query(QueueItem).filter_by(id=i2.id).first()
        i2_db.manually_moved = True
        session.commit()
        ordered = mgr.apply_fair_order("test-queue-room")
        # Pinned at rank 1 (its current rank) — rotation must not move it.
        assert ordered[1].id == i2.id

    def test_pick_next_ready_agrees_with_display_order(self, session, setup_room):
        mgr = QueueManager(session)
        a, b = setup_room["alice"].id, setup_room["bob"].id
        i1 = mgr.add_song(room_id="test-queue-room", song_id="song1", guest_id=a)
        i2 = mgr.add_song(room_id="test-queue-room", song_id="song2", guest_id=a)
        i3 = mgr.add_song(room_id="test-queue-room", song_id="song3", guest_id=b)
        for qi_id in (i1.id, i2.id, i3.id):
            _prepare_ready(session, session.get(QueueItem, qi_id))
        session.commit()
        displayed = mgr.apply_fair_order("test-queue-room")
        picked = mgr.pick_next_ready("test-queue-room")
        assert picked.id == displayed[0].id

    def test_current_singer_counts_as_recent(self, session, setup_room):
        mgr = QueueManager(session)
        a, b = setup_room["alice"].id, setup_room["bob"].id
        i1 = mgr.add_song(room_id="test-queue-room", song_id="song1", guest_id=a)
        _prepare_ready(session, i1)
        mgr.mark_playing(i1.id)
        mgr.add_song(room_id="test-queue-room", song_id="song2", guest_id=a)
        mgr.add_song(room_id="test-queue-room", song_id="song3", guest_id=b)
        ordered = mgr.apply_fair_order("test-queue-room")
        waiting = [qi for qi in ordered if qi.status != "playing"]
        # Alice is singing NOW, so Bob's song comes before her next one.
        assert waiting[0].guest_id == b
        assert waiting[1].guest_id == a
