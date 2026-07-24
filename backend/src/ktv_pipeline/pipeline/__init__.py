"""Pipeline workers: yt-dlp, Demucs, lyrics, WhisperX, ASS, HLS."""

from .ytdlp import YtDlpWrapper, DownloadResult, YtDlpError, TempDownloadError, PermDownloadError
from .demucs import DemucsWrapper, SeparationResult, DemucsError, TemporaryError, PermanentError
from .whisperx_align import (
    WhisperXWrapper,
    AlignmentResult,
    AlignmentError,
    TemporaryError,
    PermanentError,
)
from .lrc_to_ass import (
    LrcToAssConverter,
    LrcToAssResult,
    AssConfig,
    ConversionError,
    convert_lrc_to_ass,
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
    # LRC → ASS
    "LrcToAssConverter",
    "LrcToAssResult",
    "AssConfig",
    "ConversionError",
    "convert_lrc_to_ass",
]