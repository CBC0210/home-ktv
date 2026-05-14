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

    def _convert() -> bool:
        try:
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", str(wav_path),
                 "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
                 "-c:a", "libopus", "-b:a", "128k", "-vbr", "on",
                 str(opus_path)],
                capture_output=True, timeout=300,
            )
            return result.returncode == 0
        except Exception:
            return False

    loop = asyncio.get_event_loop()
    ok = await loop.run_in_executor(None, _convert)
    _opus_converting.discard(key)
    if ok:
        log.info("Converted %s → %s", wav_path.name, opus_path.name)
        return opus_path
    return None


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
    session: Session = Depends(get_session),
):
    """Stream the video.mp4 with HTTP Range support (required for browser seeking)."""
    song = session.query(Song).filter_by(id=song_id).first()
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")

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
    session: Session = Depends(get_session),
):
    """Stream an audio file (vocals.wav / no_vocals.wav) with range-request support.

    Serves the Opus-encoded version when available (much smaller than WAV).
    Triggers background Opus conversion on first request so subsequent plays are faster.
    """
    song = session.query(Song).filter_by(id=song_id).first()
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")
    if song.status != "ready":
        raise HTTPException(status_code=202, detail=f"Song status is '{song.status}', not ready")

    if filename not in ("vocals.wav", "no_vocals.wav", "audio.m4a"):
        raise HTTPException(status_code=403, detail="Invalid filename")

    wav_path = _song_cache_dir(song_id) / filename
    if not wav_path.exists():
        raise HTTPException(status_code=404, detail=f"File '{filename}' not found")

    # Prefer Opus (much smaller, fast-start); trigger conversion if not yet done
    opus_path = wav_path.with_suffix(".opus")
    if opus_path.exists():
        audio_path = opus_path
        media_type = "audio/ogg; codecs=opus"
    else:
        # Start background conversion (first play will use WAV; subsequent plays Opus)
        asyncio.create_task(_ensure_opus(wav_path))
        audio_path = wav_path
        media_type = "audio/wav"

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