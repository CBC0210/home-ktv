"""Romanisation of Japanese / Korean lyric lines.

Used by the ASS renderer to show a small Latin-script reading line under
the native current/next lines. Best-effort only: any failure (no target
script, library hiccup, empty result) returns ``None`` so the caller just
shows the original line — never a blank or an error.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Optional

# Script ranges
_HIRAGANA = (0x3040, 0x309F)
_KATAKANA = (0x30A0, 0x30FF)
_HANGUL = (0xAC00, 0xD7A3)
_HANGUL_JAMO = (0x1100, 0x11FF)

_kakasi = None  # lazily-built pykakasi converter (heavy-ish import)
_ko_translit = None


def _in(o: int, rng: tuple[int, int]) -> bool:
    return rng[0] <= o <= rng[1]


def detect_script(text: str) -> Optional[str]:
    """Return 'ja' if the line contains kana, 'ko' if it contains hangul.

    Kana / hangul presence is decisive; bare Han (kanji-only) is ambiguous
    between Chinese and Japanese, so it is intentionally *not* treated as
    Japanese here — the chosen fallback is to show the original only.
    """
    for ch in text:
        o = ord(ch)
        if _in(o, _HIRAGANA) or _in(o, _KATAKANA):
            return "ja"
        if _in(o, _HANGUL) or _in(o, _HANGUL_JAMO):
            return "ko"
    return None


def _romanize_ja(text: str) -> Optional[str]:
    global _kakasi
    if _kakasi is None:
        import pykakasi  # lazy — keeps cold-start light

        _kakasi = pykakasi.kakasi()
    parts = [item.get("hepburn", "") for item in _kakasi.convert(text)]
    out = " ".join(p for p in parts if p).strip()
    out = re.sub(r"\s{2,}", " ", out)
    return out or None


def _romanize_ko(text: str) -> Optional[str]:
    global _ko_translit
    if _ko_translit is None:
        from hangul_romanize import Transliter
        from hangul_romanize.rule import academic

        _ko_translit = Transliter(academic)
    out = (_ko_translit.translit(text) or "").strip()
    out = re.sub(r"\s{2,}", " ", out)
    return out or None


@lru_cache(maxsize=8192)
def romanize(text: str) -> Optional[str]:
    """Return a Latin-script reading of *text*, or None if not applicable.

    None when: no kana/hangul in the line, conversion fails, or the result
    is empty / identical to the input (nothing was actually transliterated).
    """
    text = (text or "").strip()
    if not text:
        return None
    script = detect_script(text)
    try:
        if script == "ja":
            r = _romanize_ja(text)
        elif script == "ko":
            r = _romanize_ko(text)
        else:
            return None
    except Exception:
        return None
    if not r or r.strip() == text.strip():
        return None
    return r
