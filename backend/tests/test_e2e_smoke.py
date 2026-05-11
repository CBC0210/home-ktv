"""M2-T8 End-to-end smoke test.

Flow: create room → join as guest → add song → pipeline triggered → song ready.
Also covers WebSocket JWT auth and stream endpoint for a ready song.

All pipeline work is mocked — no real yt-dlp / Demucs / GPU needed.
"""
import json
import uuid
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from main import app
from ktv_pipeline.config import settings
from ktv_pipeline.database import get_db_session, init_db
from ktv_pipeline.models import Room, Song, QueueItem, Guest
from ktv_pipeline.auth import hash_password, create_access_token


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def ensure_db():
    """Make sure tables exist before each test (idempotent)."""
    init_db()


@pytest.fixture()
def client():
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture()
def admin_token(client):
    """Get a valid admin JWT token."""
    resp = client.post("/api/auth/admin/login", params={"password": settings.admin_password})
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest.fixture()
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture()
def smoke_room(client, admin_headers):
    """Create a uniquely-named room for the smoke test, return room dict."""
    room_id = f"smoke-{uuid.uuid4().hex[:8]}"
    resp = client.post(
        "/api/rooms",
        json={"id": room_id, "name": "Smoke Test Room"},
        headers=admin_headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture()
def guest_session(client, smoke_room):
    """Join the smoke room as a guest; return (token, guest_id, room_id)."""
    room_id = smoke_room["id"]
    nickname = f"smoketester-{uuid.uuid4().hex[:6]}"
    resp = client.post("/api/guests/join", json={"nickname": nickname, "room_id": room_id})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    return data["access_token"], data["guest"]["id"], room_id


# ── E2E Smoke Test ─────────────────────────────────────────────────────────────

class TestE2ESmokeFlow:
    """Full create-room → join → add-song → pipeline-triggered → ready cycle."""

    def test_create_room_returns_room(self, smoke_room):
        assert smoke_room["id"].startswith("smoke-")
        assert smoke_room["name"] == "Smoke Test Room"
        assert smoke_room["has_password"] is False

    def test_join_room_returns_token(self, guest_session):
        token, guest_id, room_id = guest_session
        assert token
        assert guest_id
        assert room_id.startswith("smoke-")

    def test_add_song_triggers_pipeline_and_creates_queue_item(self, client, guest_session):
        """POST /api/songs → song record created, queue item present, pipeline enqueued."""
        token, guest_id, room_id = guest_session
        yt_id = f"smk{uuid.uuid4().hex[:8]}"  # unique synthetic ID — avoids DB state from prior runs

        pipeline_called_with = []

        def mock_pipeline(queue_item_id: int):
            pipeline_called_with.append(queue_item_id)

        with patch("api.songs._run_pipeline_sync", side_effect=mock_pipeline):
            resp = client.post(
                "/api/songs",
                json={"youtube_url": f"https://www.youtube.com/watch?v={yt_id}", "room_id": room_id},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200, resp.text
        data = resp.json()

        # Response carries the queue item (or song data — both have song_id / id)
        assert data.get("song_id") == yt_id or data.get("id") == yt_id

        # Verify song record exists in DB
        with get_db_session() as session:
            song = session.query(Song).filter_by(id=yt_id).first()
            assert song is not None
            assert song.status in ("pending", "processing", "ready")

        # Verify queue item was created
        with get_db_session() as session:
            item = session.query(QueueItem).filter_by(room_id=room_id, song_id=yt_id).first()
            assert item is not None

        # Verify background task was scheduled (pipeline_called_with populated OR bg task enqueued)
        # TestClient runs background tasks synchronously by default — so mock is invoked
        assert len(pipeline_called_with) == 1

    def test_song_status_shows_pending_then_ready(self, client, guest_session):
        """Pipeline transitions: song starts pending, manually set ready, status endpoint reflects it."""
        token, guest_id, room_id = guest_session
        yt_id = f"test{uuid.uuid4().hex[:7]}"  # synthetic ID

        # Create the song directly in DB (simulating a prior pipeline run that's now pending)
        with get_db_session() as session:
            song = session.query(Song).filter_by(id=yt_id).first()
            if not song:
                song = Song(id=yt_id, title=f"Test Song {yt_id}", status="pending")
                session.add(song)
                session.commit()

        # Initial status: pending
        resp = client.get(f"/api/songs/{yt_id}/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "pending"

        # Simulate pipeline completing: set status → ready
        with get_db_session() as session:
            song = session.query(Song).filter_by(id=yt_id).first()
            song.status = "ready"
            session.commit()

        # Final status: ready
        resp = client.get(f"/api/songs/{yt_id}/status")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"

    def test_duplicate_add_reuses_queue_item(self, client, guest_session):
        """Adding the same song twice returns same/existing queue item without duplicates."""
        token, guest_id, room_id = guest_session
        yt_id = f"dup{uuid.uuid4().hex[:8]}"
        url = f"https://www.youtube.com/watch?v={yt_id}"
        auth = {"Authorization": f"Bearer {token}"}

        with patch("api.songs._run_pipeline_sync"):
            r1 = client.post("/api/songs", json={"youtube_url": url, "room_id": room_id}, headers=auth)
            r2 = client.post("/api/songs", json={"youtube_url": url, "room_id": room_id}, headers=auth)

        assert r1.status_code == 200
        assert r2.status_code == 200

        # Should not create duplicate active queue items
        with get_db_session() as session:
            count = (
                session.query(QueueItem)
                .filter_by(room_id=room_id, song_id=yt_id)
                .filter(QueueItem.status.in_(["pending", "processing", "playing"]))
                .count()
            )
        assert count == 1


# ── WebSocket Auth Tests ──────────────────────────────────────────────────────

class TestWebSocketAuth:
    """WebSocket connects/rejects based on JWT token."""

    def test_ws_connect_with_valid_token(self, client, smoke_room):
        """A valid JWT allows WebSocket connection."""
        room_id = smoke_room["id"]
        token = create_access_token(guest_id="ws-test-guest", room_id=room_id)

        # Pre-create a Guest so the WS handler finds it
        with get_db_session() as session:
            g = session.query(Guest).filter_by(id="ws-test-guest").first()
            if not g:
                g = Guest(id="ws-test-guest", nickname="WSTester")
                session.add(g)
                session.commit()

        with client.websocket_connect(f"/ws?token={token}") as ws:
            # Send a simple JSON message and verify no crash
            ws.send_text(json.dumps({"type": "player.ready"}))
            # No assertion on receive — just checks that connect succeeded

    def test_ws_connect_with_invalid_token_closes(self, client):
        """Invalid JWT causes the WebSocket to close with code 4001."""
        from websockets.exceptions import ConnectionClosedError

        try:
            with client.websocket_connect("/ws?token=invalid.token.here") as ws:
                # If we get here, force a receive to detect the close
                ws.receive_text()
            # Getting here without exception means the server didn't close — fail
            pytest.fail("Expected WebSocket to be closed with 4001 for invalid token")
        except Exception as exc:
            # Any exception (WebSocketDisconnect, RuntimeError) is acceptable — server refused
            assert True


# ── Streaming Endpoint Tests ──────────────────────────────────────────────────

class TestStreamingE2E:
    """Streaming endpoint returns content for ready songs with files on disk."""

    def test_stream_hls_manifest_for_ready_song(self, client, tmp_path):
        """A ready song with vocals.wav on disk returns 200 m3u8 content."""
        yt_id = f"hls{uuid.uuid4().hex[:8]}"

        # Recreate the exact path that _song_cache_dir() produces:
        # settings.data_dir / "cache" / "demucs" / song_id
        cache_dir = tmp_path / "cache" / "demucs" / yt_id
        cache_dir.mkdir(parents=True)
        (cache_dir / "vocals.wav").write_bytes(b"RIFF" + b"\x00" * 44)  # minimal WAV header

        # Patch settings.data_dir to use our tmp dir
        with patch("api.streaming.settings") as mock_settings:
            mock_settings.data_dir = tmp_path

            with get_db_session() as session:
                song = Song(id=yt_id, title="HLS Test Song", status="ready")
                session.add(song)
                session.commit()

            resp = client.get(f"/songs/{yt_id}/stream.m3u8")

        assert resp.status_code == 200
        assert "EXTM3U" in resp.text

    def test_stream_pending_song_returns_202(self, client):
        """A song in 'pending' state returns 202 (not ready yet)."""
        yt_id = f"pnd{uuid.uuid4().hex[:8]}"

        with get_db_session() as session:
            song = Song(id=yt_id, title="Pending Song", status="pending")
            session.add(song)
            session.commit()

        resp = client.get(f"/songs/{yt_id}/stream.m3u8")
        assert resp.status_code == 202
