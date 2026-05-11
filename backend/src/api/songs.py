"""Songs API — search, create from YouTube URL, trigger pipeline."""
import re
import asyncio
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from sqlalchemy.orm import Session

from ktv_pipeline.database import get_db_session
from ktv_pipeline.models import Song, QueueItem, Room
from ktv_pipeline.schemas import SongCreate, SongOut, QueueItemOut
from ktv_pipeline.deps import get_current_guest
from ktv_pipeline.queue_manager import QueueManager

router = APIRouter(prefix="/songs", tags=["songs"])


def get_session():
    with get_db_session() as session:
        yield session


# ── Helpers ──────────────────────────────────────────────────────────────────

YOUTUBE_ID_RE = re.compile(
    r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/)([a-zA-Z0-9_-]{11})"
)


def extract_youtube_id(url_or_id: str) -> str:
    """Return the 11-char YouTube video ID from a URL or bare ID."""
    m = YOUTUBE_ID_RE.search(url_or_id)
    if m:
        return m.group(1)
    if len(url_or_id) == 11 and re.match(r"^[a-zA-Z0-9_-]+$", url_or_id):
        return url_or_id
    raise HTTPException(status_code=400, detail=f"Invalid YouTube ID: {url_or_id}")


def _run_pipeline_sync(queue_item_id: int) -> None:
    """Sync wrapper — runs the async pipeline in a new event loop (for background tasks)."""
    import asyncio
    import sys, os
    # Ensure ktv_pipeline is importable
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))
    from ktv_pipeline.pipeline_orchestrator import PipelineOrchestrator
    from ktv_pipeline.config import settings as s
    from ktv_pipeline.database import init_db
    init_db()
    config = PipelineOrchestrator.Config(
        max_retries=s.pipeline_max_retries,
        heartbeat_interval_sec=s.pipeline_heartbeat_sec,
        total_timeout_sec=s.song_total_timeout_sec,
    )
    orch = PipelineOrchestrator(config)
    asyncio.run(orch.run_from_queue(queue_item_id))


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/search", response_model=list[SongOut])
def search_songs(q: str = "", limit: int = 20, session: Session = Depends(get_session)):
    """Search songs by title or artist."""
    query = session.query(Song)
    if q:
        query = query.filter(
            (Song.title.ilike(f"%{q}%")) | (Song.artist.ilike(f"%{q}%"))
        )
    return query.order_by(Song.play_count.desc()).limit(limit).all()


@router.get("/{song_id}", response_model=SongOut)
def get_song(song_id: str, session: Session = Depends(get_session)):
    """Get a song by ID (or YouTube URL)."""
    try:
        yt_id = extract_youtube_id(song_id)
    except HTTPException:
        raise HTTPException(status_code=400, detail=f"Invalid song ID format: {song_id}")

    song = session.query(Song).filter_by(id=yt_id).first()
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")
    return song


@router.post("", response_model=SongOut, summary="Add a song by YouTube URL")
def add_song(
    data: SongCreate,
    background_tasks: BackgroundTasks,
    payload: dict = Depends(get_current_guest),
    session: Session = Depends(get_session),
):
    """Add a song (by YouTube URL or ID) to a room's queue and trigger pipeline processing.

    If the song already exists in the DB it is reused (no duplicate pipeline run).
    If the song exists but is not yet ready, the existing queue item is returned.
    New songs are created with status='pending' and processing is triggered in background.
    """
    room_id = data.room_id

    # Verify room exists
    room = session.query(Room).filter_by(id=room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    guest_id = payload["sub"]
    yt_id = extract_youtube_id(data.youtube_url)

    # Check if song already exists
    song = session.query(Song).filter_by(id=yt_id).first()

    if not song:
        # Create new song record
        song = Song(
            id=yt_id,
            title=f"YouTube:{yt_id}",  # placeholder; pipeline updates after download
            artist="",
            status="pending",
        )
        session.add(song)
        session.commit()
        session.refresh(song)

    # Check if already in queue (pending/processing) — reuse rather than duplicate
    existing_item = (
        session.query(QueueItem)
        .filter_by(room_id=room_id, song_id=yt_id)
        .filter(QueueItem.status.in_(["pending", "processing", "playing"]))
        .first()
    )
    if existing_item:
        return QueueItemOut.model_validate(existing_item)

    # Add to queue
    mgr = QueueManager(session)
    try:
        item = mgr.add_song(room_id=room_id, song_id=yt_id, guest_id=guest_id, position="end")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    # Trigger pipeline in background if song not ready
    if song.status != "ready":
        background_tasks.add_task(_run_pipeline_sync, item.id)

    return QueueItemOut.model_validate(item)


@router.get("/{song_id}/status")
def song_status(song_id: str, session: Session = Depends(get_session)):
    """Get the processing status of a song (pipeline state + queue info)."""
    try:
        yt_id = extract_youtube_id(song_id)
    except HTTPException:
        raise HTTPException(status_code=400, detail="Invalid YouTube ID")

    song = session.query(Song).filter_by(id=yt_id).first()
    if not song:
        return {"error": "not_found"}

    queue_items = session.query(QueueItem).filter_by(song_id=yt_id).all()

    return {
        "song_id": yt_id,
        "status": song.status,  # pending/processing/ready/failed_perm
        "error_message": song.error_message,
        "queue_items": [
            {
                "id": qi.id,
                "room_id": qi.room_id,
                "position": qi.position,
                "queue_status": qi.status,
            }
            for qi in queue_items
        ],
    }