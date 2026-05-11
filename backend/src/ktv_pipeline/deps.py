"""FastAPI auth dependencies — Depends() injection for routes."""
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ktv_pipeline.database import get_db_session
from ktv_pipeline.models import Guest, Room
from ktv_pipeline.auth import guest_from_request, get_optional_guest


def get_current_guest(request: Request) -> dict:
    """Dependency — requires a valid session. Returns JWT payload."""
    return guest_from_request(request)


def get_optional_guest_dep(request: Request) -> dict | None:
    """Dependency — returns guest payload or None if not authenticated."""
    return get_optional_guest(request)


def require_admin(request: Request) -> dict:
    """Dependency — requires admin session (is_admin=True in JWT)."""
    payload = guest_from_request(request)
    if not payload.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin access required")
    return payload


class RoomPasswordDependency:
    """FastAPI dependency that checks room password for protected rooms.
    
    Usage:
        @router.post("/join")
        def join_room(
            room_id: str,
            password: str,
            room_auth: RoomPasswordDependency = Depends(),
        ):
            room_auth.check(room_id, password)
    """

    def __init__(self, session: Session):
        self._session = session

    def check(self, room_id: str, provided_password: str) -> Room:
        """Verify room password and return the Room object. Raises 403 on failure."""
        room = self._session.query(Room).filter_by(id=room_id).first()
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")

        if room.password_hash:
            from ktv_pipeline.auth import verify_room_password
            if not verify_room_password(room.password_hash, provided_password):
                raise HTTPException(status_code=403, detail="Incorrect room password")

        return room


def get_room_password_dep(session: Session = Depends(lambda: None)) -> RoomPasswordDependency:
    # We need a session — use the same get_session approach
    raise NotImplementedError("Use get_room_password_dependency below")


def get_room_password_dependency(session: Session) -> RoomPasswordDependency:
    """Create a RoomPasswordDependency with the current session."""
    return RoomPasswordDependency(session)


# ── Dependency factory (must be called inside a route to get session) ─────────
def room_password_check(room_id: str, provided_password: str, session: Session) -> Room:
    """Standalone room password check — usable inside route handlers."""
    from ktv_pipeline.auth import verify_room_password as _verify

    room = session.query(Room).filter_by(id=room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    if room.password_hash:
        if not _verify(room.password_hash, provided_password):
            raise HTTPException(status_code=403, detail="Incorrect room password")
    return room