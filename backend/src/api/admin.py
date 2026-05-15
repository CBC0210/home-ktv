"""Admin API — password-protected admin endpoints for room management, error logs, and system status."""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Query
from sqlalchemy.orm import Session

from ktv_pipeline.database import get_db_session, get_gpu_status
from ktv_pipeline.models import Room, Song, QueueItem, ErrorLog
from ktv_pipeline.deps import get_current_guest


router = APIRouter(prefix="/admin", tags=["admin"])


def get_session():
    with get_db_session() as session:
        yield session


def require_admin(payload: dict = Depends(get_current_guest)) -> dict:
    if not payload.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin only")
    return payload


# ── Rooms ─────────────────────────────────────────────────────────────────────

@router.get("/rooms")
def list_rooms_admin(
    session: Session = Depends(get_session),
    _=Depends(require_admin),
):
    """List all rooms (admin view)."""
    rooms = session.query(Room).order_by(Room.created_at.desc()).all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "is_default": r.is_default,
            "has_password": bool(r.password_hash),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "settings": r.settings,
        }
        for r in rooms
    ]


@router.post("/rooms")
def create_room_admin(
    data: dict,
    session: Session = Depends(get_session),
    _=Depends(require_admin),
):
    """Create a new room with optional password."""
    room_id = data.get("id", "").strip()
    name = data.get("name", "").strip()
    password = data.get("password") or None

    if not room_id or not name:
        raise HTTPException(status_code=400, detail="id and name are required")

    existing = session.query(Room).filter_by(id=room_id).first()
    if existing:
        raise HTTPException(status_code=409, detail="Room already exists")

    from ktv_pipeline.auth import hash_password
    password_hash = hash_password(password) if password else None

    room = Room(id=room_id, name=name, password_hash=password_hash)
    session.add(room)
    session.commit()
    session.refresh(room)
    return {
        "id": room.id,
        "name": room.name,
        "is_default": room.is_default,
        "has_password": bool(room.password_hash),
        "created_at": room.created_at.isoformat() if room.created_at else None,
        "settings": room.settings,
    }


@router.delete("/rooms/{room_id}")
def delete_room_admin(
    room_id: str,
    session: Session = Depends(get_session),
    _=Depends(require_admin),
):
    """Delete a room and all its queue items."""
    room = session.query(Room).filter_by(id=room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    session.query(QueueItem).filter_by(room_id=room_id).delete()
    session.delete(room)
    session.commit()
    return {"status": "ok", "deleted": room_id}


@router.patch("/rooms/{room_id}/password")
def change_room_password(
    room_id: str,
    data: dict,
    session: Session = Depends(get_session),
    _=Depends(require_admin),
):
    """Change room password (set password to null to remove)."""
    new_password = data.get("password")
    room = session.query(Room).filter_by(id=room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    from ktv_pipeline.auth import hash_password
    room.password_hash = hash_password(new_password) if new_password else None
    session.commit()
    return {"status": "ok", "room_id": room_id, "has_password": bool(new_password)}


# ── Detail views (room overview + per-guest drill-down) ─────────────────────

@router.get("/rooms/{room_id}/detail")
def room_detail(
    room_id: str,
    session: Session = Depends(get_session),
    _=Depends(require_admin),
):
    """Everything about a room: connected guests, queue, processing
    breakdown, and play stats — one call powering the admin room panel."""
    from ktv_pipeline.models import Guest, QueueItem, Song, PlayHistory
    from ktv_pipeline.ws_manager import manager
    from sqlalchemy import func

    room = session.query(Room).filter_by(id=room_id).first()
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")

    # Connected guests (live WS), enriched with per-guest play counts
    client_ids = {
        c.guest_id for c in manager.get_room_clients(room_id) if c.guest_id
    }
    guest_rows = (
        session.query(Guest).filter(Guest.id.in_(client_ids)).all()
        if client_ids else []
    )
    play_counts = dict(
        session.query(PlayHistory.guest_id, func.count(PlayHistory.id))
        .filter(PlayHistory.room_id == room_id)
        .group_by(PlayHistory.guest_id)
        .all()
    )
    guests = [
        {
            "id": g.id,
            "nickname": g.nickname,
            "avatar_color": g.avatar_color,
            "is_admin": g.is_admin,
            "plays_here": int(play_counts.get(g.id, 0)),
            "last_seen": g.last_seen.isoformat() if g.last_seen else None,
        }
        for g in guest_rows
    ]

    # Active queue with song + requester + processing state
    q = (
        session.query(QueueItem)
        .filter(QueueItem.room_id == room_id)
        .filter(QueueItem.status.in_(QueueManagerStatuses()))
        .order_by(QueueItem.position)
        .all()
    )
    song_map = {s.id: s for s in session.query(Song).all()}
    guest_map = {g.id: g for g in session.query(Guest).all()}
    queue = []
    for qi in q:
        s = song_map.get(qi.song_id)
        gg = guest_map.get(qi.guest_id)
        queue.append({
            "id": qi.id,
            "status": qi.status,
            "position": qi.position,
            "song_id": qi.song_id,
            "title": s.title if s else qi.song_id,
            "artist": s.artist if s else None,
            "song_status": s.status if s else None,
            "has_timing": s.has_timing if s else None,
            "lyrics_source": s.lyrics_source if s else None,
            "requested_by": gg.nickname if gg else None,
        })

    # Processing breakdown for songs in this room's active queue
    breakdown: dict = {}
    for qi in q:
        s = song_map.get(qi.song_id)
        st = s.status if s else "unknown"
        breakdown[st] = breakdown.get(st, 0) + 1

    total_played = (
        session.query(func.count(PlayHistory.id))
        .filter(PlayHistory.room_id == room_id).scalar() or 0
    )
    unique_songs = (
        session.query(func.count(func.distinct(PlayHistory.song_id)))
        .filter(PlayHistory.room_id == room_id).scalar() or 0
    )

    return {
        "room": {
            "id": room.id,
            "name": room.name,
            "is_default": room.is_default,
            "has_password": bool(room.password_hash),
            "has_admin_password": bool(room.admin_password_hash),
            "created_at": room.created_at.isoformat() if room.created_at else None,
        },
        "online_guests": guests,
        "online_count": len(guests),
        "queue": queue,
        "queue_count": len(queue),
        "processing_breakdown": breakdown,
        "stats": {
            "total_played": int(total_played),
            "unique_songs": int(unique_songs),
        },
    }


def QueueManagerStatuses():
    from ktv_pipeline.queue_manager import QueueManager
    return QueueManager.ACTIVE_STATUSES


@router.get("/guests/{guest_id}/detail")
def guest_detail(
    guest_id: str,
    session: Session = Depends(get_session),
    _=Depends(require_admin),
):
    """A guest's profile + recent play history + favorites."""
    from ktv_pipeline.models import Guest, PlayHistory, Favorite, Song
    from sqlalchemy import func

    g = session.query(Guest).filter_by(id=guest_id).first()
    if not g:
        raise HTTPException(status_code=404, detail="Guest not found")

    hist = (
        session.query(PlayHistory)
        .filter_by(guest_id=guest_id)
        .order_by(PlayHistory.played_at.desc())
        .limit(50)
        .all()
    )
    favs = (
        session.query(Favorite)
        .filter_by(guest_id=guest_id)
        .order_by(Favorite.added_at.desc())
        .all()
    )
    sid_set = {h.song_id for h in hist} | {f.song_id for f in favs}
    songs = {
        s.id: s for s in session.query(Song).filter(Song.id.in_(sid_set)).all()
    } if sid_set else {}

    def _s(sid):
        s = songs.get(sid)
        return {"id": sid, "title": s.title if s else sid,
                "artist": s.artist if s else None}

    total_plays = (
        session.query(func.count(PlayHistory.id))
        .filter_by(guest_id=guest_id).scalar() or 0
    )

    return {
        "guest": {
            "id": g.id,
            "nickname": g.nickname,
            "avatar_color": g.avatar_color,
            "is_admin": g.is_admin,
            "first_seen": g.first_seen.isoformat() if g.first_seen else None,
            "last_seen": g.last_seen.isoformat() if g.last_seen else None,
        },
        "total_plays": int(total_plays),
        "history": [
            {**_s(h.song_id),
             "played_at": h.played_at.isoformat() if h.played_at else None,
             "room_id": h.room_id}
            for h in hist
        ],
        "favorites": [_s(f.song_id) for f in favs],
    }


@router.get("/songs")
def list_saved_songs(
    session: Session = Depends(get_session),
    _=Depends(require_admin),
):
    """List every saved song with its on-disk footprint (media + cache +
    demucs), so the admin can see what's stored and prune big/unused ones."""
    import os
    from ktv_pipeline.config import settings

    def dir_size(p) -> int:
        if not os.path.isdir(p):
            return 0
        tot = 0
        for dp, _dn, fn in os.walk(p):
            for f in fn:
                try:
                    tot += os.path.getsize(os.path.join(dp, f))
                except OSError:
                    pass
        return tot

    data = str(settings.data_dir)
    songs = session.query(Song).order_by(Song.processed_at.desc()).all()
    out = []
    for s in songs:
        b = (
            dir_size(os.path.join(data, "media", s.id))
            + dir_size(os.path.join(data, "cache", s.id))
            + dir_size(os.path.join(data, "cache", "demucs", s.id))
        )
        out.append({
            "id": s.id,
            "title": s.title,
            "artist": s.artist,
            "status": s.status,
            "play_count": s.play_count or 0,
            "has_timing": s.has_timing,
            "lyrics_source": s.lyrics_source,
            "duration_sec": s.duration_sec,
            "last_played_at": s.last_played_at.isoformat() if s.last_played_at else None,
            "bytes": b,
            "human": _human_size(b),
        })
    out.sort(key=lambda x: x["bytes"], reverse=True)
    total = sum(x["bytes"] for x in out)
    return {"songs": out, "count": len(out), "total_bytes": total,
            "total_human": _human_size(total)}


# ── Song DB management (used by Remote admin mode + admin page) ──────────────

@router.delete("/songs/{song_id}")
def delete_song_admin(
    song_id: str,
    session: Session = Depends(get_session),
    payload: dict = Depends(get_current_guest),
):
    """Delete a song from the DB + remove its queue items + on-disk media.

    Allowed for any room admin (guest.is_admin=True after admin-mode verify).
    """
    if not payload.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin only")
    song = session.query(Song).filter_by(id=song_id).first()
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")
    # Remove queue items first (cascading)
    session.query(QueueItem).filter_by(song_id=song_id).delete()
    session.delete(song)
    session.commit()
    # Clean up media + cache directories on disk (best-effort)
    from ktv_pipeline.config import settings as cfg
    import shutil
    for sub in ("media", "cache", "cache/demucs"):
        path = cfg.data_dir / sub / song_id
        if path.exists():
            try:
                shutil.rmtree(path)
            except OSError:
                pass
    return {"status": "ok", "deleted": song_id}


@router.delete("/songs")
def clear_all_songs(
    session: Session = Depends(get_session),
    _=Depends(require_admin),
):
    """Wipe every song + queue item + on-disk media. System admin only."""
    n_queue = session.query(QueueItem).delete()
    n_songs = session.query(Song).delete()
    session.commit()
    from ktv_pipeline.config import settings as cfg
    import shutil
    for sub in ("media", "cache", "cache/demucs"):
        path = cfg.data_dir / sub
        if path.exists():
            for child in path.iterdir():
                try:
                    if child.is_dir():
                        shutil.rmtree(child)
                except OSError:
                    pass
    return {"status": "ok", "songs": n_songs, "queue_items": n_queue}


@router.delete("/leaderboard")
def clear_leaderboard(
    room_id: Optional[str] = Query(None, description="Limit to one room; omit = all"),
    session: Session = Depends(get_session),
    _=Depends(require_admin),
):
    """Wipe play history (the leaderboard data source). Also resets each
    song's play_count so 歷史經典/本月熱門 start fresh."""
    from ktv_pipeline.models import PlayHistory
    q = session.query(PlayHistory)
    if room_id:
        q = q.filter(PlayHistory.room_id == room_id)
    n = q.delete(synchronize_session=False)
    if not room_id:
        session.query(Song).update({"play_count": 0}, synchronize_session=False)
    session.commit()
    return {"status": "ok", "removed": n, "scope": room_id or "all"}


# ── Error Logs ────────────────────────────────────────────────────────────────

@router.get("/error-logs")
def list_error_logs(
    resolved: Optional[bool] = Query(None, description="Filter by resolved status"),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
    _=Depends(require_admin),
):
    """List error log entries with pagination."""
    q = session.query(ErrorLog)
    if resolved is not None:
        if resolved:
            q = q.filter(ErrorLog.resolved_at.isnot(None))
        else:
            q = q.filter(ErrorLog.resolved_at.is_(None))
    total = q.count()
    entries = (
        q.order_by(ErrorLog.occurred_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "total": total,
        "entries": [
            {
                "id": e.id,
                "occurred_at": e.occurred_at.isoformat() if e.occurred_at else None,
                "category": e.category,
                "severity": e.severity,
                "message": e.message,
                "context": e.context,
                "resolved_at": e.resolved_at.isoformat() if e.resolved_at else None,
                "resolution": e.resolution,
            }
            for e in entries
        ],
    }


@router.post("/error-logs/{log_id}/resolve")
def resolve_error_log(
    log_id: int,
    data: dict,
    session: Session = Depends(get_session),
    _=Depends(require_admin),
):
    """Mark an error log as resolved."""
    entry = session.query(ErrorLog).filter_by(id=log_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Error log not found")
    entry.resolved_at = datetime.now(timezone.utc)
    entry.resolution = data.get("resolution") or "Resolved by admin"
    session.commit()
    return {"status": "ok", "log_id": log_id, "resolved_at": entry.resolved_at.isoformat()}


@router.post("/error-logs/resolve-all")
def resolve_all_error_logs(
    session: Session = Depends(get_session),
    _=Depends(require_admin),
):
    """Mark all unresolved error logs as resolved."""
    now = datetime.now(timezone.utc)
    updated = (
        session.query(ErrorLog)
        .filter(ErrorLog.resolved_at.is_(None))
        .update({"resolved_at": now, "resolution": "Bulk resolved by admin"})
    )
    session.commit()
    return {"status": "ok", "resolved_count": updated}


# ── Cache / Disk ──────────────────────────────────────────────────────────────

@router.get("/cache-stats")
def cache_stats(_=Depends(require_admin)):
    """Return disk usage for data directory subfolders."""
    import os
    from ktv_pipeline.config import settings

    def walk_size(path: str) -> int:
        total = 0
        if not os.path.exists(path):
            return 0
        for dirpath, _dirnames, filenames in os.walk(path):
            for f in filenames:
                try:
                    total += os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    pass
        return total

    def disk_entry(sub: str) -> dict:
        p = os.path.join(str(settings.data_dir), sub)
        sz = walk_size(p)
        return {"bytes": sz, "human": _human_size(sz)}

    base = str(settings.data_dir)
    return {
        "media": disk_entry("media"),
        "cache": disk_entry("cache"),
        "logs": disk_entry("logs"),
        "tmp": disk_entry("tmp"),
        "total": disk_entry("."),
    }


@router.post("/cache/clear")
def clear_cache(
    data: dict,
    session: Session = Depends(get_session),
    _=Depends(require_admin),
):
    """Clear contents of cache/ and tmp/ subdirectories."""
    import os
    from ktv_pipeline.config import settings

    what = data.get("what", "all")  # "all", "cache", "tmp"
    base = str(settings.data_dir)
    cleared: list[dict] = []

    for sub in ("cache", "tmp"):
        if what not in ("all", sub):
            continue
        dir_path = os.path.join(base, sub)
        if not os.path.exists(dir_path):
            continue
        count = 0
        bytes_freed = 0
        for entry in os.scandir(dir_path):
            try:
                if entry.is_dir():
                    for dp, dn, fn in os.walk(entry.path):
                        for f in fn:
                            try:
                                bytes_freed += os.path.getsize(os.path.join(dp, f))
                                os.remove(os.path.join(dp, f))
                            except OSError:
                                pass
                        for d in dn:
                            try:
                                os.rmdir(os.path.join(dp, d))
                            except OSError:
                                pass
                    try:
                        os.rmdir(entry.path)
                    except OSError:
                        pass
                else:
                    bytes_freed += entry.stat().st_size
                    entry.unlink()
                count += 1
            except OSError:
                pass
        if count:
            cleared.append({"dir": sub, "files_removed": count, "bytes_freed": bytes_freed})

    return {"status": "ok", "cleared": cleared}


# ── System Status ──────────────────────────────────────────────────────────────

@router.get("/system-status")
def system_status(_=Depends(require_admin)):
    """GPU status, pending pipeline count, song stats."""
    from ktv_pipeline.database import check_db_connection
    from ktv_pipeline.config import settings

    gpu = get_gpu_status()
    db_ok = check_db_connection()

    with get_db_session() as s:
        pipeline_statuses = ["pending", "downloading", "separating", "fetching_lyrics", "aligning", "packaging"]
        pending_count = s.query(Song).filter(Song.status.in_(pipeline_statuses)).count()
        total_songs = s.query(Song).count()
        ready_songs = s.query(Song).filter_by(status="ready").count()
        failed_songs = s.query(Song).filter(Song.status.in_(["failed_perm", "failed_temp"])).count()

    return {
        "gpu": gpu,
        "db_connected": db_ok,
        "db_path": str(settings.db_path),
        "pipeline": {"pending_count": pending_count},
        "songs": {
            "total": total_songs,
            "ready": ready_songs,
            "failed": failed_songs,
        },
    }


def _human_size(num_bytes: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} PB"