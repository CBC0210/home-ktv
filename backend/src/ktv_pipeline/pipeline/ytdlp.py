"""yt-dlp Python-API wrapper.

Uses yt_dlp.YoutubeDL (not subprocess).  Classifies errors as temp or perm,
retries temp errors with exponential back-off (1 s, 2 s, 4 s).
"""

import asyncio
import json
import logging
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yt_dlp
import yt_dlp.utils

from ..config import settings

log = logging.getLogger(__name__)

_JS_RUNTIME_ENV = {
    "deno": "KTV_YTDLP_DENO_PATH",
    "node": "KTV_YTDLP_NODE_PATH",
}


def _is_executable(path: Path) -> bool:
    return path.is_absolute() and path.is_file() and os.access(path, os.X_OK)


def _home_runtime_candidates(name: str) -> list[Path]:
    if name == "deno":
        return [Path.home() / ".deno/bin/deno"]
    nvm_root = Path.home() / ".nvm/versions/node"
    candidates = list(nvm_root.glob("*/bin/node"))
    return sorted(
        candidates,
        key=lambda path: tuple(int(part) for part in re.findall(r"\d+", path.parent.parent.name)),
        reverse=True,
    )


def _resolve_js_runtime(name: str, env_name: str) -> Path | None:
    override = os.environ.get(env_name)
    candidates = [Path(override).expanduser()] if override else []
    discovered = shutil.which(name)
    if discovered:
        candidates.append(Path(discovered))
    candidates.extend(_home_runtime_candidates(name))
    return next((path for path in candidates if _is_executable(path)), None)


def _bgutil_server_home() -> Path:
    override = os.environ.get("KTV_BGUTIL_SERVER_HOME")
    return Path(override).expanduser() if override else (
        Path.home() / ".local/share/home-ktv/bgutil-ytdlp-pot-provider/server"
    )


def _js_runtimes() -> dict[str, dict[str, str]]:
    """Return installed JS runtimes using absolute executable paths only."""
    runtimes: dict[str, dict[str, str]] = {}
    for name, env_name in _JS_RUNTIME_ENV.items():
        path = _resolve_js_runtime(name, env_name)
        if path:
            runtimes[name] = {"path": str(path)}
    if not runtimes:
        log.error(
            "No configured yt-dlp JS runtime found; set KTV_YTDLP_DENO_PATH or "
            "KTV_YTDLP_NODE_PATH to an absolute executable path"
        )
    return runtimes

# Messages that indicate the video cannot ever be downloaded (perm errors).
_PERM_SUBSTRINGS = (
    "video unavailable",
    "this video is not available",
    "private video",
    "this video has been removed",
    "has been removed",
    "age-restricted",
    "age restricted",
    "is not available in your country",
    "available in your country",
    "geo restricted",
    "geographic restriction",
    "copyright",
    "your account",
    "members only",
    "this video contains content",
)



# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class YtDlpError(Exception):
    """Base class for all download errors."""


class TempDownloadError(YtDlpError):
    """Transient error (network, rate-limit, timeout) — caller should retry."""


class PermDownloadError(YtDlpError):
    """Permanent error (unavailable, private, geo-blocked) — do not retry."""


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class DownloadResult:
    youtube_id: str
    title: str
    artist: Optional[str]
    duration_sec: Optional[int]
    thumbnail_url: Optional[str]
    video_path: Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _classify_ytdlp_error(exc: Exception) -> YtDlpError:
    msg = str(exc).lower()
    for sub in _PERM_SUBSTRINGS:
        if sub in msg:
            return PermDownloadError(str(exc))
    return TempDownloadError(str(exc))


def _extract_youtube_id(url: str) -> Optional[str]:
    # Source-agnostic: YouTube id or Bilibili BVID (used as cache dir name).
    from ktv_pipeline.video_source import extract_video_id
    return extract_video_id(url)


def _build_result(youtube_id: str, info: dict, video_path: Path) -> DownloadResult:
    return DownloadResult(
        youtube_id=youtube_id,
        title=info.get("title") or youtube_id,
        artist=info.get("uploader") or info.get("channel"),
        duration_sec=info.get("duration"),
        thumbnail_url=info.get("thumbnail"),
        video_path=video_path,
    )


def _safe_info_subset(info: dict) -> dict:
    """Extract serialisable fields we care about from yt-dlp info dict."""
    keys = ("id", "title", "uploader", "channel", "duration", "thumbnail", "webpage_url")
    return {k: info.get(k) for k in keys}


# ---------------------------------------------------------------------------
# Wrapper
# ---------------------------------------------------------------------------


class YtDlpWrapper:
    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        timeout_sec: int = 300,
        max_retries: int = 3,
        cookies_path: Optional[Path] = None,
    ):
        self.cache_dir = cache_dir or (settings.data_dir / "cache")
        self.timeout_sec = timeout_sec
        self.max_retries = max_retries
        self.cookies_path = cookies_path

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ydl_opts(self, output_template: str) -> dict:
        opts: dict = {
            # Cap at 1080p — KTV background never needs 4K, and 4K files
            # (200-400MB) overwhelm the Cloudflare Tunnel → playback lag.
            "format": (
                "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/"
                "best[height<=1080][ext=mp4]/best[height<=1080]/best"
            ),
            "noplaylist": True,
            "max_filesize": 500 * 1024 * 1024,
            "match_filter": yt_dlp.utils.match_filter_func("duration <= 1200 & !is_live"),
            "outtmpl": output_template,
            "merge_output_format": "mp4",
            "quiet": True,
            "no_warnings": False,
            "socket_timeout": 30,
            "retries": 0,          # we control retry ourselves
            "fragment_retries": 3,
            "http_chunk_size": 10 * 1024 * 1024,
            # Explicit paths make this work under systemd, whose PATH has no deno/node.
            "js_runtimes": _js_runtimes(),
            # YouTube now enforces a GVS Proof-of-Origin token for this client.
            # The bgutil yt-dlp plugin supplies it through the local provider service.
            "extractor_args": {
                "youtube": {"player_client": ["mweb"]},
                # Sequential pipeline admission makes the on-demand provider
                # safe here and avoids exposing or supervising an HTTP token service.
                "youtubepot-bgutilscript": {"server_home": [str(_bgutil_server_home())]},
            },
        }
        if self.cookies_path and self.cookies_path.exists():
            opts["cookiefile"] = str(self.cookies_path)
        return opts

    def _download_sync(self, url: str, output_template: str) -> dict:
        with yt_dlp.YoutubeDL(self._ydl_opts(output_template)) as ydl:
            return ydl.extract_info(url, download=True) or {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def download(self, url: str) -> DownloadResult:
        """Download a YouTube video.

        Returns DownloadResult on success.
        Raises PermDownloadError for videos that can never be downloaded.
        Raises TempDownloadError after all retries are exhausted.
        """
        youtube_id = _extract_youtube_id(url) or url
        song_dir = self.cache_dir / youtube_id
        song_dir.mkdir(parents=True, exist_ok=True)

        video_path = song_dir / "video.mp4"
        info_path = song_dir / "info.json"

        # Idempotent: already downloaded — load saved info
        if video_path.exists() and video_path.stat().st_size > 0 and info_path.exists():
            log.info("Cache hit for %s, skipping download", youtube_id)
            info = json.loads(info_path.read_text())
            return _build_result(youtube_id, info, video_path)

        output_template = str(song_dir / "video.%(ext)s")
        last_exc: Optional[Exception] = None

        for attempt in range(self.max_retries):
            try:
                log.info(
                    "Downloading %s (attempt %d/%d)", youtube_id, attempt + 1, self.max_retries
                )
                info = await asyncio.wait_for(
                    asyncio.to_thread(self._download_sync, url, output_template),
                    timeout=self.timeout_sec,
                )

                # Normalise output file name to video.mp4
                actual = _find_output(song_dir, exclude=video_path)
                if actual and actual != video_path:
                    actual.rename(video_path)

                info_path.write_text(json.dumps(_safe_info_subset(info)))
                log.info("Downloaded %s successfully", youtube_id)
                return _build_result(youtube_id, info, video_path)

            except yt_dlp.utils.DownloadError as exc:
                classified = _classify_ytdlp_error(exc)
                if isinstance(classified, PermDownloadError):
                    log.error("Permanent download error for %s: %s", youtube_id, exc)
                    raise classified from exc
                last_exc = classified
                log.warning(
                    "Temp download error for %s attempt %d/%d: %s",
                    youtube_id, attempt + 1, self.max_retries, exc,
                )

            except asyncio.TimeoutError:
                last_exc = TempDownloadError(
                    f"Download timed out after {self.timeout_sec}s"
                )
                log.warning("Timeout for %s attempt %d/%d", youtube_id, attempt + 1, self.max_retries)

            except Exception as exc:
                last_exc = TempDownloadError(str(exc))
                log.warning(
                    "Unexpected error for %s attempt %d/%d: %s",
                    youtube_id, attempt + 1, self.max_retries, exc,
                )

            if attempt < self.max_retries - 1:
                backoff = 2**attempt  # 1 s, 2 s, 4 s
                log.info("Retrying %s in %d s", youtube_id, backoff)
                await asyncio.sleep(backoff)

        raise last_exc or TempDownloadError(
            f"Download failed after {self.max_retries} attempts"
        )


def _find_output(song_dir: Path, exclude: Optional[Path] = None) -> Optional[Path]:
    for ext in ("mp4", "mkv", "webm"):
        p = song_dir / f"video.{ext}"
        if p.exists() and p != exclude:
            return p
    return None
