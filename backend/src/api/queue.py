"""Queue API routes — add, remove, reorder, list."""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from ktv_pipeline.database import get_db_session
from ktv_pipeline.models import QueueItem, Room, Guest, Song
from ktv_pipeline.schemas import QueueItemCreate, QueueItemOut
from ktv_pipeline.queue_manager import QueueManager
from ktv_pipeline.deps import get_current_guest


router = APIRouter(prefix="/queue", tags=["queue"])


def get_session():
    with get_db_session() as session:
        yield session


@router.get("/room/{room_id}", response_model=list[QueueItemOut])
def list_queue(room_id: str, session: Session = Depends(get_session)):
    """Get the queue for a room, ordered by position."""
    mgr = QueueManager(session)
    items = mgr.get_queue(room_id)
    return items


@router.post("", response_model=QueueItemOut)
def add_to_queue(
    data: QueueItemCreate,
    room_id: str,
    payload: dict = Depends(get_current_guest),
    session: Session = Depends(get_session),
):
    """Add a song to the queue. Requires authentication.
    
    The song is processed through the pipeline (if not already ready).
    On success, the queue item is created with status='processing'.
    """
    guest_id = payload["sub"]

    # Verify room exists
    room = session.query(Room).filter_by(id=room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # Verify song exists (or trigger pipeline for new YouTube URL)
    song = session.query(Song).filter_by(id=data.song_id).first()
    if not song:
        # TODO: trigger pipeline for a new song (M2-T6)
        raise HTTPException(status_code=404, detail=f"Song '{data.song_id}' not found or not yet processed")

    mgr = QueueManager(session)
    try:
        item = mgr.add_song(
            room_id=room_id,
            song_id=data.song_id,
            guest_id=guest_id,
            position=data.position or "end",
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    return QueueItemOut.model_validate(item)


@router.patch("/room/{room_id}/reorder")
def reorder_queue(
    room_id: str,
    ordered_item_ids: list[int],
    payload: dict = Depends(get_current_guest),
    session: Session = Depends(get_session),
):
    """Reorder the queue. Admin only."""
    if not payload.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin only")

    mgr = QueueManager(session)
    mgr.reorder(room_id, ordered_item_ids)
    return {"status": "ok", "ordered_item_ids": ordered_item_ids}


@router.delete("/{item_id}")
def remove_from_queue(
    item_id: int,
    payload: dict = Depends(get_current_guest),
    session: Session = Depends(get_session),
):
    """Remove a song from the queue."""
    mgr = QueueManager(session)
    item = session.query(QueueItem).filter_by(id=item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")

    # Only the guest who added it or admin can remove
    if item.guest_id != payload["sub"] and not payload.get("is_admin"):
        raise HTTPException(status_code=403, detail="Not authorized to remove this item")

    mgr.remove_item(item_id)
    return {"ok": True}


@router.post("/{item_id}/play")
def start_playing(
    item_id: int,
    payload: dict = Depends(get_current_guest),
    session: Session = Depends(get_session),
):
    """Mark a queue item as currently playing. Admin only."""
    if not payload.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin only")

    mgr = QueueManager(session)
    item = mgr.mark_playing(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")
    return QueueItemOut.model_validate(item)


@router.post("/{item_id}/done")
def finish_playing(
    item_id: int,
    payload: dict = Depends(get_current_guest),
    session: Session = Depends(get_session),
):
    """Mark a queue item as done (playback finished). Admin only."""
    if not payload.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin only")

    mgr = QueueManager(session)
    item = session.query(QueueItem).filter_by(id=item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")
    mgr.mark_done(item_id)
    return {"ok": True}