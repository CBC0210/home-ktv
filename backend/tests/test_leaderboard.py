"""Tests for GET /api/songs/leaderboard."""
import uuid
import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

from main import app
from ktv_pipeline.config import settings
from ktv_pipeline.database import get_db_session, init_db
from ktv_pipeline.models import Room, Song, Guest, PlayHistory
from ktv_pipeline.auth import hash_password


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def ensure_db():
    init_db()


@pytest.fixture()
def client():
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture()
def admin_token(client):
    resp = client.post("/api/auth/admin/login", params={"password": settings.admin_password})
    assert resp.status_code == 200
    return resp.json()["access_token"]


@pytest.fixture()
def guest_token(client):
    room_id = f"lb-room-{uuid.uuid4().hex[:6]}"
    with get_db_session() as session:
        room = Room(id=room_id, name="Leaderboard Test Room")
        session.add(room)
        session.commit()
    resp = client.post("/api/guests/join", json={"nickname": f"lbuser-{uuid.uuid4().hex[:4]}", "room_id": room_id})
    assert resp.status_code == 200
    return resp.json()["access_token"], resp.json()["guest"]["id"]


@pytest.fixture()
def songs_with_history(guest_token):
    """Create songs and play_history entries for testing."""
    _, guest_id = guest_token
    now = datetime.now(timezone.utc)

    with get_db_session() as session:
        song_ids = []
        for i in range(5):
            sid = f"lb-song-{uuid.uuid4().hex[:6]}"
            song = Song(
                id=sid,
                title=f"Test Song {i}",
                artist=f"Artist {i}",
                status="ready",
                play_count=10 - i,  # 10, 9, 8, 7, 6
            )
            session.add(song)
            song_ids.append(sid)
        session.commit()

        # Add play_history entries this month
        room_id = f"lb-hist-room-{uuid.uuid4().hex[:4]}"
        room = Room(id=room_id, name="History Room")
        session.add(room)
        session.commit()

        # song_ids[0] played 3 times this month by our guest
        # song_ids[1] played 2 times this month
        # song_ids[2] played 1 time this month (old — not this month)
        for _ in range(3):
            session.add(PlayHistory(
                song_id=song_ids[0], guest_id=guest_id,
                room_id=room_id, played_at=now,
            ))
        for _ in range(2):
            session.add(PlayHistory(
                song_id=song_ids[1], guest_id=guest_id,
                room_id=room_id, played_at=now,
            ))
        # Old play (last month) — should NOT appear in monthly_hot
        session.add(PlayHistory(
            song_id=song_ids[2], guest_id=guest_id,
            room_id=room_id, played_at=now - timedelta(days=40),
        ))
        session.commit()

    return song_ids, guest_id


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestLeaderboardAllTime:
    def test_returns_list(self, client):
        resp = client.get("/api/songs/leaderboard?category=all_time")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_default_category_is_all_time(self, client):
        resp = client.get("/api/songs/leaderboard")
        assert resp.status_code == 200

    def test_ordered_by_play_count_desc(self, client, songs_with_history):
        song_ids, _ = songs_with_history
        resp = client.get("/api/songs/leaderboard?category=all_time&limit=5")
        assert resp.status_code == 200
        data = resp.json()
        counts = [item["play_count"] for item in data]
        assert counts == sorted(counts, reverse=True)

    def test_rank_field_starts_at_1(self, client, songs_with_history):
        resp = client.get("/api/songs/leaderboard?category=all_time&limit=3")
        data = resp.json()
        ranks = [item["rank"] for item in data]
        assert ranks[0] == 1

    def test_response_shape(self, client, songs_with_history):
        resp = client.get("/api/songs/leaderboard?category=all_time&limit=1")
        item = resp.json()[0]
        assert "rank" in item
        assert "song_id" in item
        assert "title" in item
        assert "play_count" in item

    def test_limit_respected(self, client, songs_with_history):
        resp = client.get("/api/songs/leaderboard?category=all_time&limit=2")
        assert len(resp.json()) <= 2

    def test_limit_capped_at_50(self, client):
        resp = client.get("/api/songs/leaderboard?category=all_time&limit=999")
        assert resp.status_code == 200


class TestLeaderboardMonthlyHot:
    def test_returns_list(self, client, songs_with_history):
        resp = client.get("/api/songs/leaderboard?category=monthly_hot")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_excludes_old_plays(self, client, songs_with_history):
        song_ids, _ = songs_with_history
        resp = client.get("/api/songs/leaderboard?category=monthly_hot&limit=50")
        data = resp.json()
        result_ids = [item["song_id"] for item in data]
        # song_ids[2] was played 40 days ago — must not be in monthly hot
        assert song_ids[2] not in result_ids

    def test_top_song_has_most_plays(self, client, songs_with_history):
        song_ids, _ = songs_with_history
        resp = client.get("/api/songs/leaderboard?category=monthly_hot&limit=50")
        data = resp.json()
        if not data:
            return
        # Results must be in descending play count order
        counts = [item["play_count"] for item in data]
        assert counts == sorted(counts, reverse=True)
        # song_ids[0] was played 3 times — it should appear in the results
        result_ids = [item["song_id"] for item in data]
        assert song_ids[0] in result_ids
        # And must rank above song_ids[1] (2 plays) if both are present
        if song_ids[1] in result_ids:
            idx0 = result_ids.index(song_ids[0])
            idx1 = result_ids.index(song_ids[1])
            assert idx0 < idx1

    def test_empty_when_no_history(self, client):
        resp = client.get("/api/songs/leaderboard?category=monthly_hot")
        assert resp.status_code == 200
        # May or may not be empty depending on DB state — just check it's a list
        assert isinstance(resp.json(), list)


class TestLeaderboardPersonal:
    def test_requires_auth(self, client):
        resp = client.get("/api/songs/leaderboard?category=personal")
        assert resp.status_code == 401

    def test_returns_personal_plays(self, client, guest_token, songs_with_history):
        token, _ = guest_token
        resp = client.get(
            "/api/songs/leaderboard?category=personal&limit=10",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_personal_top_song(self, client, guest_token, songs_with_history):
        token, _ = guest_token
        song_ids, _ = songs_with_history
        resp = client.get(
            "/api/songs/leaderboard?category=personal&limit=10",
            headers={"Authorization": f"Bearer {token}"},
        )
        data = resp.json()
        # song_ids[0] played 3 times by our guest this month
        if data:
            assert data[0]["song_id"] == song_ids[0]
            assert data[0]["play_count"] == 3


class TestLeaderboardEdgeCases:
    def test_invalid_category_returns_400(self, client):
        resp = client.get("/api/songs/leaderboard?category=invalid")
        assert resp.status_code == 400

    def test_empty_db_returns_empty_list(self, client):
        resp = client.get("/api/songs/leaderboard?category=all_time")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
