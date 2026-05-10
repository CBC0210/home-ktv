"""Songs API routes。"""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from ktv_pipeline.database import get_db_session
from ktv_pipeline.models import Song
from ktv_pipeline.schemas import SongOut

router = APIRouter(prefix="/songs", tags=["songs"])


def get_session():
    with get_db_session() as session:
        yield session


@router.get("/{song_id}", response_model=SongOut)
def get_song(song_id: str, session: Session = Depends(get_session)):
    song = session.query(Song).filter_by(id=song_id).first()
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")
    return song


@router.get("")
def search_songs(q: str = "", limit: int = 20, session: Session = Depends(get_session)):
    query = session.query(Song)
    if q:
        query = query.filter((Song.title.ilike(f"%{q}%")) | (Song.artist.ilike(f"%{q}%")))
    return query.order_by(Song.play_count.desc()).limit(limit).all()
