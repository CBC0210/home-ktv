"""Verify that a song's selected playback mode has its required local assets."""
import json
import math
import subprocess
from functools import lru_cache
from pathlib import Path

from .config import settings


def _nonempty(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


@lru_cache(maxsize=256)
def _original_has_audio(path: str, size: int, mtime: int) -> bool:
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'a:0',
             '-show_entries', 'stream=codec_type:format=duration', '-of', 'json', path],
            capture_output=True, text=True, timeout=5,
        )
        data = json.loads(result.stdout)
        duration = float(data.get('format', {}).get('duration', 0))
        return result.returncode == 0 and bool(data.get('streams')) and math.isfinite(duration) and duration > 0
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False


def playback_assets_ready(song) -> bool:
    if song is None:
        return False
    video = next((settings.data_dir / directory / song.id / 'video.mp4'
                  for directory in ('media', 'cache')
                  if _nonempty(settings.data_dir / directory / song.id / 'video.mp4')), None)
    if video is None:
        return False
    if ((song.extra_metadata or {}).get('playback') or {}).get('use_original_audio'):
        stat = video.stat()
        return _original_has_audio(str(video), stat.st_size, stat.st_mtime_ns)
    audio = settings.data_dir / 'cache' / 'demucs' / song.id
    return all(any(_nonempty(audio / (stem + ext)) for ext in ('.opus', '.wav'))
               for stem in ('vocals', 'no_vocals'))
