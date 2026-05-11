"""Tests for auth.py, deps.py, and /api/auth, /api/guests, /api/rooms auth routes."""
import pytest
from fastapi.testclient import TestClient

from ktv_pipeline.main import app
from ktv_pipeline.auth import hash_password, verify_password, create_access_token, decode_access_token


client = TestClient(app)


class TestPasswordHashing:
    def test_hash_and_verify(self):
        pwd = "test_password_123"
        h = hash_password(pwd)
        assert h != pwd
        assert verify_password(pwd, h) is True
        assert verify_password("wrong", h) is False

    def test_different_hashes_for_same_password(self):
        pwd = "same"
        h1 = hash_password(pwd)
        h2 = hash_password(pwd)
        assert h1 != h2  # bcrypt uses random salt
        assert verify_password(pwd, h1)
        assert verify_password(pwd, h2)


class TestJWTTokens:
    def test_create_and_decode_token(self):
        token = create_access_token(guest_id="g123", room_id="home")
        payload = decode_access_token(token)
        assert payload["sub"] == "g123"
        assert payload["room_id"] == "home"

    def test_decode_invalid_token_raises(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            decode_access_token("not.a.valid.token")
        assert exc_info.value.status_code == 401

    def test_token_in_response(self):
        # POST to /api/auth/admin/login with correct password
        from ktv_pipeline.config import settings
        response = client.post("/api/auth/admin/login", params={"password": settings.admin_password})
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["guest"]["is_admin"] is True


class TestAdminLogin:
    def test_admin_login_wrong_password(self):
        response = client.post("/api/auth/admin/login", params={"password": "wrong"})
        assert response.status_code == 401

    def test_admin_login_correct(self):
        from ktv_pipeline.config import settings
        response = client.post("/api/auth/admin/login", params={"password": settings.admin_password})
        assert response.status_code == 200
        data = response.json()
        assert data["guest"]["is_admin"] is True
        assert "access_token" in data


class TestGuestJoin:
    def test_join_nonexistent_room(self):
        response = client.post("/api/guests/join", json={
            "nickname": "Alice",
            "room_id": "nonexistent-room",
        })
        assert response.status_code == 404

    def test_join_room_with_password_no_password_provided(self):
        import uuid
        room_id = f"test-protected-room-{uuid.uuid4().hex[:8]}"
        # Create a room with password using direct DB
        from ktv_pipeline.database import get_db_session
        from ktv_pipeline.models import Room

        with get_db_session() as session:
            room = Room(id=room_id, name="Protected Room", password_hash=hash_password("secret123"))
            session.add(room)
            session.commit()

        response = client.post("/api/guests/join", json={
            "nickname": "Bob",
            "room_id": room_id,
            "room_password": None,
        })
        assert response.status_code == 403

        response = client.post("/api/guests/join", json={
            "nickname": "Bob2",
            "room_id": room_id,
            "room_password": "secret123",
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["guest"]["nickname"] == "Bob2"

    def test_join_default_room(self):
        # Create default room if not exists
        from ktv_pipeline.database import get_db_session
        from ktv_pipeline.models import Room

        with get_db_session() as session:
            room = session.query(Room).filter_by(id="home").first()
            if not room:
                room = Room(id="home", name="Home Room")
                session.add(room)
                session.commit()

        response = client.post("/api/guests/join", json={
            "nickname": "TestUser",
            "room_id": "home",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["guest"]["nickname"] == "TestUser"
        # Cookie should be set
        assert "ktv_session" in client.cookies

    def test_join_creates_new_guest(self):
        from ktv_pipeline.database import get_db_session
        from ktv_pipeline.models import Room

        with get_db_session() as session:
            room = session.query(Room).filter_by(id="home").first()
            if not room:
                room = Room(id="home", name="Home Room")
                session.add(room)
                session.commit()

        # Use unique nickname to avoid collision
        import uuid
        nickname = f"TestUser_{uuid.uuid4().hex[:8]}"

        response = client.post("/api/guests/join", json={
            "nickname": nickname,
            "room_id": "home",
        })
        assert response.status_code == 200


class TestGuestMe:
    def test_me_without_auth_returns_401(self):
        response = client.get("/api/guests/me")
        assert response.status_code == 401

    def test_me_with_valid_token(self):
        from ktv_pipeline.config import settings
        # Login as admin first to get a valid token
        login_resp = client.post("/api/auth/admin/login", params={"password": settings.admin_password})
        token = login_resp.json()["access_token"]

        response = client.get("/api/guests/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        data = response.json()
        assert data["is_admin"] is True