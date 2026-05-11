"""Rooms API routes — room management and password-protected creation."""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from ktv_pipeline.database import get_db_session
from ktv_pipeline.models import Room
from ktv_pipeline.schemas import RoomCreate, RoomOut
from ktv_pipeline.auth import hash_password, verify_admin_password
from ktv_pipeline.deps import get_current_guest


router = APIRouter(prefix="/rooms", tags=["rooms"])


def get_session():
    with get_db_session() as session:
        yield session


@router.get("", response_model=list[RoomOut])
def list_rooms(session: Session = Depends(get_session)):
    """List all rooms (public). Password hash is never exposed; has_password is included."""
    rooms = session.query(Room).all()
    return [
        RoomOut(
            id=room.id,
            name=room.name,
            is_default=room.is_default,
            created_at=room.created_at,
            settings=room.settings,
            has_password=bool(room.password_hash),
        )
        for room in rooms
    ]


@router.post("", response_model=RoomOut)
def create_room(
    data: RoomCreate,
    payload: dict = Depends(get_current_guest),
    session: Session = Depends(get_session),
):
    """Create a new room. Requires authentication. Password is hashed with bcrypt."""
    if not payload.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin only")

    existing = session.query(Room).filter_by(id=data.id).first()
    if existing:
        raise HTTPException(status_code=409, detail="Room already exists")

    password_hash = None
    if data.password:
        password_hash = hash_password(data.password)

    room = Room(
        id=data.id,
        name=data.name,
        password_hash=password_hash,
    )
    session.add(room)
    session.commit()
    session.refresh(room)

    return RoomOut(
        id=room.id,
        name=room.name,
        is_default=room.is_default,
        created_at=room.created_at,
        settings=room.settings,
        has_password=bool(room.password_hash),
    )


@router.get("/{room_id}", response_model=RoomOut)
def get_room(room_id: str, session: Session = Depends(get_session)):
    """Get room details. Public; does not expose password hash."""
    room = session.query(Room).filter_by(id=room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return RoomOut(
        id=room.id,
        name=room.name,
        is_default=room.is_default,
        created_at=room.created_at,
        settings=room.settings,
        has_password=bool(room.password_hash),
    )


@router.patch("/{room_id}/password")
def set_room_password(
    room_id: str,
    new_password: str,
    payload: dict = Depends(get_current_guest),
    session: Session = Depends(get_session),
):
    """Change room password. Admin only."""
    if not payload.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin only")

    room = session.query(Room).filter_by(id=room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    room.password_hash = hash_password(new_password)
    session.commit()

    return {"status": "ok", "room_id": room_id, "has_password": True}