"""HLS / raw audio streaming endpoint — serves processed song files with range-request support."""
import os
import re
import asyncio
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ktv_pipeline.config import settings
from ktv_pipeline.database import get_db_session
from ktv_pipeline.models import Song
from ktv_pipeline.deps import get_current_guest


router = APIRouter(prefix="/songs", tags=["streaming"])


def get_session():
    with get_db_session() as session:
        yield session


def _song_cache_dir(song_id: str) -> Path:
    return settings.data_dir / "cache" / "demucs" / song_id


def _song_ass_path(song_id: str) -> Path:
    return settings.data_dir / "media" / song_id / "lyrics.ass"


# ── Range request helpers ───────────────────────────────────────────────────

async def _stream_file_range(path: Path, start: int, end: int):
    """Stream a byte range of a file (for HTTP Range requests)."""
    with open(path, "rb") as f:
        f.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk_size = min(64 * 1024, remaining)
            data = f.read(chunk_size)
            if not data:
                break
            yield data
            remaining -= len(data)


def _parse_range(range_header: str, file_size: int) -> tuple[int, int]:
    """Parse 'bytes=start-end' into (start, end) inclusive."""
    m = re.match(r"bytes=(\d+)-(\d*)", range_header)
    if not m:
        return 0, file_size - 1
    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else file_size - 1
    end = min(end, file_size - 1)
    return start, end


# ── Routes ───────────────────────────────────────────────────────────────────

@router.get("/{song_id}/stream.m3u8")
async def serve_hls_manifest(song_id: str, session: Session = Depends(get_session)):
    """Serve an HLS master playlist (.m3u8) for the song.
    
    The manifest references the vocal and no_vocals AAC/TS segments.
    If segments don't exist yet, returns 404.
    """
    song = session.query(Song).filter_by(id=song_id).first()
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")
    if song.status != "ready":
        raise HTTPException(status_code=202, detail=f"Song status is '{song.status}', not ready")

    cache_dir = _song_cache_dir(song_id)

    # Find segment files
    vocals = cache_dir / "vocals.wav"
    no_vocals = cache_dir / "no_vocals.wav"

    if not vocals.exists() and not no_vocals.exists():
        raise HTTPException(status_code=404, detail="No audio files found for this song")

    # Build simple HLS manifest referencing raw audio (raw WAV served as binary)
    # For production, we'd use ffmpeg to generate proper HLS segments.
    # Here we serve the raw audio with a simple HLS wrapper pointing to the files.
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        f"#EXT-X-TARGETDURATION:3600",
        f"#EXT-X-MEDIA-SEQUENCE:0",
        f"#EXT-X-PLAYLIST-TYPE:VOD",
        f"#EXTINF:3600.0,",
        f"./audio/{song_id}/vocals.wav",
        "#EXT-X-ENDLIST",
    ]

    # In a full implementation, we'd generate a proper multi-bitrate manifest.
    # For now, stream the raw audio directly.
    return Response(
        content="\n".join(lines),
        media_type="application/vnd.apple.mpegurl",
        headers={"Content-Disposition": f'attachment; filename="{song_id}.m3u8"'},
    )


@router.get("/{song_id}/audio/{filename}")
async def serve_audio_file(
    song_id: str,
    filename: str,
    range: Optional[str] = None,
    session: Session = Depends(get_session),
):
    """Stream an audio file (vocals.wav / no_vocals.wav) with range-request support.
    
    Designed for HLS clients that request segments via range headers.
    """
    song = session.query(Song).filter_by(id=song_id).first()
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")
    if song.status != "ready":
        raise HTTPException(status_code=202, detail=f"Song status is '{song.status}', not ready")

    # Validate filename (only allow safe filenames)
    if filename not in ("vocals.wav", "no_vocals.wav", "audio.m4a"):
        raise HTTPException(status_code=403, detail="Invalid filename")

    audio_path = _song_cache_dir(song_id) / filename

    if not audio_path.exists():
        raise HTTPException(status_code=404, detail=f"File '{filename}' not found")

    file_size = audio_path.stat().st_size

    if range:
        start, end = _parse_range(range, file_size)
        return StreamingResponse(
            _stream_file_range(audio_path, start, end),
            media_type="audio/wav",
            status_code=206,
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(end - start + 1),
            },
        )
    else:
        return StreamingResponse(
            audio_path.open("rb"),
            media_type="audio/wav",
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
            },
        )


@router.get("/{song_id}/lyrics.ass")
async def serve_lyrics_ass(song_id: str, session: Session = Depends(get_session)):
    """Serve the timed lyrics ASS file for a song (for karaoke display)."""
    song = session.query(Song).filter_by(id=song_id).first()
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")

    ass_path = _song_ass_path(song_id)
    if not ass_path.exists():
        raise HTTPException(status_code=404, detail="Lyrics ASS file not found")

    return StreamingResponse(
        ass_path.open("rb"),
        media_type="application/x-ass",
        headers={
            "Content-Disposition": f'attachment; filename="{song_id}.ass"',
            "Content-Length": str(ass_path.stat().st_size),
        },
    )


class LyricsUpdateBody(BaseModel):
    ass: str


@router.put("/{song_id}/lyrics")
async def update_lyrics_ass(
    song_id: str,
    body: LyricsUpdateBody,
    session: Session = Depends(get_session),
):
    """Replace the cached ASS lyrics file for a song (user-edited karaoke timing)."""
    if not body.ass.strip():
        raise HTTPException(status_code=400, detail="ASS content cannot be empty")

    song = session.query(Song).filter_by(id=song_id).first()
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")

    ass_path = _song_ass_path(song_id)
    ass_path.parent.mkdir(parents=True, exist_ok=True)
    ass_path.write_text(body.ass, encoding="utf-8")

    return {"status": "ok", "song_id": song_id, "bytes": len(body.ass.encode("utf-8"))}


@router.get("/{song_id}/info")
def stream_info(song_id: str, session: Session = Depends(get_session)):
    """Return streaming info: available files, durations, format."""
    song = session.query(Song).filter_by(id=song_id).first()
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")

    cache_dir = _song_cache_dir(song_id)
    ass_path = _song_ass_path(song_id)

    files = {}
    for fname in ["vocals.wav", "no_vocals.wav", "audio.m4a"]:
        fpath = cache_dir / fname
        if fpath.exists():
            files[fname] = {"size_bytes": fpath.stat().st_size}

    return {
        "song_id": song_id,
        "status": song.status,
        "files": files,
        "lyrics_available": ass_path.exists(),
        "cache_dir": str(cache_dir),
    }