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


@router.get("/{room_id}/stats")
def get_room_stats(room_id: str, session: Session = Depends(get_session)):
    """Get room statistics from PlayHistory."""
    from ktv_pipeline.models import PlayHistory, Song, QueueItem
    from sqlalchemy import func

    # Verify room exists
    room = session.query(Room).filter_by(id=room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # Total songs played
    total_played = (
        session.query(func.count(PlayHistory.id))
        .filter_by(room_id=room_id)
        .scalar() or 0
    )

    # Unique songs
    unique_songs = (
        session.query(func.count(func.distinct(PlayHistory.song_id)))
        .filter_by(room_id=room_id)
        .scalar() or 0
    )

    # Total play time
    total_duration = (
        session.query(func.sum(PlayHistory.duration_sec))
        .filter_by(room_id=room_id)
        .scalar() or 0
    )

    # Top songs (by play count)
    top_songs_rows = (
        session.query(
            PlayHistory.song_id,
            func.count(PlayHistory.id).label("play_count"),
            func.sum(PlayHistory.duration_sec).label("total_duration"),
        )
        .filter_by(room_id=room_id)
        .group_by(PlayHistory.song_id)
        .order_by(func.count(PlayHistory.id).desc())
        .limit(10)
        .all()
    )

    song_ids = [r.song_id for r in top_songs_rows]
    songs_map = {s.id: s for s in session.query(Song).filter(Song.id.in_(song_ids)).all()}

    top_songs = []
    for row in top_songs_rows:
        song = songs_map.get(row.song_id)
        top_songs.append({
            "song_id": row.song_id,
            "title": song.title if song else row.song_id,
            "artist": song.artist if song else None,
            "thumbnail_url": song.thumbnail_url if song else None,
            "play_count": row.play_count,
            "total_duration_sec": row.total_duration or 0,
        })

    # Recent plays (last 10)
    recent_rows = (
        session.query(PlayHistory)
        .filter_by(room_id=room_id)
        .order_by(PlayHistory.played_at.desc())
        .limit(10)
        .all()
    )

    # Avg rating
    avg_rating = (
        session.query(func.avg(PlayHistory.rating))
        .filter_by(room_id=room_id)
        .filter(PlayHistory.rating.isnot(None))
        .scalar()
    )

@router.get("/{room_id}/stats/processing")
def get_processing_stats(room_id: str, session: Session = Depends(get_session)):
    """Get processing statistics for songs in a room's queue."""
    from ktv_pipeline.models import Song, QueueItem
    from sqlalchemy import func

    # Verify room exists
    room = session.query(Room).filter_by(id=room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # Get all song IDs in this room's queue
    queue_song_ids = (
        session.query(QueueItem.song_id)
        .filter_by(room_id=room_id)
        .distinct()
        .all()
    )
    song_ids = [r.song_id for r in queue_song_ids]

    if not song_ids:
        return {"pending": 0, "processing": 0, "ready": 0, "failed_perm": 0, "failed_temp": 0}

    counts = (
        session.query(Song.status, func.count(Song.id))
        .filter(Song.id.in_(song_ids))
        .group_by(Song.status)
        .all()
    )

    result = {"pending": 0, "processing": 0, "ready": 0, "failed_perm": 0, "failed_temp": 0}
    for status, count in counts:
        if status in result:
            result[status] = count

    return result

    return {
        "room_id": room_id,
        "total_songs_played": total_played,
        "unique_songs": unique_songs,
        "total_play_duration_sec": total_duration,
        "avg_rating": round(avg_rating, 1) if avg_rating else None,
        "top_songs": top_songs,
        "recent_plays": [
            {
                "song_id": p.song_id,
                "played_at": p.played_at.isoformat() if p.played_at else None,
                "duration_sec": p.duration_sec,
                "rating": p.rating,
            }
            for p in recent_rows
        ],
    }
