"""Guests API routes。"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from ktv_pipeline.database import get_db_session
from ktv_pipeline.models import Guest
from ktv_pipeline.schemas import GuestCreate, GuestOut

router = APIRouter(prefix="/guests", tags=["guests"])


def get_session():
    with get_db_session() as session:
        yield session


@router.get("/{guest_id}", response_model=GuestOut)
def get_guest(guest_id: str, session: Session = Depends(get_session)):
    guest = session.query(Guest).filter_by(id=guest_id).first()
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")
    return guest


@router.post("", response_model=GuestOut)
def create_or_update_guest(data: GuestCreate, session: Session = Depends(get_session)):
    guest = session.query(Guest).filter_by(nickname=data.nickname).first()
    if not guest:
        guest = Guest(nickname=data.nickname, avatar_color="#7c3aed")
        session.add(guest)
        session.commit()
        session.refresh(guest)
    return guest
