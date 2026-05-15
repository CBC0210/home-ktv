"""Library API — per-guest favorites, play history, and recommendations.

Backs the Remote "資料庫" tab:
  - 歷史記錄  : songs this guest has played (most-recent first, de-duped)
  - 喜歡的歌曲: songs this guest favorited (heart button)
  - 歌曲推薦  : same-artist songs + globally popular, excluding already-played
"""
from collections import OrderedDict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from ktv_pipeline.database import get_db_session
from ktv_pipeline.models import Song, Favorite, PlayHistory
from ktv_pipeline.deps import get_current_guest

router = APIRouter(prefix="/library", tags=["library"])


def get_session():
    with get_db_session() as session:
        yield session


def _song_dict(s: Song, favorited: bool = False) -> dict:
    return {
        "id": s.id,
        "title": s.title,
        "artist": s.artist,
        "duration_sec": s.duration_sec,
        "thumbnail_url": s.thumbnail_url,
        "status": s.status,
        "has_timing": s.has_timing,
        "play_count": s.play_count,
        "favorited": favorited,
    }


# ── Favorites ────────────────────────────────────────────────────────────────

@router.get("/favorites")
def list_favorites(
    payload: dict = Depends(get_current_guest),
    session: Session = Depends(get_session),
):
    gid = payload["sub"]
    rows = (
        session.query(Favorite)
        .filter_by(guest_id=gid)
        .order_by(Favorite.added_at.desc())
        .all()
    )
    songs = {s.id: s for s in session.query(Song).filter(
        Song.id.in_([r.song_id for r in rows])
    ).all()} if rows else {}
    return [
        _song_dict(songs[r.song_id], favorited=True)
        for r in rows if r.song_id in songs
    ]


@router.post("/favorites/{song_id}")
def add_favorite(
    song_id: str,
    payload: dict = Depends(get_current_guest),
    session: Session = Depends(get_session),
):
    gid = payload["sub"]
    if not session.query(Song).filter_by(id=song_id).first():
        raise HTTPException(status_code=404, detail="Song not found")
    exists = session.query(Favorite).filter_by(guest_id=gid, song_id=song_id).first()
    if not exists:
        session.add(Favorite(guest_id=gid, song_id=song_id))
        session.commit()
    return {"ok": True, "favorited": True, "song_id": song_id}


@router.delete("/favorites/{song_id}")
def remove_favorite(
    song_id: str,
    payload: dict = Depends(get_current_guest),
    session: Session = Depends(get_session),
):
    gid = payload["sub"]
    session.query(Favorite).filter_by(guest_id=gid, song_id=song_id).delete()
    session.commit()
    return {"ok": True, "favorited": False, "song_id": song_id}


@router.get("/favorites/{song_id}/status")
def favorite_status(
    song_id: str,
    payload: dict = Depends(get_current_guest),
    session: Session = Depends(get_session),
):
    gid = payload["sub"]
    fav = session.query(Favorite).filter_by(guest_id=gid, song_id=song_id).first()
    return {"song_id": song_id, "favorited": fav is not None}


# ── History ──────────────────────────────────────────────────────────────────

@router.get("/history")
def list_history(
    limit: int = 50,
    payload: dict = Depends(get_current_guest),
    session: Session = Depends(get_session),
):
    """Distinct songs this guest has played, most-recent first."""
    gid = payload["sub"]
    rows = (
        session.query(PlayHistory.song_id, func.max(PlayHistory.played_at).label("last"))
        .filter_by(guest_id=gid)
        .group_by(PlayHistory.song_id)
        .order_by(func.max(PlayHistory.played_at).desc())
        .limit(max(1, min(limit, 200)))
        .all()
    )
    if not rows:
        return []
    ids = [r.song_id for r in rows]
    songs = {s.id: s for s in session.query(Song).filter(Song.id.in_(ids)).all()}
    fav_ids = {
        f.song_id for f in session.query(Favorite)
        .filter(Favorite.guest_id == gid, Favorite.song_id.in_(ids)).all()
    }
    out = []
    for r in rows:
        s = songs.get(r.song_id)
        if s:
            out.append(_song_dict(s, favorited=s.id in fav_ids))
    return out


# ── Recommendations ──────────────────────────────────────────────────────────

@router.get("/recommendations")
def recommendations(
    limit: int = 20,
    payload: dict = Depends(get_current_guest),
    session: Session = Depends(get_session),
):
    """Recommend songs from artists the guest likes/played, then globally
    popular ones — excluding songs the guest has already played."""
    gid = payload["sub"]
    limit = max(1, min(limit, 50))

    played_ids = {
        r[0] for r in session.query(PlayHistory.song_id)
        .filter_by(guest_id=gid).distinct().all()
    }
    fav_ids = {
        f.song_id for f in session.query(Favorite).filter_by(guest_id=gid).all()
    }

    # Artists + genres the guest engaged with (from favorites + history)
    seed_ids = list(fav_ids | played_ids)
    artists: set[str] = set()
    genres: set[str] = set()
    if seed_ids:
        for s in session.query(Song).filter(Song.id.in_(seed_ids)).all():
            if s.artist:
                artists.add(s.artist.strip())
            g = (s.extra_metadata or {}).get("genre")
            if g:
                genres.add(g.strip())

    recs: "OrderedDict[str, Song]" = OrderedDict()

    # 1. Same-artist ready songs not yet played (strongest signal)
    if artists:
        same = (
            session.query(Song)
            .filter(Song.status == "ready", Song.artist.in_(artists))
            .order_by(Song.play_count.desc())
            .limit(limit * 2)
            .all()
        )
        for s in same:
            if s.id not in played_ids and s.id not in recs:
                recs[s.id] = s

    # 2. Same-genre ready songs (broader taste match)
    if genres and len(recs) < limit:
        candidates = (
            session.query(Song)
            .filter(Song.status == "ready")
            .order_by(Song.play_count.desc())
            .limit(limit * 6)
            .all()
        )
        for s in candidates:
            g = (s.extra_metadata or {}).get("genre")
            if g and g.strip() in genres and s.id not in played_ids and s.id not in recs:
                recs[s.id] = s
            if len(recs) >= limit:
                break

    # 3. Fill with globally most-played ready songs
    if len(recs) < limit:
        popular = (
            session.query(Song)
            .filter(Song.status == "ready")
            .order_by(Song.play_count.desc())
            .limit(limit * 3)
            .all()
        )
        for s in popular:
            if s.id not in played_ids and s.id not in recs:
                recs[s.id] = s
            if len(recs) >= limit:
                break

    return [
        _song_dict(s, favorited=s.id in fav_ids)
        for s in list(recs.values())[:limit]
    ]
