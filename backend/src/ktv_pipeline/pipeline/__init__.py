"""Pipeline workers: yt-dlp, Demucs, lyrics, WhisperX, ASS, HLS."""

from .ytdlp import YtDlpWrapper, DownloadResult, YtDlpError, TempDownloadError, PermDownloadError
from .demucs import DemucsWrapper, SeparationResult, DemucsError, TemporaryError, PermanentError
from .lyrics import (
    LyricsResult,
    LyricsError,
    TempLyricsError,
    PermLyricsError,
    fetch_lyrics,
    fetch_netease,
    fetch_amll,
    fetch_qq,
    fetch_syncedlyrics,
)

__all__ = [
    # yt-dlp
    "YtDlpWrapper",
    "DownloadResult",
    "YtDlpError",
    "TempDownloadError",
    "PermDownloadError",
    # Demucs
    "DemucsWrapper",
    "SeparationResult",
    "DemucsError",
    "TemporaryError",
    "PermanentError",
    # Lyrics
    "LyricsResult",
    "LyricsError",
    "TempLyricsError",
    "PermLyricsError",
    "fetch_lyrics",
    "fetch_netease",
    "fetch_amll",
    "fetch_qq",
    "fetch_syncedlyrics",
]