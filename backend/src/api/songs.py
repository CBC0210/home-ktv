"""Songs API — search, create from YouTube URL, trigger pipeline."""
import re
import asyncio
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks, Request
from sqlalchemy.orm import Session
from sqlalchemy import func

from ktv_pipeline.database import get_db_session
from ktv_pipeline.models import Song, QueueItem, Room, PlayHistory, Guest
from ktv_pipeline.schemas import SongCreate, SongOut, QueueItemOut
from ktv_pipeline.deps import get_current_guest, get_optional_guest_dep
from ktv_pipeline.queue_manager import QueueManager

router = APIRouter(prefix="/songs", tags=["songs"])


def get_session():
    with get_db_session() as session:
        yield session


# ── Helpers ──────────────────────────────────────────────────────────────────

def _resolve_bili_short_link(url: str) -> Optional[str]:
    """Follow a Bilibili b23.tv / bili2233.cn short link to its final
    bilibili.com URL (the short link carries no BV id). Host-restricted so it
    can't be used as an SSRF primitive against arbitrary hosts."""
    if not re.match(r"^https?://(www\.)?(b23\.tv|bili2233\.cn)/", (url or "").strip(), re.I):
        return None
    import urllib.request
    try:
        req = urllib.request.Request(
            url.strip(), method="GET", headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.geturl()
    except Exception:
        return None


def extract_youtube_id(url_or_id: str) -> str:
    """Bare video id (YouTube *or* Bilibili) from a URL or id.

    Name kept for call-site stability; now source-agnostic — the returned
    id doubles as the song PK / cache dir regardless of source. Bilibili
    b23.tv short links (the app's default share format) are resolved first.
    """
    from ktv_pipeline.video_source import extract_video_id
    vid = extract_video_id(url_or_id)
    if not vid:
        resolved = _resolve_bili_short_link(url_or_id)
        if resolved:
            vid = extract_video_id(resolved)
    if vid:
        return vid
    raise HTTPException(status_code=400, detail=f"Invalid video URL/ID: {url_or_id}")


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
        # Background: pre-fetch every lyrics source so Remote switching is
        # instant (local file copy, no network round-trip).
        from ktv_pipeline.lyrics_prefetch import prefetch_all_lyrics
        with get_db_session() as _s:
            _qi = _s.query(QueueItem).filter_by(id=queue_item_id).first()
            _sid = _qi.song_id if _qi else None
        if _sid:
            asyncio.create_task(prefetch_all_lyrics(_sid))


async def _broadcast_queue_update(room_id: str) -> None:
    """Reload and broadcast the current queue for a room.

    Always re-materialises fair rotation first, so every broadcast shows the
    order songs will ACTUALLY play in (spec §4.3) — this is the central hook
    for the add-song / pipeline-progress paths."""
    from ktv_pipeline.ws_manager import manager
    from ktv_pipeline.queue_manager import QueueManager
    from ktv_pipeline.models import Song, Guest
    from api.ws import _qi_to_dict
    with get_db_session() as session:
        mgr = QueueManager(session)
        mgr.apply_fair_order(room_id)
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


_LANG_ORDER = ["zh", "en", "tw", "ja", "ko", "other"]


def _song_lang(song) -> str:
    """Exact catalog lang if the song was preinstalled, else best-effort
    text detection (台語 can't be told from 華語 by text → counts as zh)."""
    m = song.extra_metadata or {}
    lg = m.get("lang")
    if lg in _LANG_ORDER:
        return lg
    from ktv_pipeline.pipeline.lyrics import _detect_song_lang
    d = _detect_song_lang((song.title or "") + " " + (song.artist or ""))
    if d in ("zh", "ja", "ko"):
        return d
    # Char detection failed (e.g. a JP/KR song with an English/romaji
    # title like "YOASOBI - Idol"). Fall back to the LLM genre tag.
    g = (m.get("genre") or "")
    if any(k in g for k in ("日", "J-Pop", "JPOP", "City Pop", "Anime", "動漫")):
        return "ja"
    if any(k in g for k in ("韓", "K-Pop", "KPOP")):
        return "ko"
    if any(k in g for k in ("台語", "閩南", "台灣台語")):
        return "tw"
    if any(k in g for k in ("華", "國語", "粵", "中文", "C-Pop")):
        return "zh"
    if any(k in g for k in ("西洋", "英", "歐美", "Western", "Pop", "Rock")):
        return "en"
    return "en" if d is None else "other"


@router.get("/library")
def browse_library(
    lang: str = "all",
    q: str = "",
    limit: int = 150,
    offset: int = 0,
    session: Session = Depends(get_session),
):
    """Browse every ready (instant-play) song, groupable by language.

    Separate from the leaderboard (which ranks by plays) — this is the
    discovery/song-bank view. Language is exact for preinstalled songs
    (catalog tag persisted on the Song) and detected otherwise.
    """
    rows = (
        session.query(Song)
        .filter(Song.status == "ready")
        .order_by(Song.play_count.desc(), Song.processed_at.desc())
        .all()
    )
    counts = {k: 0 for k in _LANG_ORDER}
    tagged = []
    for s in rows:
        lg = _song_lang(s)
        counts[lg] = counts.get(lg, 0) + 1
        tagged.append((s, lg))

    if q:
        ql = q.lower()
        tagged = [t for t in tagged
                  if ql in (t[0].title or "").lower()
                  or ql in (t[0].artist or "").lower()]
    if lang != "all":
        tagged = [t for t in tagged if t[1] == lang]

    total = len(tagged)
    page = tagged[max(0, offset): max(0, offset) + max(1, min(limit, 300))]
    return {
        "total": total,
        "counts": counts,
        "songs": [
            {
                "id": s.id,
                "title": s.title,
                "artist": s.artist,
                "duration_sec": s.duration_sec,
                "thumbnail_url": s.thumbnail_url,
                "has_timing": s.has_timing,
                "play_count": s.play_count,
                "lang": lg,
            }
            for s, lg in page
        ],
    }


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

        def _thumb_url(entry: dict) -> Optional[str]:
            # extract_flat doesn't populate `thumbnail`; build the canonical
            # YouTube URL from the video ID instead.
            t = entry.get("thumbnail")
            if t:
                return t
            thumbs = entry.get("thumbnails")
            if isinstance(thumbs, list) and thumbs:
                # Last entry is usually highest-res
                best = thumbs[-1]
                if isinstance(best, dict) and best.get("url"):
                    return best["url"]
            vid = entry.get("id")
            if vid:
                return f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg"
            return None

        from ktv_pipeline.config import settings as _cfg
        lo, hi = _cfg.search_min_duration_sec, _cfg.search_max_duration_sec
        _NONMUSIC = re.compile(
            r"(合輯|合集|精選輯|完整專輯|全專|串[燒烧]|演唱會完整|完整版演唱會|"
            r"直播回放|直播檔|reaction|react |開箱|教學|教程|訪談|采访|採訪|"
            r"playlist|full album|mix \d|nonstop|live stream|podcast|"
            r"一小時|1\s*hour|2\s*hours)",
            re.I,
        )

        def _ok(e: dict) -> bool:
            d = e.get("duration")
            # No duration (livestream/premiere) → drop. Out of song range → drop.
            if not isinstance(d, (int, float)) or d < lo or d > hi:
                return False
            if _NONMUSIC.search(e.get("title") or ""):
                return False
            return True

        return [
            {
                "id": entry.get("id"),
                "title": entry.get("title"),
                "channel": entry.get("channel") or entry.get("uploader"),
                "duration_sec": entry.get("duration"),
                "thumbnail_url": _thumb_url(entry),
                "url": f"https://www.youtube.com/watch?v={entry.get('id')}",
                "cached": False,  # will be updated by frontend using local search
            }
            for entry in result.get("entries", [])
            if entry and entry.get("id") and _ok(entry)
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

    # A real user is adding a song → discard any pending autoplay pick so it
    # gets re-evaluated against the new last song.
    try:
        from api.ws import _drop_pending_autopicks
        _drop_pending_autopicks(room_id)
    except Exception:
        pass

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
        .filter(QueueItem.status.in_(QueueManager.ACTIVE_STATUSES))
        .first()
    )
    if existing_item:
        session.refresh(song)
        if existing_item.status == "pending" and song.status not in ("ready", "processing"):
            # Pending item with no active pipeline — (re)trigger it
            background_tasks.add_task(_run_pipeline_task, existing_item.id, room_id)
        else:
            background_tasks.add_task(_try_start_if_idle, room_id)
        background_tasks.add_task(_broadcast_queue_update, room_id)
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

    # Push the new queue to every connected client immediately (otherwise a
    # ready/cached add only shows after a manual refresh).
    background_tasks.add_task(_broadcast_queue_update, room_id)
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

# ── Lyrics source selection (Remote can switch + we remember the choice) ──────

from pydantic import BaseModel as _BaseModel


class LyricsSourceBody(_BaseModel):
    source: str  # youtube|amll_ttml|netease|qq|syncedlyrics|mojim|kkbox|genius|none


@router.get("/{song_id}/lyrics/source")
def get_lyrics_source(song_id: str, session: Session = Depends(get_session)):
    """Return current + preferred source and the list of PRE-FETCHED sources.

    If a ready song has never been prefetched (older songs), kick the
    background prefetch so the picker fills in shortly.
    """
    song = session.query(Song).filter_by(id=song_id).first()
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")
    meta = song.extra_metadata or {}
    avail = meta.get("available_lyrics") or {}
    if not avail and song.status == "ready" and not meta.get("_prefetch_started"):
        m = dict(meta)
        m["_prefetch_started"] = True
        song.extra_metadata = m
        session.commit()
        from ktv_pipeline.lyrics_prefetch import prefetch_all_lyrics
        asyncio.create_task(prefetch_all_lyrics(song_id))
    # avail = {"netease": {"timed": true}, "mojim": {"timed": false}, ...}
    return {
        "song_id": song_id,
        "current": song.lyrics_source,
        "preferred": meta.get("preferred_lyrics_source"),
        "has_timing": song.has_timing,
        "available": avail,        # only sources that actually have lyrics
        "prefetched": bool(avail),  # false → still fetching in background
    }


@router.post("/{song_id}/lyrics/source")
async def set_lyrics_source(
    song_id: str,
    body: LyricsSourceBody,
    session: Session = Depends(get_session),
):
    """Switch the active lyrics source — INSTANT.

    Sources are pre-fetched after processing into media/{id}/lyrics_{src}.ass.
    This just copies the chosen pre-cached file onto lyrics.ass (no network).
    Falls back to an on-demand fetch only if the cache is missing.
    source="none" disables timed subtitles.
    """
    from ktv_pipeline.config import settings as cfg

    song = session.query(Song).filter_by(id=song_id).first()
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")

    src = body.source
    media_dir = cfg.data_dir / "media" / song_id
    media_dir.mkdir(parents=True, exist_ok=True)
    ass_path = media_dir / "lyrics.ass"
    txt_path = media_dir / "lyrics.txt"

    meta = dict(song.extra_metadata or {})
    meta["preferred_lyrics_source"] = src

    if src == "none":
        if ass_path.exists():
            ass_path.unlink()
        song.has_timing = False
        song.lyrics_source = "none"
        song.extra_metadata = meta
        session.commit()
        await _broadcast_lyrics_changed(song_id)
        return {"ok": True, "source": "none", "has_timing": False}

    cached_ass = media_dir / f"lyrics_{src}.ass"
    cached_txt = media_dir / f"lyrics_{src}.txt"

    # ── Fast path: pre-cached file → instant swap ────────────────────────────
    if cached_ass.exists():
        ass_path.write_text(cached_ass.read_text(encoding="utf-8"), encoding="utf-8")
        if cached_txt.exists():
            txt_path.write_text(cached_txt.read_text(encoding="utf-8"), encoding="utf-8")
        song.has_timing = True
        song.lyrics_source = src
        song.extra_metadata = meta
        session.commit()
        await _broadcast_lyrics_changed(song_id)
        return {"ok": True, "source": src, "has_timing": True, "cached": True}

    if cached_txt.exists():
        # Plain-text-only source — no timed ASS
        txt_path.write_text(cached_txt.read_text(encoding="utf-8"), encoding="utf-8")
        if ass_path.exists():
            ass_path.unlink()
        song.has_timing = False
        song.lyrics_source = src
        song.extra_metadata = meta
        session.commit()
        await _broadcast_lyrics_changed(song_id)
        return {"ok": True, "source": src, "has_timing": False, "cached": True}

    # ── Slow path: not pre-fetched yet → fetch on demand once ────────────────
    from ktv_pipeline.pipeline.lyrics import (
        fetch_youtube_subtitles, fetch_amll, fetch_netease, fetch_qq,
        fetch_syncedlyrics, _fetch_mojim, _fetch_kkbox, _fetch_genius,
        clean_song_query,
    )
    from ktv_pipeline.pipeline.lrc_to_ass import convert_lrc_to_ass, ConversionError
    from ktv_pipeline.llm import clean_title_llm
    import re as _re

    raw_title = song.title or song_id
    llm = await clean_title_llm(raw_title, song.artist or "")
    if llm:
        title, artist = llm["title"], llm["artist"]
    else:
        title, artist = clean_song_query(raw_title, song.artist or "")

    try:
        _dur = song.duration_sec
        if src == "youtube":
            result = await fetch_youtube_subtitles(song_id, raw_title)
        elif src == "amll_ttml":
            result = await fetch_amll(title, artist, duration_sec=_dur)
        elif src == "netease":
            result = await fetch_netease(title, artist, duration_sec=_dur)
        elif src == "qq":
            result = await fetch_qq(title, artist, duration_sec=_dur)
        elif src == "syncedlyrics":
            result = await fetch_syncedlyrics(title, artist, duration_sec=_dur)
        elif src == "mojim":
            result = await _fetch_mojim(title, artist)
        elif src == "kkbox":
            result = await _fetch_kkbox(title, artist)
        elif src == "genius":
            result = await _fetch_genius(title, artist)
        else:
            raise HTTPException(status_code=400, detail=f"Unknown source: {src}")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"{src} fetch failed: {exc}")

    if result is None or not result.lrc.strip():
        raise HTTPException(status_code=404, detail=f"No lyrics from {src}")

    text_lines = [
        _re.sub(r"\[\d{1,2}:\d{2}(?:\.\d{1,3})?\]", "", ln).strip()
        for ln in result.lrc.splitlines()
    ]
    text_lines = [t for t in text_lines if t]
    if text_lines:
        joined = "\n".join(text_lines)
        txt_path.write_text(joined, encoding="utf-8")
        cached_txt.write_text(joined, encoding="utf-8")

    if result.lyrics_type == "synced":
        try:
            ass = convert_lrc_to_ass(
                result.lrc, total_duration_sec=song.duration_sec, song_id=song_id,
            )
            ass_path.write_text(ass, encoding="utf-8")
            cached_ass.write_text(ass, encoding="utf-8")
            song.has_timing = True
        except ConversionError:
            song.has_timing = False
    else:
        if ass_path.exists():
            ass_path.unlink()
        song.has_timing = False

    song.lyrics_source = result.source or src
    song.extra_metadata = meta
    session.commit()
    await _broadcast_lyrics_changed(song_id)
    return {"ok": True, "source": song.lyrics_source, "has_timing": song.has_timing}


_SRC_LABELS = {
    "youtube_subtitle": "YouTube 字幕", "bilibili_subtitle": "Bilibili 字幕",
    "amll_ttml": "AMLL 逐字", "amll_ttml_fallback_netease": "NetEase",
    "netease": "NetEase", "qq": "QQ 音樂", "syncedlyrics": "LRCLIB",
    "mojim": "魔鏡(純文字)", "kkbox": "KKBOX(純文字)", "genius": "Genius(純文字)",
    "none": "關閉字幕",
}


async def _broadcast_lyrics_changed(song_id: str) -> None:
    """Tell every room currently playing this song to reload subtitles, and
    toast which source is now active so the operator sees it worked."""
    from ktv_pipeline.ws_manager import manager
    from ktv_pipeline.models import QueueItem as _QI
    with get_db_session() as s:
        song = s.query(Song).filter_by(id=song_id).first()
        src = song.lyrics_source if song else None
        rooms = [
            r[0] for r in s.query(_QI.room_id)
            .filter_by(song_id=song_id, status="playing")
            .distinct()
            .all()
        ]
    label = _SRC_LABELS.get(src or "", src or "—")
    for room_id in rooms or []:
        await manager.broadcast_lyrics_updated(room_id, song_id)
        await manager.broadcast_activity(room_id, f"🎵 字幕來源：{label}", "字幕")


# ── Per-song problem report → playback strategy override ────────────────────
#
# A song whose separated audio glitches (爆音/破音), drifts out of sync, or
# has Demucs noise can be reported by anyone. Every issue type maps to the
# one robust remediation we have without re-processing: play the ORIGINAL
# video's embedded audio next time instead of the Demucs split tracks —
# perfect A/V sync, no separation artefacts. Vocal-mix control is then inert
# (there is no separate vocal track), which the UI makes explicit. Only an
# admin can revert (history is kept either way).

_ISSUE_LABELS = {
    "clipping": "爆音/破音",
    "av_desync": "音畫不同步",
    "separation_noise": "人聲分離雜訊",
    "subtitle_timing": "字幕對不上時間",
    "wrong_lyrics": "字幕不是這首歌",
    "other": "其他問題",
}
# Audio-class issues switch the song to the original embedded audio next
# play. A subtitle-timing report is NOT an audio problem — it's just logged
# / flagged so an admin can nudge the per-song delay (the right tool).
# A wrong_lyrics report immediately disables the wrong-song subtitles
# (same as switching the lyrics source to "none"); the cached alternate
# sources stay on disk so the picker can switch to the right one.
_AUDIO_ISSUES = {"clipping", "av_desync", "separation_noise", "other"}


def _playback_profile(song) -> dict:
    p = dict((song.extra_metadata or {}).get("playback") or {})
    p.setdefault("use_original_audio", False)
    p.setdefault("reports", [])
    return p


def _save_playback_profile(session, song, profile: dict) -> None:
    meta = dict(song.extra_metadata or {})
    meta["playback"] = profile
    song.extra_metadata = meta
    session.commit()


class ReportIssueBody(_BaseModel):
    issue: str  # clipping | av_desync | separation_noise | other


@router.get("/{song_id}/report")
def get_song_report(song_id: str, session: Session = Depends(get_session)):
    """Return the playback profile + report history for a song."""
    song = session.query(Song).filter_by(id=song_id).first()
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")
    p = _playback_profile(song)
    return {
        "song_id": song_id,
        "use_original_audio": bool(p["use_original_audio"]),
        "reports": p["reports"],
        "report_count": len(p["reports"]),
    }


@router.post("/{song_id}/report")
async def report_song_issue(
    song_id: str,
    body: ReportIssueBody,
    session: Session = Depends(get_session),
    payload: dict | None = Depends(get_optional_guest_dep),
):
    """Report a playback problem. Anyone may report. Switches the song to
    original-audio mode for its next play."""
    issue = body.issue if body.issue in _ISSUE_LABELS else "other"
    song = session.query(Song).filter_by(id=song_id).first()
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")

    guest_id = (payload or {}).get("sub")
    nickname = None
    if guest_id:
        g = session.query(Guest).filter_by(id=guest_id).first()
        nickname = g.nickname if g else None

    is_audio = issue in _AUDIO_ISSUES
    p = _playback_profile(song)
    if is_audio:
        p["use_original_audio"] = True
        p.pop("reverted_at", None)
    p["reports"] = (p["reports"] + [{
        "at": datetime.now(timezone.utc).isoformat(),
        "guest_id": guest_id,
        "nickname": nickname,
        "issue": issue,
    }])[-50:]  # cap history

    if issue == "wrong_lyrics":
        # The active subtitles belong to a DIFFERENT song — kill them now
        # rather than karaoke-ing the wrong words all night. Cached alternate
        # sources (lyrics_<src>.ass) are kept so the 歌詞來源 picker can swap
        # in the right one instantly.
        from ktv_pipeline.config import settings as _cfg
        ass_path = _cfg.data_dir / "media" / song_id / "lyrics.ass"
        try:
            if ass_path.exists():
                ass_path.unlink()
        except OSError:
            pass
        song.has_timing = False
        song.lyrics_source = "none"

    _save_playback_profile(session, song, p)

    from ktv_pipeline.models import ErrorLog
    session.add(ErrorLog(
        category="playback", severity="warning",
        message=f"Song reported ({_ISSUE_LABELS[issue]}): {song.title}",
        context={"song_id": song_id, "issue": issue,
                 "by": nickname or guest_id or "anon"},
    ))
    session.commit()

    # Tell the room (toast on Player, refresh report state on Remote).
    from ktv_pipeline.ws_manager import manager
    from ktv_pipeline.models import QueueItem as _QI
    rooms = [
        r[0] for r in session.query(_QI.room_id)
        .filter_by(song_id=song_id).filter(_QI.status.in_(("playing", "pending")))
        .distinct().all()
    ]
    if is_audio:
        tail = "下次將用原始音訊"
    elif issue == "wrong_lyrics":
        tail = "已關閉錯誤字幕，可在遙控器選正確歌詞來源"
    else:
        tail = "已記錄，請管理員微調字幕延遲"
    for room_id in set(rooms):
        await manager.broadcast_activity(
            room_id, f"回報了問題（{_ISSUE_LABELS[issue]}）— {tail}",
            nickname or "有人",
        )
        await manager.send_to_room(room_id, {
            "type": "song.profile_updated",
            "song_id": song_id,
            "use_original_audio": bool(p["use_original_audio"]),
            "has_timing": bool(song.has_timing),
            "lyrics_source": song.lyrics_source,
        })
        if issue == "wrong_lyrics":
            # Remount the Player's subtitle layer — lyrics.ass is gone, so
            # the wrong-song karaoke disappears mid-play.
            await manager.broadcast_lyrics_updated(room_id, song_id)
    return {
        "ok": True, "song_id": song_id,
        "use_original_audio": bool(p["use_original_audio"]),
        "has_timing": bool(song.has_timing),
        "issue": issue, "report_count": len(p["reports"]),
    }


@router.delete("/{song_id}/report")
async def revert_song_report(
    song_id: str,
    session: Session = Depends(get_session),
    payload: dict = Depends(get_current_guest),
):
    """Revert to separated-audio mode (admin only). Report history is kept."""
    if not payload.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin only")
    song = session.query(Song).filter_by(id=song_id).first()
    if not song:
        raise HTTPException(status_code=404, detail="Song not found")
    p = _playback_profile(song)
    p["use_original_audio"] = False
    p["reverted_at"] = datetime.now(timezone.utc).isoformat()
    _save_playback_profile(session, song, p)

    from ktv_pipeline.ws_manager import manager
    from ktv_pipeline.models import QueueItem as _QI
    rooms = [
        r[0] for r in session.query(_QI.room_id)
        .filter_by(song_id=song_id).filter(_QI.status.in_(("playing", "pending")))
        .distinct().all()
    ]
    for room_id in set(rooms):
        await manager.send_to_room(room_id, {
            "type": "song.profile_updated",
            "song_id": song_id,
            "use_original_audio": False,
        })
    return {"ok": True, "song_id": song_id, "use_original_audio": False}
