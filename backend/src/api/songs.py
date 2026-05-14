"""Songs API — search, create from YouTube URL, trigger pipeline."""
import re
import asyncio
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Request
from sqlalchemy.orm import Session
from sqlalchemy import func

from ktv_pipeline.database import get_db_session
from ktv_pipeline.models import Song, QueueItem, Room, PlayHistory
from ktv_pipeline.schemas import SongCreate, SongOut, QueueItemOut
from ktv_pipeline.deps import get_current_guest, get_optional_guest_dep
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


async def _try_start_if_idle(room_id: str) -> None:
    """Start next song only if nothing is currently playing (called after queue changes)."""
    from api.ws import _start_next_song
    await _start_next_song(room_id)


async def _run_pipeline_task(queue_item_id: int, room_id: str) -> None:
    """Async pipeline background task — runs pipeline then triggers auto-play."""
    from ktv_pipeline.pipeline_orchestrator import PipelineOrchestrator, PipelineConfig
    from ktv_pipeline.config import settings as s
    from ktv_pipeline.database import init_db
    init_db()
    config = PipelineConfig(
        max_retries=s.pipeline_max_retries,
        heartbeat_interval_sec=s.pipeline_heartbeat_sec,
        total_timeout_sec=s.song_total_timeout_sec,
    )
    orch = PipelineOrchestrator(config=config)

    # Broadcast immediately so remotes see "pending" / "processing" status
    await _broadcast_queue_update(room_id)

    # Periodic broadcast every 5 s so remotes see stage transitions during processing
    async def _periodic() -> None:
        for _ in range(300):  # up to 25 min
            await asyncio.sleep(5)
            await _broadcast_queue_update(room_id)

    periodic = asyncio.create_task(_periodic())
    try:
        result = await orch.run_from_queue(queue_item_id)
    finally:
        periodic.cancel()
        try:
            await periodic
        except asyncio.CancelledError:
            pass

    # Final broadcast (item is now "ready" or "failed_perm")
    await _broadcast_queue_update(room_id)

    if result.get("ok"):
        # Auto-start if nothing is currently playing
        from api.ws import _start_next_song
        await _start_next_song(room_id)


async def _broadcast_queue_update(room_id: str) -> None:
    """Reload and broadcast the current queue for a room."""
    from ktv_pipeline.ws_manager import manager
    from ktv_pipeline.queue_manager import QueueManager
    from ktv_pipeline.models import Song, Guest
    from api.ws import _qi_to_dict
    with get_db_session() as session:
        mgr = QueueManager(session)
        queue = mgr.get_queue(room_id)
        song_map = {s.id: s for s in session.query(Song).all()}
        guest_map = {g.id: g for g in session.query(Guest).all()}
        queue_dicts = [_qi_to_dict(qi, song_map.get(qi.song_id), guest_map.get(qi.guest_id)) for qi in queue]
    await manager.broadcast_queue_updated(room_id, queue_dicts)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/search", response_model=list[SongOut])
def search_songs(q: str = "", limit: int = 20, session: Session = Depends(get_session)):
    """Search songs by title or artist in local cache."""
    query = session.query(Song)
    if q:
        query = query.filter(
            (Song.title.ilike(f"%{q}%")) | (Song.artist.ilike(f"%{q}%"))
        )
    return query.order_by(Song.play_count.desc()).limit(limit).all()


@router.get("/youtube-search")
def youtube_search(q: str, limit: int = 10):
    """Search YouTube via yt-dlp and return video metadata (no processing)."""
    if not q.strip():
        return []
    try:
        import yt_dlp

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "default_search": "ytsearch",
            "noplaylist": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            result = ydl.extract_info(f"ytsearch{limit}:{q}", download=False)

        if not result or "entries" not in result:
            return []

        return [
            {
                "id": entry.get("id"),
                "title": entry.get("title"),
                "channel": entry.get("channel") or entry.get("uploader"),
                "duration_sec": entry.get("duration"),
                "thumbnail_url": entry.get("thumbnail"),
                "url": f"https://www.youtube.com/watch?v={entry.get('id')}",
                "cached": False,  # will be updated by frontend using local search
            }
            for entry in result.get("entries", [])
            if entry and entry.get("id")
        ]
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"YouTube search unavailable: {exc}")


@router.get("/leaderboard")
def get_leaderboard(
    category: str = "all_time",
    limit: int = 10,
    session: Session = Depends(get_session),
    payload: Optional[dict] = Depends(get_optional_guest_dep),
):
    """Return top songs for the given leaderboard category.

    Categories:
    - all_time: songs ordered by total play_count (all time)
    - monthly_hot: songs most played in the current calendar month
    - personal: songs most played by the authenticated guest (requires auth)
    """
    limit = max(1, min(limit, 50))

    if category == "all_time":
        agg = (
            session.query(
                PlayHistory.song_id,
                func.count(PlayHistory.id).label("period_count"),
            )
            .group_by(PlayHistory.song_id)
            .order_by(func.count(PlayHistory.id).desc())
            .limit(limit)
            .all()
        )
        if not agg:
            return []
        song_ids = [r.song_id for r in agg]
        songs_map = {s.id: s for s in session.query(Song).filter(Song.id.in_(song_ids)).all()}
        result = []
        for i, row in enumerate(agg):
            s = songs_map.get(row.song_id)
            if not s:
                continue
            result.append({
                "rank": i + 1,
                "song_id": s.id,
                "title": s.title,
                "artist": s.artist,
                "thumbnail_url": s.thumbnail_url,
                "duration_sec": s.duration_sec,
                "play_count": row.period_count,
                "last_played_at": s.last_played_at.isoformat() if s.last_played_at else None,
            })
        return result

    elif category == "monthly_hot":
        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        agg = (
            session.query(
                PlayHistory.song_id,
                func.count(PlayHistory.id).label("period_count"),
            )
            .filter(PlayHistory.played_at >= month_start)
            .group_by(PlayHistory.song_id)
            .order_by(func.count(PlayHistory.id).desc())
            .limit(limit)
            .all()
        )
        if not agg:
            return []

        song_ids = [r.song_id for r in agg]
        songs_map = {s.id: s for s in session.query(Song).filter(Song.id.in_(song_ids)).all()}

        result = []
        for i, row in enumerate(agg):
            s = songs_map.get(row.song_id)
            if not s:
                continue
            result.append({
                "rank": i + 1,
                "song_id": s.id,
                "title": s.title,
                "artist": s.artist,
                "thumbnail_url": s.thumbnail_url,
                "duration_sec": s.duration_sec,
                "play_count": row.period_count,
                "last_played_at": s.last_played_at.isoformat() if s.last_played_at else None,
            })
        return result

    elif category == "personal":
        if not payload:
            raise HTTPException(status_code=401, detail="Authentication required for personal leaderboard")

        guest_id = payload["sub"]
        agg = (
            session.query(
                PlayHistory.song_id,
                func.count(PlayHistory.id).label("period_count"),
            )
            .filter(PlayHistory.guest_id == guest_id)
            .group_by(PlayHistory.song_id)
            .order_by(func.count(PlayHistory.id).desc())
            .limit(limit)
            .all()
        )
        if not agg:
            return []

        song_ids = [r.song_id for r in agg]
        songs_map = {s.id: s for s in session.query(Song).filter(Song.id.in_(song_ids)).all()}

        result = []
        for i, row in enumerate(agg):
            s = songs_map.get(row.song_id)
            if not s:
                continue
            result.append({
                "rank": i + 1,
                "song_id": s.id,
                "title": s.title,
                "artist": s.artist,
                "thumbnail_url": s.thumbnail_url,
                "duration_sec": s.duration_sec,
                "play_count": row.period_count,
                "last_played_at": s.last_played_at.isoformat() if s.last_played_at else None,
            })
        return result

    else:
        raise HTTPException(status_code=400, detail=f"Unknown category: {category}. Use all_time, monthly_hot, or personal")


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

    # Check if already in queue (any active status) — reuse rather than duplicate
    existing_item = (
        session.query(QueueItem)
        .filter_by(room_id=room_id, song_id=yt_id)
        .filter(QueueItem.status.in_(["pending", "processing", "ready", "playing"]))
        .first()
    )
    if existing_item:
        session.refresh(song)
        # Song already in queue — still try to auto-start if nothing is playing yet
        background_tasks.add_task(_try_start_if_idle, room_id)
        return song

    # Add to queue
    mgr = QueueManager(session)
    try:
        item = mgr.add_song(room_id=room_id, song_id=yt_id, guest_id=guest_id, position=data.position or "end")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    if song.status == "ready":
        # Song already processed — try to auto-start if nothing is playing.
        background_tasks.add_task(_try_start_if_idle, room_id)
    else:
        # Trigger pipeline; periodic broadcasts + final broadcast happen inside the task.
        background_tasks.add_task(_run_pipeline_task, item.id, room_id)

    session.refresh(song)
    return song


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