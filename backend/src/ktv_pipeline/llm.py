"""MiniMax LLM helper — clean messy YouTube titles into {title, artist}.

Uses MiniMax's Anthropic-compatible endpoint. M2.x are reasoning models so
the response contains a `thinking` block followed by the answer `text` block;
we only parse the `text` block. Best-effort: any failure (rate limit, network,
bad JSON) returns None and the caller falls back to the regex cleaner.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

import httpx

from .config import settings

log = logging.getLogger(__name__)

_PROMPT = (
    "You clean YouTube music video titles into the real song name, "
    "performer, and a genre. Rules:\n"
    "- Prefer the original-language name (keep Chinese in Chinese, do not "
    "translate or romanize).\n"
    "- Drop noise: Official/MV/Music Video/Lyric/Audio/HD/4K/動態歌詞/Live etc.\n"
    "- If you cannot tell the artist, use an empty string.\n"
    "- genre: ONE short Traditional-Chinese style tag (e.g. 華語流行, 搖滾, "
    "獨立, 嘻哈, 抒情, R&B, 電子, 民謠, 韓流, 日系, 西洋流行); guess from the "
    "artist if needed; empty string if unsure.\n"
    'Return ONLY a compact JSON object: '
    '{"title":"...","artist":"...","genre":"..."} with no other text.\n\nInput: '
)


def _extract_text(content: list) -> str:
    """Return the concatenated `text` blocks (skip `thinking`)."""
    parts = []
    for blk in content or []:
        if isinstance(blk, dict) and blk.get("type") == "text":
            parts.append(blk.get("text", ""))
    return "".join(parts).strip()


async def clean_title_llm(
    raw_title: str, raw_artist: str = ""
) -> Optional[dict]:
    """Ask MiniMax to extract {title, artist, genre}. None on any failure."""
    key = settings.minimax_api_key
    if not key or not raw_title:
        return None

    payload = {
        # M2.x are reasoning models — the `thinking` block alone can run
        # 1-2k tokens, so budget generously or the answer gets truncated.
        "model": settings.minimax_model,
        "max_tokens": 4000,
        "temperature": 0.1,
        "messages": [
            {
                "role": "user",
                "content": _PROMPT + json.dumps(
                    {"title": raw_title, "artist": raw_artist},
                    ensure_ascii=False,
                ),
            }
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(45.0)) as client:
            resp = await client.post(
                settings.minimax_base_url,
                headers={"Content-Type": "application/json", "X-Api-Key": key},
                json=payload,
            )
        if resp.status_code != 200:
            log.warning("MiniMax HTTP %s: %s", resp.status_code, resp.text[:200])
            return None
        data = resp.json()
        if data.get("type") == "error":
            log.warning("MiniMax error: %s", str(data.get("error"))[:200])
            return None
        text = _extract_text(data.get("content", []))
        if not text:
            log.warning("MiniMax returned no text block (stop=%s)", data.get("stop_reason"))
            return None
        # The model may wrap JSON in prose/```json fences — pull the object out
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return None
        obj = json.loads(m.group(0))
        title = (obj.get("title") or "").strip()
        artist = (obj.get("artist") or "").strip()
        genre = (obj.get("genre") or "").strip()
        if not title:
            return None
        log.info("LLM cleaned '%s' → title=%r artist=%r genre=%r",
                 raw_title, title, artist, genre)
        return {"title": title, "artist": artist, "genre": genre}
    except Exception as exc:
        log.warning("MiniMax clean_title_llm failed: %s", exc)
        return None


_CLASSIFY_PROMPT = (
    "Each line below is a numbered video title. Decide which are NOT a "
    "music song / MV / live performance / cover — i.e. junk for a karaoke "
    "library: interviews, reactions, tutorials, vlogs, news, gameplay, "
    "trailers, podcasts, hour-long mixes / full-album / full-concert "
    "compilations, ASMR, talk shows. A normal single song (any language, "
    "official MV, lyric video, cover, live single) IS music — keep it.\n"
    "Return ONLY a compact JSON array of the numbers that are NOT music, "
    "e.g. [2,5]. If all are music return [].\n\n"
)


async def classify_nonmusic_llm(titles: list[str]) -> Optional[set[int]]:
    """Given titles, return the 0-based indices that are NOT music.

    Best-effort: None on any failure so the caller can skip (never delete
    on uncertainty). An empty set means "all music".
    """
    key = settings.minimax_api_key
    if not key or not titles:
        return None
    listing = "\n".join(f"{i}. {t}" for i, t in enumerate(titles))
    payload = {
        "model": settings.minimax_model,
        "max_tokens": 4000,
        "temperature": 0.0,
        "messages": [{"role": "user", "content": _CLASSIFY_PROMPT + listing}],
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            resp = await client.post(
                settings.minimax_base_url,
                headers={"Content-Type": "application/json", "X-Api-Key": key},
                json=payload,
            )
        if resp.status_code != 200:
            log.warning("MiniMax classify HTTP %s: %s", resp.status_code, resp.text[:200])
            return None
        data = resp.json()
        if data.get("type") == "error":
            log.warning("MiniMax classify error: %s", str(data.get("error"))[:200])
            return None
        text = _extract_text(data.get("content", []))
        m = re.search(r"\[[\d,\s]*\]", text)
        if not m:
            return None
        idxs = json.loads(m.group(0))
        return {int(i) for i in idxs if 0 <= int(i) < len(titles)}
    except Exception as exc:
        log.warning("MiniMax classify_nonmusic_llm failed: %s", exc)
        return None
