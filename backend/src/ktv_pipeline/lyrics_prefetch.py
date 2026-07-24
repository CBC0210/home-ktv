"""Pre-fetch every lyrics source for a song and cache each one.

Run once after a song is processed (background task). Writes:
  media/{id}/lyrics_{source}.ass   (timed sources)
  media/{id}/lyrics_{source}.txt   (every source — plain text)
and records the available set in Song.extra_metadata["available_lyrics"].

Switching sources from the Remote then becomes an instant local file copy
instead of a slow network round-trip.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from .config import settings
from .database import get_db_session
from .models import Song
from .pipeline.lyrics import (
    fetch_youtube_subtitles, fetch_amll, fetch_netease, fetch_qq,
    fetch_syncedlyrics, _fetch_mojim, _fetch_kkbox, _fetch_genius,
    clean_song_query,
)
from .pipeline.lrc_to_ass import convert_lrc_to_ass, ConversionError
from .llm import clean_title_llm

log = logging.getLogger(__name__)

# Order matters — first timed source becomes the default if none chosen yet.
_SOURCES = [
    ("youtube", None),         # special-cased (needs youtube_id + raw title)
    ("amll_ttml", fetch_amll),
    ("netease", fetch_netease),
    ("qq", fetch_qq),
    ("syncedlyrics", fetch_syncedlyrics),
    ("mojim", _fetch_mojim),
    ("kkbox", _fetch_kkbox),
    ("genius", _fetch_genius),
]


def _strip_ts(lrc: str) -> str:
    out = []
    for line in lrc.splitlines():
        s = re.sub(r"\[\d{1,2}:\d{2}(?:\.\d{1,3})?\]", "", line).strip()
        if s:
            out.append(s)
    return "\n".join(out)


async def prefetch_all_lyrics(song_id: str) -> dict:
    """Fetch + cache every source for *song_id*. Returns the availability map."""
    with get_db_session() as db:
        song = db.query(Song).filter_by(id=song_id).first()
        if not song:
            return {}
        raw_title = song.title or song_id
        raw_artist = song.artist or ""
        duration = song.duration_sec
        meta = dict(song.extra_metadata or {})

    # Best title/artist/genre: LLM (cached in meta) → regex fallback
    cleaned = meta.get("clean_query")
    if not cleaned:
        llm = await clean_title_llm(raw_title, raw_artist)
        if llm:
            cleaned = {
                "title": llm["title"], "artist": llm["artist"],
                "genre": llm.get("genre", ""), "via": "llm",
            }
        else:
            ct, ca = clean_song_query(raw_title, raw_artist)
            cleaned = {"title": ct, "artist": ca, "genre": "", "via": "regex"}
        meta["clean_query"] = cleaned
        if cleaned.get("genre"):
            meta["genre"] = cleaned["genre"]
    title, artist = cleaned["title"], cleaned["artist"]
    log.info("[%s] prefetch using title=%r artist=%r (%s)",
             song_id, title, artist, cleaned.get("via"))

    media_dir = settings.data_dir / "media" / song_id
    media_dir.mkdir(parents=True, exist_ok=True)
    available: dict = {}

    for name, fetcher in _SOURCES:
        try:
            if name == "youtube":
                result = await fetch_youtube_subtitles(song_id, raw_title)
            else:
                result = await fetcher(title, artist, duration_sec=duration)
        except Exception as exc:
            log.info("[%s] prefetch %s failed: %s", song_id, name, exc)
            continue
        if result is None or not result.lrc.strip():
            continue

        # Plain text always
        txt = _strip_ts(result.lrc)
        if txt:
            (media_dir / f"lyrics_{name}.txt").write_text(txt, encoding="utf-8")

        timed = False
        if result.lyrics_type == "synced":
            try:
                ass = convert_lrc_to_ass(
                    result.lrc, total_duration_sec=duration, song_id=song_id,
                )
                (media_dir / f"lyrics_{name}.ass").write_text(ass, encoding="utf-8")
                timed = True
            except ConversionError:
                timed = False
        available[name] = {"timed": timed}
        log.info("[%s] prefetched %s (timed=%s)", song_id, name, timed)

    # Persist availability + activate a default if nothing is set yet
    with get_db_session() as db:
        song = db.query(Song).filter_by(id=song_id).first()
        if not song:
            return available
        meta = dict(song.extra_metadata or {})
        meta["available_lyrics"] = available
        meta["clean_query"] = cleaned
        if cleaned.get("genre"):
            meta["genre"] = cleaned["genre"]
        song.extra_metadata = meta

        active = media_dir / "lyrics.ass"
        pref = meta.get("preferred_lyrics_source")
        # If the user already picked a source, honour it; else first timed one
        chosen = None
        if pref and pref in available and available[pref]["timed"]:
            chosen = pref
        elif not active.exists() or not song.has_timing:
            for name, info in available.items():
                if info["timed"]:
                    chosen = name
                    break
        if chosen:
            src_ass = media_dir / f"lyrics_{chosen}.ass"
            if src_ass.exists():
                active.write_text(src_ass.read_text(encoding="utf-8"), encoding="utf-8")
                song.has_timing = True
                song.lyrics_source = chosen
                log.info("[%s] activated lyrics source: %s", song_id, chosen)
        db.commit()

    return available
