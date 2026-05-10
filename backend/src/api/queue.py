"""Queue API routes。"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from ktv_pipeline.database import get_db_session
from ktv_pipeline.models import QueueItem, Room
from ktv_pipeline.schemas import QueueItemCreate, QueueItemOut

router = APIRouter(prefix="/queue", tags=["queue"])


def get_session():
    with get_db_session() as session:
        yield session


@router.get("/room/{room_id}", response_model=list[QueueItemOut])
def list_queue(room_id: str, session: Session = Depends(get_session)):
    return session.query(QueueItem).filter_by(room_id=room_id).order_by(QueueItem.position).all()


@router.post("", response_model=QueueItemOut)
def add_to_queue(data: QueueItemCreate, guest_id: str, room_id: str, session: Session = Depends(get_session)):
    room = session.query(Room).filter_by(id=room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    last_of_guest = session.query(QueueItem).filter_by(guest_id=guest_id).order_by(QueueItem.position.desc()).first()
    max_pos = last_of_guest.position + 2 if last_of_guest else session.query(QueueItem).filter_by(room_id=room_id).count()
    item = QueueItem(room_id=room_id, song_id=data.song_id, guest_id=guest_id, position=max_pos, status="pending")
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


@router.delete("/{item_id}")
def remove_from_queue(item_id: int, session: Session = Depends(get_session)):
    item = session.query(QueueItem).filter_by(id=item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")
    session.delete(item)
    session.commit()
    return {"ok": True}
