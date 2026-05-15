"""Guests API routes — session management and authentication."""
from fastapi import APIRouter, HTTPException, Depends, Response
from sqlalchemy.orm import Session

from ktv_pipeline.database import get_db_session
from ktv_pipeline.models import Guest, Room
from ktv_pipeline.schemas import GuestJoin, GuestOut, SessionOut
from ktv_pipeline.auth import (
    hash_password,
    verify_room_password,
    create_access_token,
    guest_from_request,
)
from ktv_pipeline.deps import get_current_guest


router = APIRouter(prefix="/guests", tags=["guests"])


def get_session():
    with get_db_session() as session:
        yield session


@router.post("/join", response_model=SessionOut)
def join_room(data: GuestJoin, response: Response, session: Session = Depends(get_session)):
    """Join a room with a nickname and optional room password.
    
    Creates a new Guest record if nickname is new; otherwise re-uses existing guest.
    Returns a JWT session token set as a cookie.
    """
    # Check room exists
    room = session.query(Room).filter_by(id=data.room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail=f"Room '{data.room_id}' not found")

    # Verify room password if required (accepts `password` or `room_password`)
    if room.password_hash:
        pw = data.effective_password
        if not pw:
            raise HTTPException(status_code=403, detail="Room password required")
        if not verify_room_password(room.password_hash, pw):
            raise HTTPException(status_code=403, detail="Incorrect room password")

    # Find or create guest by nickname (within this room — key is nickname for simplicity)
    guest = session.query(Guest).filter_by(nickname=data.nickname).first()
    is_new = guest is None
    if is_new:
        import random
        colors = ["#7c3aed", "#059669", "#dc2626", "#d97706", "#2563eb", "#db2777"]
        guest = Guest(
            nickname=data.nickname,
            avatar_color=random.choice(colors),
            is_admin=False,
        )
        session.add(guest)
        session.commit()
        session.refresh(guest)
    else:
        # Update last_seen
        from datetime import datetime, timezone
        guest.last_seen = datetime.now(timezone.utc)
        session.commit()
        session.refresh(guest)

    # Create JWT token
    token = create_access_token(guest_id=guest.id, room_id=data.room_id)

    # Set cookie
    response.set_cookie(
        key="ktv_session",
        value=token,
        httponly=True,
        secure=True,           # HTTPS only
        samesite="lax",
        max_age=60 * 60 * 24 * 7,  # 1 week
    )

    return SessionOut(access_token=token, guest=GuestOut.model_validate(guest))


@router.get("/me", response_model=GuestOut)
def get_me(payload: dict = Depends(get_current_guest), session: Session = Depends(get_session)):
    """Return the current authenticated guest's info."""
    guest_id = payload["sub"]
    guest = session.query(Guest).filter_by(id=guest_id).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")
    return guest


@router.post("", response_model=GuestOut)
def update_guest(
    payload: dict = Depends(get_current_guest),
    session: Session = Depends(get_session),
):
    """Update guest info (e.g. nickname). Requires authentication."""
    guest_id = payload["sub"]
    guest = session.query(Guest).filter_by(id=guest_id).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")
    return guest


@router.get("/online/{room_id}", response_model=list[GuestOut])
def get_online_guests(room_id: str, session: Session = Depends(get_session)):
    """Return guests currently connected to a room via WebSocket."""
    from ktv_pipeline.ws_manager import manager
    clients = manager.get_room_clients(room_id)
    guest_ids = list({c.guest_id for c in clients if c.guest_id})
    if not guest_ids:
        return []
    guests = session.query(Guest).filter(Guest.id.in_(guest_ids)).all()
    return guests


@router.get("/{guest_id}", response_model=GuestOut)
def get_guest(guest_id: str, session: Session = Depends(get_session)):
    """Get a guest by ID. Public endpoint."""
    guest = session.query(Guest).filter_by(id=guest_id).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")
    return guest