"""Queue removal and skip permissions for ordinary room guests."""
import json
import uuid
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient

from main import app
from ktv_pipeline.auth import create_access_token
from ktv_pipeline.database import get_db_session, init_db
from ktv_pipeline.models import Guest, QueueItem, Room, Song
from ktv_pipeline.ws_manager import ClientRole


@pytest.fixture(autouse=True)
def _db():
    init_db()


@pytest.fixture()
def queue_case():
    tag = uuid.uuid4().hex[:8]
    room_a, room_b = f"owner-a-{tag}", f"owner-b-{tag}"
    song_a, song_b = f"owner-song-a-{tag}", f"owner-song-b-{tag}"
    with get_db_session() as session:
        owner = Guest(nickname=f"owner-{tag}")
        other = Guest(nickname=f"other-{tag}")
        admin = Guest(nickname=f"admin-{tag}")
        session.add_all([
            Room(id=room_a, name="Owner controls A"),
            Room(id=room_b, name="Owner controls B"),
            Song(id=song_a, title="Song A", status="ready", duration_sec=200),
            Song(id=song_b, title="Song B", status="ready", duration_sec=200),
            owner, other, admin,
        ])
        session.flush()
        own_pending = QueueItem(room_id=room_a, song_id=song_a, guest_id=owner.id,
                                position=1, status="pending")
        other_pending = QueueItem(room_id=room_a, song_id=song_b, guest_id=other.id,
                                  position=2, status="pending")
        cross_pending = QueueItem(room_id=room_b, song_id=song_b, guest_id=owner.id,
                                  position=1, status="pending")
        session.add_all([own_pending, other_pending, cross_pending])
        session.commit()
        session.refresh(own_pending)
        session.refresh(other_pending)
        session.refresh(cross_pending)
        return {
            "room_a": room_a, "room_b": room_b,
            "owner": owner.id, "other": other.id, "admin": admin.id,
            "own_pending": own_pending.id, "other_pending": other_pending.id,
            "cross_pending": cross_pending.id,
            "owner_headers": {"Authorization": "Bearer " + create_access_token(owner.id, room_a)},
            "other_headers": {"Authorization": "Bearer " + create_access_token(other.id, room_a)},
            "admin_headers": {"Authorization": "Bearer " + create_access_token(admin.id, room_a, is_admin=True, scope="room_admin")},
            "cross_headers": {"Authorization": "Bearer " + create_access_token(owner.id, room_b)},
        }


def _exists(item_id: int) -> bool:
    with get_db_session() as session:
        return session.query(QueueItem).filter_by(id=item_id).first() is not None


def test_rest_remove_only_allows_owner_or_this_room_admin(queue_case):
    client = TestClient(app)
    c = queue_case
    assert client.delete(f"/api/queue/{c['own_pending']}", headers=c["owner_headers"]).status_code == 200
    assert not _exists(c["own_pending"])

    # A request-body guest_id cannot override the JWT subject.
    denied = client.request(
        "DELETE", f"/api/queue/{c['other_pending']}", headers=c["owner_headers"],
        json={"guest_id": c["other"]},
    )
    assert denied.status_code == 403
    assert _exists(c["other_pending"])

    assert client.delete(f"/api/queue/{c['other_pending']}", headers=c["admin_headers"]).status_code == 200


def test_rest_remove_cannot_cross_rooms_even_for_item_owner(queue_case):
    client = TestClient(app)
    c = queue_case
    response = client.delete(f"/api/queue/{c['cross_pending']}", headers=c["other_headers"])
    assert response.status_code == 403
    assert _exists(c["cross_pending"])


def test_rest_remove_allows_processing_but_not_currently_playing(queue_case):
    c = queue_case
    with get_db_session() as session:
        processing = QueueItem(room_id=c["room_a"], song_id=f"owner-song-a-{c['room_a'].rsplit('-', 1)[1]}",
                               guest_id=c["owner"], position=3, status="processing")
        playing = QueueItem(room_id=c["room_a"], song_id=f"owner-song-b-{c['room_a'].rsplit('-', 1)[1]}",
                            guest_id=c["owner"], position=4, status="playing")
        session.add_all([processing, playing])
        session.commit()
        session.refresh(processing)
        session.refresh(playing)
        processing_id, playing_id = processing.id, playing.id

    client = TestClient(app)
    assert client.delete(f"/api/queue/{processing_id}", headers=c["owner_headers"]).status_code == 200
    assert not _exists(processing_id)
    response = client.delete(f"/api/queue/{playing_id}", headers=c["owner_headers"])
    assert response.status_code == 409
    assert _exists(playing_id)


def _make_playing(case, owner_id: str) -> int:
    with get_db_session() as session:
        session.query(QueueItem).filter_by(room_id=case["room_a"]).update({"status": "done"})
        item = QueueItem(room_id=case["room_a"], song_id=f"owner-song-a-{case['room_a'].rsplit('-', 1)[1]}",
                         guest_id=owner_id, position=1, status="playing")
        session.add(item)
        session.commit()
        session.refresh(item)
        return item.id


async def _dispatch_skip(case, guest_id, is_admin, body, advance):
    from api import ws as ws_mod
    with patch.object(ws_mod.manager, "broadcast_system_error", new=AsyncMock()) as error, \
         patch.object(ws_mod.manager, "broadcast_activity", new=AsyncMock()), \
         patch.object(ws_mod.manager, "get_playback_state", return_value={"position_sec": 10}), \
         patch.object(ws_mod.manager, "update_playback_state", new=Mock()), \
         patch.object(ws_mod, "_handle_song_advance", new=advance):
        await ws_mod.dispatch_message(
            "client", case["room_a"], guest_id, "Guest", json.dumps(body),
            ClientRole.REMOTE, is_admin,
        )
        return error


async def test_ws_owner_can_skip_own_current_song(queue_case):
    item_id = _make_playing(queue_case, queue_case["owner"])
    advance = AsyncMock()
    error = await _dispatch_skip(
        queue_case, queue_case["owner"], False,
        {"type": "playback.skip", "queueItemId": item_id}, advance,
    )
    error.assert_not_awaited()
    advance.assert_awaited_once_with(
        queue_case["room_a"], final_position_sec=10, expected_queue_item_id=item_id
    )


async def test_ws_legacy_skip_binds_the_current_item_before_advancing(queue_case):
    item_id = _make_playing(queue_case, queue_case["owner"])
    advance = AsyncMock()
    error = await _dispatch_skip(
        queue_case, queue_case["owner"], False, {"type": "playback.skip"}, advance,
    )
    error.assert_not_awaited()
    advance.assert_awaited_once_with(
        queue_case["room_a"], final_position_sec=10, expected_queue_item_id=item_id
    )


async def test_ws_guest_cannot_skip_another_guests_song_or_forge_owner(queue_case):
    item_id = _make_playing(queue_case, queue_case["owner"])
    advance = AsyncMock()
    error = await _dispatch_skip(
        queue_case, queue_case["other"], False,
        {"type": "playback.skip", "queueItemId": item_id, "guest_id": queue_case["owner"]}, advance,
    )
    advance.assert_not_awaited()
    error.assert_awaited_once()


async def test_ws_admin_can_skip_any_song_and_stale_item_cannot_skip_new_song(queue_case):
    item_id = _make_playing(queue_case, queue_case["owner"])
    admin_advance = AsyncMock()
    admin_error = await _dispatch_skip(
        queue_case, queue_case["admin"], True,
        {"type": "playback.skip", "queueItemId": item_id}, admin_advance,
    )
    admin_error.assert_not_awaited()
    admin_advance.assert_awaited_once()

    stale_advance = AsyncMock()
    stale_error = await _dispatch_skip(
        queue_case, queue_case["owner"], False,
        {"type": "playback.skip", "queueItemId": item_id + 999}, stale_advance,
    )
    stale_advance.assert_not_awaited()
    stale_error.assert_awaited_once()


async def test_ws_queue_remove_rejects_cross_room_item(queue_case):
    from api import ws as ws_mod
    with patch.object(ws_mod.manager, "broadcast_system_error", new=AsyncMock()) as error, \
         patch.object(ws_mod.manager, "broadcast_queue_updated", new=AsyncMock()), \
         patch.object(ws_mod.manager, "broadcast_activity", new=AsyncMock()):
        await ws_mod._handle_queue_remove(
            queue_case["room_a"], queue_case["owner"], "Owner", False,
            {"queueItemId": queue_case["cross_pending"]},
        )
    error.assert_awaited_once()
    assert _exists(queue_case["cross_pending"])


async def test_ws_queue_remove_rejects_playing_item(queue_case):
    item_id = _make_playing(queue_case, queue_case["owner"])
    from api import ws as ws_mod
    with patch.object(ws_mod.manager, "broadcast_system_error", new=AsyncMock()) as error, \
         patch.object(ws_mod.manager, "broadcast_queue_updated", new=AsyncMock()), \
         patch.object(ws_mod.manager, "broadcast_activity", new=AsyncMock()):
        await ws_mod._handle_queue_remove(
            queue_case["room_a"], queue_case["owner"], "Owner", False,
            {"queueItemId": item_id},
        )
    error.assert_awaited_once()
    assert _exists(item_id)
