"""Rooms API routes。"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from ktv_pipeline.database import get_db_session
from ktv_pipeline.models import Room
from ktv_pipeline.schemas import RoomCreate, RoomOut

router = APIRouter(prefix="/rooms", tags=["rooms"])


def get_session():
    with get_db_session() as session:
        yield session


@router.get("", response_model=list[RoomOut])
def list_rooms(session: Session = Depends(get_session)):
    return session.query(Room).all()


@router.post("", response_model=RoomOut)
def create_room(data: RoomCreate, session: Session = Depends(get_session)):
    existing = session.query(Room).filter_by(id=data.id).first()
    if existing:
        raise HTTPException(status_code=409, detail="Room already exists")
    room = Room(id=data.id, name=data.name)
    session.add(room)
    session.commit()
    session.refresh(room)
    return room


@router.get("/{room_id}", response_model=RoomOut)
def get_room(room_id: str, session: Session = Depends(get_session)):
    room = session.query(Room).filter_by(id=room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    return room
