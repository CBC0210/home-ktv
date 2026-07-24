"""Tests for GET /api/guests/online/{room_id} endpoint."""
import pytest
from fastapi.testclient import TestClient

from ktv_pipeline.main import app
from ktv_pipeline.auth import create_access_token, hash_password
from ktv_pipeline.database import get_db_session
from ktv_pipeline.models import Room, Guest


client = TestClient(app)


def _seed_room(room_id: str = "test-online-room") -> str:
    with get_db_session() as s:
        existing = s.query(Room).filter_by(id=room_id).first()
        if not existing:
            s.add(Room(id=room_id, name="Online Test Room"))
            s.commit()
    return room_id


def _seed_guest(nickname: str) -> str:
    with get_db_session() as s:
        g = s.query(Guest).filter_by(nickname=nickname).first()
        if not g:
            g = Guest(nickname=nickname, avatar_color="#7c3aed", is_admin=False)
            s.add(g)
            s.commit()
            s.refresh(g)
        return g.id


class TestOnlineGuestsEndpoint:
    def test_empty_room_returns_empty_list(self):
        room_id = _seed_room("test-online-empty")
        resp = client.get(f"/api/guests/online/{room_id}")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_list_type(self):
        room_id = _seed_room("test-online-list")
        resp = client.get(f"/api/guests/online/{room_id}")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_endpoint_not_confused_with_guest_id_route(self):
        """online/{room_id} must not be matched by /{guest_id}."""
        room_id = _seed_room("test-online-route")
        resp = client.get(f"/api/guests/online/{room_id}")
        # Should return 200 (list), not 404 (guest not found)
        assert resp.status_code == 200
