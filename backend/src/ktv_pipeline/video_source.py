"""Video source / id / url helpers — YouTube and Bilibili.

`songs.id` (the cache + media directory name and DB PK) is the bare video id:
  - YouTube : 11 chars  [A-Za-z0-9_-]
  - Bilibili: "BV" + 10 [0-9A-Za-z]  (modern bvid, 12 chars), or
              "av" + digits         (legacy aid, normalised form)

All three shapes are disjoint and filesystem-safe, so a single id space is
unambiguous and nothing downstream — media paths, streaming URLs,
Demucs/WhisperX/HLS — needs to care about the source.
"""
from __future__ import annotations

import re
from typing import Optional

_YT_RE = re.compile(r"(?:v=|youtu\.be/|embed/|/v/|/shorts/)([A-Za-z0-9_-]{11})")
_BV_RE = re.compile(r"(BV[0-9A-Za-z]{10})")
_AV_RE = re.compile(r"(?:bilibili\.com/video/|/)?av(\d+)", re.I)


def extract_video_id(url_or_id: str) -> Optional[str]:
    """Bare video id from a URL or id (YouTube or Bilibili), else None."""
    s = (url_or_id or "").strip()
    # Bilibili bvid — distinctive, never a YouTube URL.
    m = _BV_RE.search(s)
    if m:
        return m.group(1)
    if re.fullmatch(r"BV[0-9A-Za-z]{10}", s):
        return s
    # Bilibili legacy aid: "av12345", a bilibili av URL, or bare digits
    # (yt-dlp bilisearch returns the numeric aid).
    if "bilibili.com" in s or re.match(r"(?i)av\d+$", s) or re.fullmatch(r"\d{2,}", s):
        m = _AV_RE.search(s)
        if m:
            return f"av{m.group(1)}"
        if re.fullmatch(r"\d{2,}", s):
            return f"av{s}"
    m = _YT_RE.search(s)
    if m:
        return m.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", s):
        return s
    return None


def video_source(song_id: str) -> str:
    """'bilibili' | 'youtube' inferred from the id shape."""
    if (len(song_id) == 12 and song_id.startswith("BV")) or re.match(r"(?i)av\d+$", song_id):
        return "bilibili"
    return "youtube"


def video_url(song_id: str) -> str:
    """Canonical watch URL for yt-dlp (download + subtitle extraction)."""
    if video_source(song_id) == "bilibili":
        return f"https://www.bilibili.com/video/{song_id}"
    return f"https://www.youtube.com/watch?v={song_id}"


def subtitle_source_name(song_id: str) -> str:
    """Lyrics-source label for the video's own embedded captions."""
    return "bilibili_subtitle" if video_source(song_id) == "bilibili" else "youtube_subtitle"
