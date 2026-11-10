"""Shared safety filter for song-search results.

The filter deliberately relies on unambiguous compilation signals.  A title
containing words such as ``完整版``、``精選`` or ``經典金曲`` alone can still be
a legitimate single-song MV, live clip, or remaster and must remain searchable.
"""
from __future__ import annotations

import re
from math import isfinite
from typing import Any, Mapping


# Terms that identify a non-song result regardless of its duration.  Keep this
# narrowly scoped: the duration bounds catch most long-form results, while
# these patterns catch short compilations that fit inside those bounds.
_NON_SONG_TITLE = re.compile(
    r"(?:"
    # Existing explicit compilation / non-music labels.
    r"合輯|合集|精選輯|精选辑|完整專輯|完整专辑|全專|全专|"
    r"串[燒烧]|演唱會完整|演唱会完整|完整版演唱會|完整版演唱会|"
    r"直播回放|直播檔|直播档|reaction|react\s|開箱|开箱|教學|教学|教程|"
    r"訪談|访谈|採訪|采访|playlist|full\s+album|mix\s+\d|nonstop|"
    r"live\s+stream|podcast|一小時|一小时|1\s*hour|2\s*hours|"
    # A count plus a song/compilation word is a clear multi-track signal.
    r"(?:[2-9]\d{0,2}|1\d{1,2}|一[十百千萬万]|[二三四五六七八九十百千兩两][一二三四五六七八九十百千萬万兩两]*)\s*首\s*"
    r"(?:歌(?:曲)?|金曲|精選|精选|經典|经典|串[燒烧])|"
    # These are explicit compilations without a track count.
    r"(?:歌曲|金曲|好歌)\s*(?:精選|精选)\s*(?:集|輯|辑)?|"
    r"(?:金曲|歌曲)\s*串[燒烧]|"
    r"(?:best|greatest|top)\s*(?:\d+\s*)?(?:songs?|hits?|collection|mix|medley)|"
    r"(?:\d+\s*)?(?:songs?|hits?)\s*(?:collection|mix|medley)|"
    r"(?:dj\s*)?medley|compilation\b"
    r")",
    re.IGNORECASE,
)


def is_song_search_result(
    entry: Mapping[str, Any],
    min_duration_sec: int | float,
    max_duration_sec: int | float,
) -> bool:
    """Return whether a local or YouTube search entry is suitable for KTV.

    ``entry`` needs only ``title`` and ``duration`` (or ``duration_sec`` for
    local ``Song`` records).  Missing duration is rejected because a search
    result without it is usually a livestream or an unavailable video.
    """
    if entry.get("is_live") is True or entry.get("live_status") in {
        "is_live", "is_upcoming"
    }:
        return False

    duration = entry.get("duration", entry.get("duration_sec"))
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        return False
    if not isfinite(duration):
        return False
    if duration < min_duration_sec or duration > max_duration_sec:
        return False
    return not _NON_SONG_TITLE.search(str(entry.get("title") or ""))
