"""Reclaim disk space in cache/ without breaking playback.

cache/ mixes two kinds of files:

- Playback assets: cache/demucs/<id>/ (separated vocals + instrumental) and,
  when media/<id>/video.mp4 does not exist, cache/<id>/video.mp4. A `ready`
  song cannot play without them, so they are never removed here.
- Reclaimable files: download leftovers, original downloads that were
  transcoded into a separate media/<id>/video.mp4, and folders of songs no
  longer in the DB. An original that is hardlinked to its media copy frees no
  space, so it stays (it lets a reprocess skip the download).

Songs still being processed (anything other than ready / failed_perm) are not
touched at all, because the pipeline may be writing their files right now.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

SETTLED_STATUSES = frozenset({"ready", "failed_perm"})
LEFTOVER_SUFFIXES = (".part", ".ytdl", ".temp", ".tmp")
# Top-level cache/ entries that are not per-song download folders.
SPECIAL_DIRS = frozenset({"demucs", "whisperx"})


@dataclass
class ReclaimResult:
    files_removed: int = 0
    bytes_freed: int = 0

    def add_file(self, path: Path) -> None:
        try:
            st = path.stat()
            path.unlink()
        except OSError:
            return
        self.files_removed += 1
        # A hardlinked file frees nothing until its last link is gone.
        if st.st_nlink <= 1:
            self.bytes_freed += st.st_size

    def add_tree(self, path: Path) -> None:
        for f in sorted(path.rglob("*"), reverse=True):
            if f.is_file() or f.is_symlink():
                self.add_file(f)
        shutil.rmtree(path, ignore_errors=True)


def _is_leftover(path: Path) -> bool:
    return path.name.endswith(LEFTOVER_SUFFIXES)


def _nonempty(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size > 0
    except OSError:
        return False


def _separate_media_copy(media_root: Path, song_id: str, original: Path) -> bool:
    """True when media/ has its own (transcoded) video, not a link to original."""
    media_video = media_root / "media" / song_id / "video.mp4"
    if not _nonempty(media_video):
        return False
    try:
        return not media_video.samefile(original)
    except OSError:
        return False


def reclaim_cache(media_root: Path, song_status: Mapping[str, str]) -> ReclaimResult:
    """Delete reclaimable files under media_root/cache.

    song_status maps every song id in the DB to its status.
    """
    result = ReclaimResult()
    cache = media_root / "cache"
    if not cache.is_dir():
        return result

    for entry in cache.iterdir():
        if not entry.is_dir() or entry.is_symlink() or entry.name in SPECIAL_DIRS:
            continue
        song_id = entry.name
        status = song_status.get(song_id)
        if status is None:  # song deleted from the DB
            result.add_tree(entry)
            continue
        if status not in SETTLED_STATUSES:
            continue
        for f in entry.iterdir():
            if f.is_file() and _is_leftover(f):
                result.add_file(f)
        original = entry / "video.mp4"
        if _nonempty(original) and _separate_media_copy(media_root, song_id, original):
            result.add_file(original)

    demucs = cache / "demucs"
    if demucs.is_dir():
        for entry in demucs.iterdir():
            if entry.is_dir() and not entry.is_symlink() and entry.name not in song_status:
                result.add_tree(entry)

    return result
