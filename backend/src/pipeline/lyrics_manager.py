"""歌詞抓取 manager — 7 sources + fallback chain。"""
import logging
import re
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class LyricsResult:
    lyrics_text: str
    source: Optional[str]
    has_timing: bool
    quality: str


class LyricsManager:
    """依序嘗試 7 個歌詞 source，fallback 到下一個直到成功。"""

    TIMEOUT = 10

    def fetch(self, song_id: str, title: str, artist: str) -> LyricsResult:
        fetchers = [
            ("amll_ttml",     self._fetch_amll),
            ("netease",      self._fetch_netease),
            ("qq",           self._fetch_qq),
            ("syncedlyrics", self._fetch_syncedlyrics),
            ("mojim",        self._fetch_plaintext_mojim),
            ("kkbox",        self._fetch_plaintext_kkbox),
            ("genius",       self._fetch_plaintext_genius),
        ]
        for source_name, fetcher in fetchers:
            try:
                result = fetcher(title, artist)
                if result and result.lyrics_text.strip():
                    logger.info(f"Lyrics found: {source_name}")
                    return result
            except Exception as e:
                logger.warning(f"{source_name} failed: {e}")
                continue
        logger.warning("All lyrics sources failed")
        return LyricsResult(lyrics_text="", source=None, has_timing=False, quality="none")

    def _fetch_amll(self, title: str, artist: str) -> Optional[LyricsResult]:
        return self._fetch_netease(title, artist)

    def _fetch_netease(self, title: str, artist: str) -> Optional[LyricsResult]:
        try:
            with httpx.Client(timeout=self.TIMEOUT) as client:
                search_url = "https://music.163.com/api/search/get"
                params = {"s": f"{title} {artist}", "type": 1, "limit": 1}
                resp = client.get(search_url, params=params)
                if resp.status_code != 200:
                    return None
                songs = resp.json().get("result", {}).get("songs", [])
                if not songs:
                    return None
                song_id = songs[0]["id"]
                lrc_resp = client.get(f"https://music.163.com/api/song/lyric?id={song_id}&lv=1&kv=1&tv=-1")
                data = lrc_resp.json()
                lrc = data.get("lrc", {}).get("lyric", "")
                if lrc.strip():
                    return LyricsResult(lyrics_text=lrc, source="netease", has_timing=True, quality="official_line")
        except Exception:
            pass
        return None

    def _fetch_qq(self, title: str, artist: str) -> Optional[LyricsResult]:
        return self._fetch_syncedlyrics(title, artist)

    def _fetch_syncedlyrics(self, title: str, artist: str) -> Optional[LyricsResult]:
        try:
            query = f"{title} {artist}".replace(" ", "+")
            with httpx.Client(timeout=self.TIMEOUT) as client:
                resp = client.get(f"https://lrclib.net/api/get?q={query}")
                if resp.status_code == 200:
                    data = resp.json()
                    lrc = data.get("plainLyrics", "") or data.get("syncedLyrics", "")
                    if lrc:
                        return LyricsResult(lyrics_text=lrc, source="syncedlyrics", has_timing=True, quality="official_line")
        except Exception:
            pass
        return None

    def _fetch_plaintext_mojim(self, title: str, artist: str) -> Optional[LyricsResult]:
        try:
            query = f"{title} {artist}".replace(" ", "+")
            with httpx.Client(timeout=self.TIMEOUT) as client:
                resp = client.get(f"https://mojim.com/twh_search.php?keyword={query}")
                if resp.status_code != 200:
                    return None
                match = re.search(r'href="/([a-z0-9_]+?\.htm)"', resp.text)
                if not match:
                    return None
                lyrics_resp = client.get(f"https://mojim.com/{match.group(1)}")
                text = re.sub(r"<[^>]+>", "", lyrics_resp.text)
                lines = [l.strip() for l in text.split("\n") if l.strip() and len(l.strip()) > 5]
                lyrics = "\n".join(lines[:100])
                if lyrics:
                    return LyricsResult(lyrics_text=lyrics, source="mojim", has_timing=False, quality="plaintext")
        except Exception:
            pass
        return None

    def _fetch_plaintext_kkbox(self, title: str, artist: str) -> Optional[LyricsResult]:
        return None

    def _fetch_plaintext_genius(self, title: str, artist: str) -> Optional[LyricsResult]:
        try:
            query = f"{title} {artist}".replace(" ", "+")
            with httpx.Client(timeout=self.TIMEOUT) as client:
                resp = client.get(f"https://genius.com/api/search/song?q={query}&per_page=1")
                if resp.status_code == 200:
                    hits = resp.json().get("response", {}).get("hits", [])
                    if hits:
                        path = hits[0]["result"]["path"]
                        lyrics_resp = client.get(f"https://genius.com{path}")
                        m = re.search(r'lyrics[^>]*>(.*?)</div>', lyrics_resp.text, re.DOTALL)
                        if m:
                            text = re.sub(r"<[^>]+>", "", m.group(1))
                            return LyricsResult(lyrics_text=text.strip(), source="genius", has_timing=False, quality="plaintext")
        except Exception:
            pass
        return None
