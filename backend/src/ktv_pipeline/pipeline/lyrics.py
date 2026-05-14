"""Lyrics fetching — ADR-005 fallback chain.

Phase 0 (YouTube native subtitles, highest quality):
  0. YouTube subtitles — extracted via yt_dlp from the video itself

Phase 1 (synced / timed lyrics):
  1. AMLL TTML DB   — word-level AMLL (uses NetEase song ID → AMLL lookup)
  2. NetEase        — line-level LRC from 163 API
  3. QQ Music       — QRC line-level via QQ API
  4. syncedlyrics   — LRCLIB / Musixmatch / Megalobiz

Phase 2 (plain text fallback):
  5. Mojim          — HTML scrape
  6. KKBOX          — HTML scrape
  7. Genius         — HTML scrape

Phase 3:
  → 完全失敗，回傳 has_timing=False source=None quality=none

Output dict format per ADR-005 §7.3:
  {
    "lyrics_type": "synced" | "plain",
    "lrc": str,          # raw LRC content (even plain text gets returned in lrc field as single lines)
    "source": str,       # source name
  }

Thread-safety: uses a module-level asyncio.Lock (separate from GPU lock).
HTTP: httpx async client with exponential back-off retry.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field
from typing import Optional

import httpx

from ..config import settings

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lock — serialize network I/O to avoid hammering lyric servers.
# ---------------------------------------------------------------------------
_http_lock: asyncio.Lock = asyncio.Lock()

# Exponential back-off base delays (seconds) — 1, 2, 4, 8 ...
_BACKOFF_BASE = 1
_MAX_RETRIES = 3
_DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)
_CONNECT_TIMEOUT = 5.0
_READ_TIMEOUT = 15.0


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class LyricsError(Exception):
    """Base class."""


class TempLyricsError(LyricsError):
    """Transient error (network, timeout, 5xx) — retry ok."""


class PermLyricsError(LyricsError):
    """Permanent error (not found, 404, parse failure) — skip this source."""


# ---------------------------------------------------------------------------
# Result dataclass — ADR-005 output format
# ---------------------------------------------------------------------------


@dataclass
class LyricsResult:
    """Output of the lyrics pipeline stage.

    Attributes
    ----------
    lyrics_type:
        "synced"  — time-stamped LRC
        "plain"   — plain text (no timing)
    lrc:
        Raw LRC content. For plain text, one line per lyric line.
    source:
        Which source provided the lyrics (e.g. "netease", "mojim").
        None if all sources failed.
    quality:
        One of:
          "official_word"  — AMLL word-level timing
          "official_line"  — line-level from official API
          "plaintext"      — scraped plain text
          "none"           — all sources failed
    """

    lyrics_type: str          # "synced" | "plain"
    lrc: str
    source: Optional[str]
    quality: str

    def to_dict(self) -> dict:
        return {
            "lyrics_type": self.lyrics_type,
            "lrc": self.lrc,
            "source": self.source,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _classify_http_error(status: int) -> PermLyricsError | TempLyricsError:
    """Map HTTP status to error tier."""
    if status in (404, 410, 403):
        return PermLyricsError(f"HTTP {status}")
    if 400 <= status < 500:
        return PermLyricsError(f"HTTP {status}")
    return TempLyricsError(f"HTTP {status}")


def _strip_html(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _has_timing_markers(lrc: str) -> bool:
    """Return True if the LRC string contains at least one [mm:ss.xx] tag."""
    return bool(re.search(r"\[\d{1,2}:\d{2}(?:\.\d{1,3})?\]", lrc))


# OpenCC simplified → traditional converter (cached singleton)
_s2t_converter = None


def _to_traditional(text: str) -> str:
    """Convert simplified Chinese to traditional. Idempotent for non-CJK text.

    Most mainland sources (NetEase, QQ) return simplified Chinese, but we
    want Traditional for the karaoke display. OpenCC's s2twp variant uses
    Taiwan-Mandarin idiom mapping (more natural than plain s2t).
    """
    global _s2t_converter
    if not text or not re.search(r"[一-鿿]", text):
        return text
    try:
        if _s2t_converter is None:
            import opencc
            _s2t_converter = opencc.OpenCC("s2twp")
        return _s2t_converter.convert(text)
    except Exception as exc:
        log.warning("OpenCC conversion failed: %s", exc)
        return text


def _build_result(
    lrc: str,
    source: str,
    quality: str,
) -> LyricsResult:
    """Normalise source output into a LyricsResult.

    Lyrics from mainland sources are converted to Traditional Chinese
    (Taiwan idioms) automatically. Non-CJK content passes through.
    """
    lyrics_type = "synced" if _has_timing_markers(lrc) else "plain"
    return LyricsResult(
        lyrics_type=lyrics_type,
        lrc=_to_traditional(lrc),
        source=source,
        quality=quality,
    )


async def _retryable_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: Optional[dict] = None,
    headers: Optional[dict] = None,
    timeout: httpx.Timeout,
) -> httpx.Response:
    """GET with exponential-back-off retry for temp errors."""
    last_exc: Optional[Exception] = None
    for attempt in range(_MAX_RETRIES):
        try:
            resp = await client.get(url, params=params, headers=headers, timeout=timeout)
            if resp.status_code < 500:
                return resp
            # Server-side error → treat as temp
            last_exc = TempLyricsError(f"Server error {resp.status_code} on {url}")
        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError) as exc:
            last_exc = TempLyricsError(str(exc))

        if attempt < _MAX_RETRIES - 1:
            backoff = _BACKOFF_BASE * (2**attempt)
            log.warning("Retry %d/%d after %ds for %s", attempt + 1, _MAX_RETRIES, backoff, url)
            await asyncio.sleep(backoff)

    raise last_exc or TempLyricsError(f"All {_MAX_RETRIES} attempts failed for {url}")


# ---------------------------------------------------------------------------
# Phase 1: Synced-lyrics sources
# ---------------------------------------------------------------------------


def _normalize(s: str) -> str:
    """Lowercase, strip non-alphanumeric/CJK chars."""
    if not s:
        return ""
    s = s.lower()
    # Keep CJK + alphanumerics, drop punctuation/whitespace
    return re.sub(r"[^\w一-鿿]", "", s)


def _match_score(query: str, candidate: str) -> float:
    """Rough 0-1 similarity score via normalized substring containment."""
    q = _normalize(query)
    c = _normalize(candidate)
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0
    if q in c or c in q:
        return min(len(q), len(c)) / max(len(q), len(c))
    # Token overlap (works for English; CJK has no spaces so falls through)
    qt = set(q)
    ct = set(c)
    if not qt or not ct:
        return 0.0
    return len(qt & ct) / len(qt | ct) * 0.5  # weak signal, cap at 0.5


def _netease_artist_names(song: dict) -> str:
    """Extract artist names from NetEase song dict — artists are in artists[]."""
    arts = song.get("artists") or song.get("ar") or []
    if isinstance(arts, list):
        return " ".join(a.get("name", "") for a in arts if isinstance(a, dict))
    return ""


async def _netease_search(client: httpx.AsyncClient, title: str, artist: str) -> Optional[dict]:
    """Search NetEase and return the best-matching song.

    Scores each candidate by title + artist similarity to the query and
    rejects matches below a confidence threshold — better no lyrics than
    wrong lyrics for a different song.
    """
    params = {"s": f"{title} {artist}".strip(), "type": 1, "limit": 8}
    try:
        resp = await _retryable_get(
            client,
            "https://music.163.com/api/search/get",
            params=params,
            timeout=_DEFAULT_TIMEOUT,
        )
    except LyricsError:
        return None

    if resp.status_code != 200:
        return None
    songs = resp.json().get("result", {}).get("songs", [])
    if not songs:
        return None

    best: Optional[dict] = None
    best_score = 0.0
    for s in songs:
        cand_title = s.get("name", "") or ""
        cand_artist = _netease_artist_names(s)
        title_score = _match_score(title, cand_title)
        artist_score = _match_score(artist, cand_artist) if artist else 0.5
        score = title_score * 0.7 + artist_score * 0.3
        if score > best_score:
            best_score = score
            best = s

    log.info(
        "NetEase match for '%s'/'%s' → %s (score=%.2f)",
        title, artist,
        (best.get("name") if best else None),
        best_score,
    )
    # Reject low-confidence matches — wrong lyrics are worse than no lyrics
    if best_score < 0.5:
        return None
    return best


async def _fetch_netease_lrc(client: httpx.AsyncClient, song_id: int) -> Optional[str]:
    """Fetch line-level LRC from NetEase given a numeric song ID."""
    try:
        resp = await _retryable_get(
            client,
            f"https://music.163.com/api/song/lyric?id={song_id}&lv=1&kv=1&tv=-1",
            timeout=_DEFAULT_TIMEOUT,
        )
    except LyricsError:
        return None

    if resp.status_code != 200:
        return None
    data = resp.json()
    lrc = data.get("lrc", {}).get("lyric", "")
    if not lrc or not lrc.strip():
        return None
    return lrc


async def fetch_netease(title: str, artist: str) -> Optional[LyricsResult]:
    """NetEase line-level LRC."""
    try:
        async with _http_lock:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                song = await _netease_search(client, title, artist)
                if not song:
                    return None
                lrc = await _fetch_netease_lrc(client, song["id"])
                if lrc:
                    return _build_result(lrc, source="netease", quality="official_line")
    except Exception as exc:
        log.warning("NetEase fetch failed: %s", exc)
    return None


async def _amll_ttml_lookup(netease_id: int, client: httpx.AsyncClient) -> Optional[str]:
    """Query AMLL TTML DB for word-level LRC given a NetEase numeric ID.

    Must be called with an existing client (already inside _http_lock).
    """
    url = f"https://api.utuwork.cn/lyric/{netease_id}"
    try:
        resp = await _retryable_get(client, url, timeout=_DEFAULT_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            lrc = data.get("lrc") or data.get("lyric") or data.get("txt") or ""
            if lrc:
                return lrc
    except LyricsError:
        pass
    except Exception as exc:
        log.debug("AMLL probe failed for %d: %s", netease_id, exc)
    return None


async def fetch_amll(title: str, artist: str) -> Optional[LyricsResult]:
    """AMLL TTML DB — word-level timing (best effort, falls back to NetEase ID lookup)."""
    try:
        async with _http_lock:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                song = await _netease_search(client, title, artist)
                if not song:
                    return None
                netease_id = song["id"]
                lrc = await _amll_ttml_lookup(netease_id, client)
                if lrc:
                    return _build_result(lrc, source="amll_ttml", quality="official_word")
                # Fall back to plain NetEase LRC if AMLL has no TTML
                netease_lrc = await _fetch_netease_lrc(client, netease_id)
                if netease_lrc:
                    return _build_result(netease_lrc, source="amll_ttml_fallback_netease", quality="official_line")
    except Exception as exc:
        log.warning("AMLL fetch failed: %s", exc)
    return None


async def fetch_qq(title: str, artist: str) -> Optional[LyricsResult]:
    """QQ Music line-level LRC via QRC endpoint."""
    try:
        async with _http_lock:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                # 1. Search QQ
                search_params = {"w": f"{title} {artist}", "format": "json", "p": 1, "n": 3}
                try:
                    resp = await _retryable_get(
                        client,
                        "https://c.y.qq.com/soso/fcgi-bin/client_search_cp",
                        params=search_params,
                        timeout=_DEFAULT_TIMEOUT,
                    )
                except LyricsError:
                    return None

                if resp.status_code != 200:
                    return None

                text = resp.text
                # QQ search returns a weird JSONP wrapper; extract JSON
                m = re.search(r"callback\((.*)\)", text, re.DOTALL)
                if m:
                    import json
                    try:
                        data = json.loads(m.group(1))
                    except json.JSONDecodeError:
                        data = {}
                else:
                    import json
                    try:
                        data = json.loads(text)
                    except json.JSONDecodeError:
                        data = {}

                songs = data.get("data", {}).get("song", {}).get("list", [])
                if not songs:
                    return None

                song_mid = songs[0].get("songmid")
                if not song_mid:
                    return None

                # 2. Fetch LRC by song mid
                lrc_resp = await _retryable_get(
                    client,
                    f"https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg?songmid={song_mid}&format=json&nobase64=1",
                    headers={"Referer": "https://y.qq.com"},
                    timeout=_DEFAULT_TIMEOUT,
                )

                if lrc_resp.status_code != 200:
                    return None

                import json
                lrc_data = lrc_resp.json()
                raw = lrc_data.get("lyric", "") or lrc_data.get("trans", "")
                if not raw:
                    return None

                lrc = raw
                return _build_result(lrc, source="qq", quality="official_line")
    except Exception as exc:
        log.warning("QQ lyrics fetch failed: %s", exc)
    return None


async def _lrclib_get(query: str) -> Optional[str]:
    """Query LRCLIB.net and return synced LRC or plain lyrics."""
    try:
        async with _http_lock:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                resp = await _retryable_get(
                    client,
                    f"https://lrclib.net/api/get?q={query}",
                    timeout=_DEFAULT_TIMEOUT,
                )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("syncedLyrics") or data.get("plainLyrics") or ""
    except LyricsError:
        pass
    return None


async def fetch_syncedlyrics(title: str, artist: str) -> Optional[LyricsResult]:
    """LRCLIB — covers Musixmatch / Megalobiz via lrclib.net aggregation."""
    query = f"{title} {artist}"
    try:
        lrc = await _lrclib_get(query)
        if lrc and _has_timing_markers(lrc):
            return _build_result(lrc, source="syncedlyrics", quality="official_line")
    except Exception as exc:
        log.warning("syncedlyrics fetch failed: %s", exc)
    return None


# ---------------------------------------------------------------------------
# Phase 2: Plain-text sources
# ---------------------------------------------------------------------------


def _parse_plaintext(html: str, min_len: int = 20) -> str:
    """Strip HTML tags and noise from a lyrics page to get plain text."""
    text = _strip_html(html)
    # Remove common noise lines
    lines = [
        l.strip()
        for l in text.split("\n")
        if l.strip()
        and len(l.strip()) >= min_len
        and "©" not in l
        and "offset" not in l.lower()
    ]
    return "\n".join(lines[:200])


async def _fetch_mojim(title: str, artist: str) -> Optional[LyricsResult]:
    """Mojim.com plain-text scrape."""
    try:
        query = f"{title} {artist}".replace(" ", "+")
        async with _http_lock:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                resp = await _retryable_get(
                    client,
                    f"https://mojim.com/twh_search.php?keyword={query}",
                    timeout=_DEFAULT_TIMEOUT,
                )
        if resp.status_code != 200:
            return None

        # Find first results link
        m = re.search(r'href="/([a-z0-9_]+?\.htm[l]?)"', resp.text)
        if not m:
            return None

        song_path = f"https://mojim.com/{m.group(1)}"
        async with _http_lock:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                lyrics_resp = await _retryable_get(
                    client, song_path,
                    timeout=_DEFAULT_TIMEOUT,
                )
        if lyrics_resp.status_code != 200:
            return None

        lyrics = _parse_plaintext(lyrics_resp.text)
        if not lyrics:
            return None
        return _build_result(lyrics, source="mojim", quality="plaintext")
    except Exception as exc:
        log.warning("Mojim scrape failed: %s", exc)
    return None


async def _fetch_kkbox(title: str, artist: str) -> Optional[LyricsResult]:
    """KKBOX plain-text scrape (no API, just HTML)."""
    try:
        query = f"{title} {artist}".replace(" ", "+")
        search_url = f"https://www.kkbox.com/tw/tc/search.php?word={query}"
        async with _http_lock:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                resp = await _retryable_get(
                    client, search_url,
                    timeout=_DEFAULT_TIMEOUT,
                )
        if resp.status_code != 200:
            return None

        # KKBOX embeds song IDs in data attrs; we try to find the first match
        song_m = re.search(r'data-id="(\d+)"', resp.text)
        if not song_m:
            return None

        song_id = song_m.group(1)
        lyrics_url = f"https://www.kkbox.com/tw/tc/song/{song_id}/lyrics"
        async with _http_lock:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                lyrics_resp = await _retryable_get(
                    client, lyrics_url,
                    timeout=_DEFAULT_TIMEOUT,
                )
        if lyrics_resp.status_code != 200:
            return None

        lyrics = _parse_plaintext(lyrics_resp.text)
        if not lyrics:
            return None
        return _build_result(lyrics, source="kkbox", quality="plaintext")
    except Exception as exc:
        log.warning("KKBOX scrape failed: %s", exc)
    return None


async def _fetch_genius(title: str, artist: str) -> Optional[LyricsResult]:
    """Genius plain-text scrape."""
    try:
        query = f"{title} {artist}".replace(" ", "+")
        search_url = f"https://genius.com/api/search/song?q={query}&per_page=1"
        async with _http_lock:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                resp = await _retryable_get(
                    client, search_url,
                    timeout=_DEFAULT_TIMEOUT,
                )
        if resp.status_code != 200:
            return None

        hits = resp.json().get("response", {}).get("hits", [])
        if not hits:
            return None

        path = hits[0]["result"]["path"]
        lyrics_url = f"https://genius.com{path}"

        async with _http_lock:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                lyrics_resp = await _retryable_get(
                    client, lyrics_url,
                    timeout=_DEFAULT_TIMEOUT,
                )
        if lyrics_resp.status_code != 200:
            return None

        # Genius lyrics are in a <div data-lyrics-container="true">
        containers = re.findall(
            r'<div[^>]+data-lyrics-container="true"[^>]*>(.*?)</div>',
            lyrics_resp.text,
            re.DOTALL,
        )
        if not containers:
            return None

        parts = [_strip_html(c) for c in containers]
        lyrics = "\n".join(p for p in parts if p.strip())
        if not lyrics:
            return None
        return _build_result(lyrics, source="genius", quality="plaintext")
    except Exception as exc:
        log.warning("Genius scrape failed: %s", exc)
    return None


# ---------------------------------------------------------------------------
# Phase 0: YouTube native subtitles
# ---------------------------------------------------------------------------

# Preferred subtitle language order (manual first, then auto-generated)
_YT_SUB_LANGS = ["zh", "zh-Hant", "zh-Hans", "zh-TW", "zh-CN", "zh-HK", "en"]


def _vtt_to_lrc(vtt_content: str) -> Optional[str]:
    """Convert WebVTT subtitle content to LRC format.

    Handles both manual (line-level) and auto-generated (word-level) VTT.
    Strips word-level <tag> annotations, keeping only the visible text.
    Deduplicates consecutive identical lines produced by YouTube's rolling captions.
    """
    lines = vtt_content.splitlines()
    cues: list[tuple[str, str]] = []  # (start_lrc_tag, text)

    i = 0
    # Skip WEBVTT header lines until first blank line separator
    while i < len(lines) and lines[i].strip():
        i += 1

    while i < len(lines):
        line = lines[i].strip()
        # Skip cue identifier lines (non-empty, no "-->")
        if line and "-->" not in line:
            i += 1
            continue
        if "-->" in line:
            # Parse start timestamp: HH:MM:SS.mmm or MM:SS.mmm
            time_part = line.split("-->")[0].strip()
            time_parts = time_part.split(":")
            try:
                if len(time_parts) == 3:
                    h, m, s = time_parts
                    total_sec = int(h) * 3600 + int(m) * 60 + float(s)
                else:
                    m, s = time_parts
                    total_sec = int(m) * 60 + float(s)
            except (ValueError, IndexError):
                i += 1
                continue

            minutes = int(total_sec // 60)
            seconds = total_sec % 60
            lrc_tag = f"[{minutes:02d}:{seconds:05.2f}]"

            # Collect cue text lines
            i += 1
            text_lines = []
            while i < len(lines) and lines[i].strip():
                text_lines.append(lines[i].strip())
                i += 1
            raw_text = " ".join(text_lines)
            # Strip all VTT inline tags: <00:00:01.000>, <c>, </c>, <b>, etc.
            clean = re.sub(r"<[^>]+>", "", raw_text).strip()
            if clean:
                cues.append((lrc_tag, clean))
        else:
            i += 1

    if not cues:
        return None

    # Deduplicate rolling-caption duplicates: YouTube repeats the same text
    # across multiple cues as words are appended.  Keep only the last cue
    # in each run of identical text to avoid duplicate LRC lines.
    deduped: list[tuple[str, str]] = []
    for tag, text in cues:
        if deduped and deduped[-1][1] == text:
            deduped[-1] = (deduped[-1][0], text)  # keep first tag, skip duplicate
        else:
            deduped.append((tag, text))

    return "\n".join(f"{tag}{text}" for tag, text in deduped)


def _pick_best_subtitle(subs: dict, auto_subs: dict) -> Optional[tuple[str, bool]]:
    """Return (lang_key, is_auto) for the best available subtitle track.

    Prefers manual subtitles over auto-generated, and Chinese over English.
    Returns None if no subtitles are available.
    """
    for lang in _YT_SUB_LANGS:
        if lang in subs:
            return (lang, False)
    for lang in _YT_SUB_LANGS:
        if lang in auto_subs:
            return (lang, True)
    # Fallback: first available manual, then first auto
    if subs:
        return (next(iter(subs)), False)
    if auto_subs:
        return (next(iter(auto_subs)), True)
    return None


def _download_youtube_subs_sync(youtube_id: str, tmpdir: str) -> Optional[str]:
    """Synchronous yt_dlp subtitle download.  Run in a thread via asyncio.to_thread."""
    try:
        import yt_dlp  # type: ignore
    except ImportError:
        log.warning("yt_dlp not installed — skipping YouTube subtitle extraction")
        return None

    url = f"https://www.youtube.com/watch?v={youtube_id}"
    ydl_opts = {
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": _YT_SUB_LANGS,
        "subtitlesformat": "vtt",
        "outtmpl": os.path.join(tmpdir, "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 15,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            subs = info.get("subtitles", {}) if info else {}
            auto_subs = info.get("automatic_captions", {}) if info else {}
            pick = _pick_best_subtitle(subs, auto_subs)
            if not pick:
                return None
            lang, is_auto = pick
            # Now download just the chosen subtitle track
            ydl_opts2 = dict(ydl_opts)
            ydl_opts2["subtitleslangs"] = [lang]
            ydl_opts2["writeautomaticsub"] = is_auto
            ydl_opts2["writesubtitles"] = not is_auto
        with yt_dlp.YoutubeDL(ydl_opts2) as ydl2:
            ydl2.download([url])
    except Exception as exc:
        log.warning("yt_dlp subtitle download failed for %s: %s", youtube_id, exc)
        return None

    # Find the downloaded .vtt file
    for fname in os.listdir(tmpdir):
        if fname.endswith(".vtt"):
            try:
                return open(os.path.join(tmpdir, fname), encoding="utf-8").read()
            except OSError:
                return None
    return None


async def fetch_youtube_subtitles(youtube_id: str) -> Optional[LyricsResult]:
    """Phase 0: extract subtitles directly from the YouTube video.

    Uses yt_dlp in a thread pool (sync) so it doesn't block the event loop.
    Returns None if no subtitles are available or extraction fails.
    """
    log.info("Trying YouTube subtitles for video %s", youtube_id)
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            vtt_content = await asyncio.to_thread(
                _download_youtube_subs_sync, youtube_id, tmpdir
            )
            if not vtt_content:
                return None
            lrc = _vtt_to_lrc(vtt_content)
            if lrc and _has_timing_markers(lrc):
                log.info("YouTube subtitles found for %s", youtube_id)
                return _build_result(lrc, source="youtube_subtitle", quality="official_line")
    except Exception as exc:
        log.warning("YouTube subtitle extraction failed for %s: %s", youtube_id, exc)
    return None


# ---------------------------------------------------------------------------
# Manager — orchestrates the fallback chain
# ---------------------------------------------------------------------------

# Phase 1 ordered sources
_SYNCED_SOURCES = [
    ("amll_ttml",     fetch_amll),
    ("netease",      fetch_netease),
    ("qq",           fetch_qq),
    ("syncedlyrics", fetch_syncedlyrics),
]

# Phase 2 ordered sources
_PLAINTEXT_SOURCES = [
    ("mojim",  _fetch_mojim),
    ("kkbox",  _fetch_kkbox),
    ("genius", _fetch_genius),
]


async def fetch_lyrics(
    title: str,
    artist: str,
    youtube_id: Optional[str] = None,
) -> LyricsResult:
    """Main entry point — try all sources in ADR-005 order.

    Parameters
    ----------
    title:
        Song title from video metadata.
    artist:
        Artist name (may be empty).
    youtube_id:
        YouTube video ID.  When provided, YouTube's own subtitles are tried
        first (Phase 0) before any external lyric API.

    Returns ``LyricsResult`` with:
      - ``lyrics_type``: "synced" | "plain"
      - ``lrc``: raw content
      - ``source``: provider name or None
      - ``quality``: "official_word" | "official_line" | "plaintext" | "none"
    """
    log.info("Fetching lyrics for '%s' by '%s'", title, artist)

    # Phase 0: YouTube native subtitles (highest priority)
    if youtube_id:
        try:
            result = await fetch_youtube_subtitles(youtube_id)
            if result is not None and result.lrc.strip():
                log.info("Lyrics found via youtube_subtitle")
                return result
        except Exception as exc:
            log.warning("youtube_subtitle unexpected error, trying next source: %s", exc)

    # Phase 1: synced / timed lyrics
    for source_name, fetcher in _SYNCED_SOURCES:
        try:
            result = await fetcher(title, artist)
            if result is not None and result.lrc.strip():
                log.info("Lyrics found via %s", source_name)
                return result
        except TempLyricsError as exc:
            log.warning("%s temp error, trying next source: %s", source_name, exc)
        except PermLyricsError as exc:
            log.warning("%s perm error, trying next source: %s", source_name, exc)
        except Exception as exc:
            log.warning("%s unexpected error, trying next source: %s", source_name, exc)

    # Phase 2: plain text fallback
    for source_name, fetcher in _PLAINTEXT_SOURCES:
        try:
            result = await fetcher(title, artist)
            if result is not None and result.lrc.strip():
                log.info("Plain-text lyrics found via %s", source_name)
                return result
        except TempLyricsError as exc:
            log.warning("%s temp error, trying next source: %s", source_name, exc)
        except PermLyricsError as exc:
            log.warning("%s perm error, trying next source: %s", source_name, exc)
        except Exception as exc:
            log.warning("%s unexpected error, trying next source: %s", source_name, exc)

    # Phase 3: complete failure
    log.warning("All lyrics sources failed for '%s' by '%s'", title, artist)
    return LyricsResult(
        lyrics_type="plain",
        lrc="",
        source=None,
        quality="none",
    )