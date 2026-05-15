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
from typing import Optional, Tuple

import httpx

from .config import settings

log = logging.getLogger(__name__)

_PROMPT = (
    "You clean YouTube music video titles into the real song name and "
    "performer. Rules:\n"
    "- Prefer the original-language name (keep Chinese in Chinese, do not "
    "translate or romanize).\n"
    "- Drop noise: Official/MV/Music Video/Lyric/Audio/HD/4K/動態歌詞/Live etc.\n"
    "- If you cannot tell the artist, use an empty string.\n"
    'Return ONLY a compact JSON object: {"title":"...","artist":"..."} '
    "with no other text.\n\nInput: "
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
) -> Optional[Tuple[str, str]]:
    """Ask MiniMax to extract (title, artist). Returns None on any failure."""
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
        if not title:
            return None
        log.info("LLM cleaned '%s' → title=%r artist=%r", raw_title, title, artist)
        return title, artist
    except Exception as exc:
        log.warning("MiniMax clean_title_llm failed: %s", exc)
        return None
