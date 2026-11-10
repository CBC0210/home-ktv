"""HLS / raw audio streaming endpoint — serves processed song files with range-request support."""
import logging
import os
import re
import asyncio
import subprocess
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ktv_pipeline.config import settings
from ktv_pipeline.database import get_db_session
from ktv_pipeline.models import Song
from ktv_pipeline.deps import get_current_guest
from ktv_pipeline.auth import is_system_admin

log = logging.getLogger(__name__)

# Track in-progress Opus conversions so we don't spawn duplicates
_opus_converting: set[str] = set()


async def _ensure_opus(wav_path: Path) -> Optional[Path]:
    """Return the .opus path for a WAV file, converting if needed.

    Returns None while conversion is in progress or if ffmpeg is unavailable.
    Conversion is non-blocking — runs in a thread pool.
    """
    opus_path = wav_path.with_suffix(".opus")
    if opus_path.exists():
        return opus_path

    key = str(wav_path)
    if key in _opus_converting:
        return None  # Conversion in progress; caller falls back to WAV

    _opus_converting.add(key)

    try:
        from ktv_pipeline.pipeline_orchestrator import PipelineOrchestrator
        # Reuse atomic conversion and full duration/decode verification. This
        # background fallback never removes its source WAV.
        converted = await PipelineOrchestrator()._convert_opus_async(wav_path)
        return converted
    finally:
        _opus_converting.discard(key)


router = APIRouter(prefix="/songs", tags=["streaming"])


def get_session():
    with get_db_session() as session:
        yield session


def _song_cache_dir(song_id: str) -> Path:
    return settings.data_dir / "cache" / "demucs" / song_id


def _song_media_dir(song_id: str) -> Path:
    return settings.data_dir / "media" / song_id


def _song_ass_path(song_id: str) -> Path:
    return settings.data_dir / "media" / song_id / "lyrics.ass"


def _song_video_path(song_id: str) -> Path:
    """Return the video path, preferring the canonical media dir.

    yt-dlp downloads to cache/{song_id}/video.mp4, but the final destination
    per CLAUDE.md §16 is media/{song_id}/video.mp4.  Support both so that
    songs processed via the pipeline (cache path) and manually placed files
    (media path) both work.
    """
    media_path = settings.data_dir / "media" / song_id / "video.mp4"
    if media_path.exists():
        return media_path
    # Fallback: yt-dlp download cache
    return settings.data_dir / "cache" / song_id / "video.mp4"


def _stream_song_status(song_id: str) -> str:
    """Read status and release the DB connection before streaming starts.

    FastAPI keeps yielded dependencies alive until a StreamingResponse body is
    finished.  Holding a SQLAlchemy session here exhausts the small connection
    pool when browsers preload, seek, abort, or reconnect media requests.
    """
    with get_db_session() as session:
        song = session.query(Song).filter_by(id=song_id).first()
        if not song:
            raise HTTPException(status_code=404, detail="Song not found")
        return song.status


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
async def serve_hls_manifest(
    song_id: str,
    request: Request,
    session: Session = Depends(get_session),
):
    """Serve an HLS playlist (.m3u8) for the song video track.

    Points to the video.mp4 file via absolute URL so hls.js / Safari can resolve it
    regardless of the page origin.
    """
    song = session.query(Song).filter_by(id=song_id).first()
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")
    if song.status != "ready":
        raise HTTPException(status_code=202, detail=f"Song status is '{song.status}', not ready")

    # Build absolute URL for the segment — don't require file on disk here;
    # the video.mp4 endpoint returns 404 if the file is missing at that point.
    base = str(request.base_url).rstrip("/")
    video_url = f"{base}/songs/{song_id}/video.mp4"

    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        "#EXT-X-TARGETDURATION:3600",
        "#EXT-X-MEDIA-SEQUENCE:0",
        "#EXT-X-PLAYLIST-TYPE:VOD",
        "#EXTINF:3600.0,",
        video_url,
        "#EXT-X-ENDLIST",
    ]

    return Response(
        content="\n".join(lines),
        media_type="application/vnd.apple.mpegurl",
    )


@router.get("/{song_id}/video.mp4")
async def serve_video_file(
    song_id: str,
    request: Request,
):
    """Stream the video.mp4 with HTTP Range support (required for browser seeking)."""
    _stream_song_status(song_id)

    video_path = _song_video_path(song_id)
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Video file not found")

    file_size = video_path.stat().st_size
    range_header = request.headers.get("range")

    if range_header:
        start, end = _parse_range(range_header, file_size)
        return StreamingResponse(
            _stream_file_range(video_path, start, end),
            media_type="video/mp4",
            status_code=206,
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(end - start + 1),
            },
        )
    else:
        return StreamingResponse(
            video_path.open("rb"),
            media_type="video/mp4",
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
            },
        )


@router.get("/{song_id}/audio/{filename}")
async def serve_audio_file(
    song_id: str,
    filename: str,
    request: Request,
):
    """Stream an audio file (vocals.wav / no_vocals.wav) with range-request support.

    Serves the Opus-encoded version when available (much smaller than WAV).
    Triggers background Opus conversion on first request so subsequent plays are faster.
    """
    status = _stream_song_status(song_id)
    if status != "ready":
        raise HTTPException(status_code=202, detail=f"Song status is '{status}', not ready")

    if filename not in ("vocals.wav", "no_vocals.wav", "audio.m4a"):
        raise HTTPException(status_code=403, detail="Invalid filename")

    source_path = _song_cache_dir(song_id) / filename
    # A completed pipeline may deliberately remove its large WAV intermediates
    # after producing both verified Opus tracks.  The public URL remains the
    # historical ``*.wav`` URL, but its canonical playback asset is Opus.
    opus_path = source_path.with_suffix(".opus")
    if filename in ("vocals.wav", "no_vocals.wav") and (
        opus_path.is_file() and opus_path.stat().st_size > 0
    ):
        audio_path = opus_path
        media_type = "audio/ogg; codecs=opus"
    elif source_path.is_file() and source_path.stat().st_size > 0:
        audio_path = source_path
        media_type = "audio/wav" if filename.endswith(".wav") else "audio/mp4"
        # Start background conversion only for a remaining Demucs WAV.  m4a
        # files are original-audio fallbacks and are never converted here.
        if filename in ("vocals.wav", "no_vocals.wav"):
            asyncio.create_task(_ensure_opus(source_path))
    else:
        raise HTTPException(status_code=404, detail=f"File '{filename}' not found")

    file_size = audio_path.stat().st_size
    range_header = request.headers.get("range")

    if range_header:
        start, end = _parse_range(range_header, file_size)
        return StreamingResponse(
            _stream_file_range(audio_path, start, end),
            media_type=media_type,
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
            media_type=media_type,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
            },
        )


@router.get("/{song_id}/lyrics.txt")
async def serve_lyrics_txt(song_id: str, session: Session = Depends(get_session)):
    """Serve the plain-text lyrics for a song (for non-timed fallback display)."""
    song = session.query(Song).filter_by(id=song_id).first()
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")
    txt_path = settings.data_dir / "media" / song_id / "lyrics.txt"
    if not txt_path.exists():
        raise HTTPException(status_code=404, detail="Plain-text lyrics not available")
    return Response(content=txt_path.read_text(encoding="utf-8"), media_type="text/plain; charset=utf-8")


@router.get("/{song_id}/lyrics.ass")
async def serve_lyrics_ass(song_id: str, session: Session = Depends(get_session)):
    """Serve the timed lyrics ASS file for a song (for karaoke display).

    No-cache: lyrics may be edited live (lyrics.edit WS command), so we never
    want the browser to return a stale copy.
    """
    song = session.query(Song).filter_by(id=song_id).first()
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")

    ass_path = _song_ass_path(song_id)
    if not ass_path.exists():
        raise HTTPException(status_code=404, detail="Lyrics ASS file not found")

    return Response(
        content=ass_path.read_bytes(),
        media_type="application/x-ass",
        headers={
            "Cache-Control": "no-store, must-revalidate",
            "Pragma": "no-cache",
        },
    )


class LyricsUpdateBody(BaseModel):
    ass: str


@router.put("/{song_id}/lyrics")
async def update_lyrics_ass(
    song_id: str,
    body: LyricsUpdateBody,
    session: Session = Depends(get_session),
    payload: dict = Depends(get_current_guest),
):
    """Replace the cached ASS lyrics file for a song (user-edited karaoke timing).

    Requires a system-admin session. song_id is DB-constrained below (404 if
    the song doesn't exist), so it can't escape the media directory.
    """
    if not is_system_admin(payload):
        raise HTTPException(status_code=403, detail="System admin access required")

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
    for fname in ["vocals.wav", "no_vocals.wav"]:
        wav_path = cache_dir / fname
        opus_path = wav_path.with_suffix(".opus")
        if opus_path.is_file() and opus_path.stat().st_size > 0:
            files[fname] = {
                "size_bytes": opus_path.stat().st_size,
                "stored_as": opus_path.name,
                "format": "opus",
            }
        elif wav_path.is_file() and wav_path.stat().st_size > 0:
            files[fname] = {
                "size_bytes": wav_path.stat().st_size,
                "stored_as": wav_path.name,
                "format": "wav",
            }

    original_path = cache_dir / "audio.m4a"
    if original_path.is_file() and original_path.stat().st_size > 0:
        files["audio.m4a"] = {"size_bytes": original_path.stat().st_size}

    return {
        "song_id": song_id,
        "status": song.status,
        "files": files,
        "lyrics_available": ass_path.exists(),
        "cache_dir": str(cache_dir),
    }
