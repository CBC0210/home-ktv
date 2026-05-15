"""Pipeline orchestrator — coordinates all stages for a single song.

State machine (CLAUDE.md §21.4):
  queued → pending → downloading → separating → fetching_lyrics
    → aligning → packaging → ready → playing → done
  failed_temp (retry) | failed_perm (stuck, user decides) | interrupted | stale

Each stage updates DB heartbeat every 30 s.
Total song timeout: settings.song_total_timeout_sec (default 900 s = 15 min).
"""

from __future__ import annotations

import asyncio
import logging
import signal
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple, Awaitable

from .config import settings
from .database import get_db_session, init_db
from .models import Song, QueueItem

from .pipeline.ytdlp import (
    YtDlpWrapper,
    DownloadResult,
    PermDownloadError as YtPermError,
    TempDownloadError as YtTempError,
)
from .pipeline.demucs import (
    DemucsWrapper,
    SeparationResult,
    PermanentError as DemucsPermError,
    TemporaryError as DemucsTempError,
)
from .pipeline.lyrics import fetch_lyrics, TempLyricsError, PermLyricsError, LyricsResult
from .pipeline.whisperx_align import (
    WhisperXWrapper,
    AlignmentResult,
    PermanentError as AlignPermError,
    TemporaryError as AlignTempError,
)
from .pipeline.lrc_to_ass import LrcToAssConverter, ConversionError

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Inter-stage VRAM flush
# ---------------------------------------------------------------------------


def _inter_stage_vram_flush() -> None:
    """Force Python GC and CUDA allocator release between heavy GPU stages.

    Called via asyncio.to_thread() so it runs in a worker thread, matching
    the thread context where PyTorch allocated its objects.  This gives the
    CUDA allocator the best chance to actually free blocks before the next
    model loads.
    """
    import gc

    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            log.debug(
                "Inter-stage VRAM flush: free=%dMB reserved=%dMB",
                torch.cuda.mem_get_info()[0] // 1024 // 1024,
                torch.cuda.memory_reserved() // 1024 // 1024,
            )
    except Exception:
        pass  # flush is best-effort; never block the pipeline


# ---------------------------------------------------------------------------
# State machine
# ---------------------------------------------------------------------------


class SongState(str, Enum):
    QUEUED = "queued"
    PENDING = "pending"
    DOWNLOADING = "downloading"
    SEPARATING = "separating"
    FETCHING_LYRICS = "fetching_lyrics"
    ALIGNING = "aligning"
    PACKAGING = "packaging"
    READY = "ready"
    PLAYING = "playing"
    DONE = "done"
    FAILED_TEMP = "failed_temp"
    FAILED_PERM = "failed_perm"
    INTERRUPTED = "interrupted"
    STALE = "stale"


@dataclass
class PipelineConfig:
    """Tunable pipeline parameters."""
    max_retries: int = 3
    heartbeat_interval_sec: int = 30
    total_timeout_sec: int = field(default_factory=lambda: settings.song_total_timeout_sec)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PipelineError(Exception):
    """Base class."""


class TotalTimeoutError(PipelineError):
    """15-minute hard limit exceeded."""


class FailedPermError(PipelineError):
    """Permanent failure — skip without retry."""


# ---------------------------------------------------------------------------
# Heartbeat helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _update_queue_heartbeat(queue_item_id: int, state: str) -> None:
    """Update DB row in a new session (called from heartbeat task)."""
    try:
        with get_db_session() as db:
            item = db.query(QueueItem).filter(QueueItem.id == queue_item_id).first()
            if item:
                item.status = state
                item.last_heartbeat = _utcnow()
    except Exception:
        pass  # heartbeat must never raise


# ---------------------------------------------------------------------------
# PipelineOrchestrator
# ---------------------------------------------------------------------------


class PipelineOrchestrator:
    """End-to-end pipeline for one song.

    Usage (CLI mode)::

        orchestrator = PipelineOrchestrator()
        result = await orchestrator.run(song_id="dQw4w9WgXcQ")
        print(result)

    The orchestrator:
      1. Downloads the YouTube video via yt-dlp
      2. Separates vocals/instrumental via Demucs (GPU-serialised)
      3. Fetches + aligns lyrics via WhisperX (GPU-serialised)
      4. Converts LRC → ASS
      5. Writes results to the Song DB table
    """

    def __init__(
        self,
        config: Optional[PipelineConfig] = None,
        ytdlp: Optional[YtDlpWrapper] = None,
        demucs: Optional[DemucsWrapper] = None,
        whisperx: Optional[WhisperXWrapper] = None,
        lrc_converter: Optional[LrcToAssConverter] = None,
    ):
        self.config = config or PipelineConfig()
        self._ytdlp = ytdlp or YtDlpWrapper()
        self._demucs = demucs or DemucsWrapper()
        self._whisperx = whisperx or WhisperXWrapper()
        self._lrc_converter = lrc_converter or LrcToAssConverter()
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._cancel = asyncio.Event()
        self._started_at: Optional[datetime] = None
        # Set in run_from_queue() so _update_state can broadcast to the room
        self._queue_item_id: Optional[int] = None
        self._room_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(self, song_id: str) -> dict:
        """Run the full pipeline for *song_id*.

        Returns
        -------
        dict
            ``{"ok": True, "files": {...}}`` on success.
            ``{"ok": False, "error": "...", "perm": bool}`` on failure.

        Raises
        ------
        TotalTimeoutError
            When total elapsed exceeds ``total_timeout_sec``.
        """
        self._started_at = _utcnow()
        self._cancel.clear()

        # Heartbeat task — updates DB every 30 s
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(song_id)
        )

        try:
            result = await asyncio.wait_for(
                self._run_pipeline(song_id),
                timeout=self.config.total_timeout_sec,
            )
            await self._mark_ready(song_id)
            return result
        except asyncio.TimeoutError:
            log.error("[%s] Total timeout (%ds) exceeded", song_id, self.config.total_timeout_sec)
            await self._mark_failed_perm(song_id, "total_timeout")
            return {"ok": False, "error": "total_timeout", "perm": True}
        except BaseException as exc:
            # Cancelled / SIGTERM — mark interrupted
            if not self._cancel.is_set():
                log.warning("[%s] Pipeline exception: %s", song_id, exc)
            raise
        finally:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

    async def run_from_queue(self, queue_item_id: int) -> dict:
        """Process a song referenced by a queue item.

        Used when the orchestrator is called by the FastAPI backend.
        """
        with get_db_session() as db:
            item = db.query(QueueItem).filter(QueueItem.id == queue_item_id).first()
            if not item:
                return {"ok": False, "error": "queue_item_not_found", "perm": True}
            song_id = item.song_id
            self._queue_item_id = queue_item_id
            self._room_id = item.room_id

        # Update queue status → processing
        with get_db_session() as db:
            item = db.query(QueueItem).filter(QueueItem.id == queue_item_id).first()
            if item:
                item.status = "processing"
                item.last_heartbeat = _utcnow()

        result = await self.run(song_id)

        # Update queue item status
        with get_db_session() as db:
            item = db.query(QueueItem).filter(QueueItem.id == queue_item_id).first()
            if item:
                item.status = "ready" if result.get("ok") else "failed_perm"

        return result

    # ------------------------------------------------------------------
    # Internal pipeline steps
    # ------------------------------------------------------------------

    async def _run_pipeline(self, song_id: str) -> dict:
        """Run all stages in order; classify errors as temp or perm."""
        log.info("[%s] Pipeline starting", song_id)

        # ── Stage 1: Download ──────────────────────────────────────────
        try:
            dl_result = await self._download(song_id)
        except FailedPermError as exc:
            return {"ok": False, "error": str(exc), "perm": True}
        except TotalTimeoutError:
            raise
        except Exception as exc:
            # Unexpected — treat as temp, will retry
            log.warning("[%s] Download unexpected error: %s", song_id, exc)
            return {"ok": False, "error": str(exc), "perm": False}

        # ── Stage 2: Separate vocals ────────────────────────────────────
        sep_result: Optional[SeparationResult] = None
        try:
            sep_result = await self._separate(song_id, dl_result)
        except FailedPermError as exc:
            return {"ok": False, "error": str(exc), "perm": True}
        except TotalTimeoutError:
            raise

        # Flush any remaining VRAM between Demucs and WhisperX.
        # Demucs deletes its own tensors inside _run_demucs_sync, but the
        # asyncio.to_thread wrapper may keep the thread frame alive briefly.
        # Calling gc + empty_cache here in the event-loop thread ensures the
        # VRAM is freed before WhisperX tries to load its model.
        await asyncio.to_thread(_inter_stage_vram_flush)

        # ── Stage 3: Fetch + align lyrics ───────────────────────────────
        lyrics_result: Optional[LyricsResult] = None
        aligned_lrc: Optional[str] = None
        try:
            lyrics_result, aligned_lrc = await self._fetch_and_align(
                song_id, dl_result, sep_result
            )
        except FailedPermError as exc:
            return {"ok": False, "error": str(exc), "perm": True}
        except TotalTimeoutError:
            raise

        # ── Stage 4: Package ───────────────────────────────────────────
        try:
            files = await self._package(
                song_id, dl_result, sep_result, lyrics_result, aligned_lrc
            )
        except FailedPermError as exc:
            return {"ok": False, "error": str(exc), "perm": True}
        except TotalTimeoutError:
            raise

        log.info("[%s] Pipeline complete", song_id)
        return {"ok": True, "files": files}

    async def _download(self, song_id: str) -> DownloadResult:
        """Stage 1: yt-dlp download.

        Idempotent: returns cached result if video already downloaded.
        Caches to self._ytdlp.cache_dir (settings.data_dir / "cache").
        """
        log.info("[%s] Stage: download", song_id)
        await self._update_state(song_id, SongState.DOWNLOADING)

        cache_dir = self._ytdlp.cache_dir
        video_path = cache_dir / song_id / "video.mp4"
        info_path = cache_dir / song_id / "info.json"

        # Idempotent cache check
        if video_path.exists() and video_path.stat().st_size > 0 and info_path.exists():
            log.info("[%s] Download cache hit, skipping yt-dlp", song_id)
            import json
            info = json.loads(info_path.read_text())
            from .pipeline.ytdlp import _build_result
            return _build_result(song_id, info, video_path)

        # Run download (use self._ytdlp so cache_dir is consistent)
        url = f"https://www.youtube.com/watch?v={song_id}"
        for attempt in range(self.config.max_retries):
            try:
                result = await self._ytdlp.download(url)
                return result
            except YtTempError as exc:
                if attempt < self.config.max_retries - 1:
                    delay = (5, 30, 120)[attempt] if attempt < 3 else 120
                    log.warning("[%s] Download temp error, retrying in %ds: %s", song_id, delay, exc)
                    await asyncio.sleep(delay)
                else:
                    raise FailedPermError(f"download failed after {self.config.max_retries} attempts: {exc}")
            except YtPermError as exc:
                raise FailedPermError(f"download_perm: {exc}")

    async def _separate(self, song_id: str, dl_result: DownloadResult) -> SeparationResult:
        """Stage 2: Demucs vocal separation (GPU-serialised)."""
        log.info("[%s] Stage: separate", song_id)
        await self._update_state(song_id, SongState.SEPARATING)

        # Check cache — Demucs outputs go to self._demucs.cache_dir
        out_dir = self._demucs.cache_dir / song_id
        vocal_path = out_dir / "vocals.wav"
        inst_path = out_dir / "no_vocals.wav"
        if vocal_path.exists() and vocal_path.stat().st_size > 0 and inst_path.exists():
            log.info("[%s] Separation cache hit, skipping Demucs", song_id)
            from .pipeline.demucs import SeparationResult as SepRes
            return SepRes(song_id=song_id, vocal_path=vocal_path, instrumental_path=inst_path)

        for attempt in range(self.config.max_retries):
            try:
                return await self._demucs.separate(song_id, dl_result.video_path)
            except DemucsTempError as exc:
                if attempt < self.config.max_retries - 1:
                    delay = (5, 30, 120)[attempt] if attempt < 3 else 120
                    log.warning("[%s] Demucs temp error, retrying in %ds: %s", song_id, delay, exc)
                    await asyncio.sleep(delay)
                else:
                    raise FailedPermError(f"demucs failed after {self.config.max_retries} attempts: {exc}")
            except DemucsPermError as exc:
                raise FailedPermError(f"demucs_perm: {exc}")

    async def _fetch_and_align(
        self, song_id: str, dl_result: DownloadResult, sep_result: Optional[SeparationResult]
    ) -> Tuple[LyricsResult, Optional[str]]:
        """Stage 3: Fetch lyrics + WhisperX forced alignment (GPU-serialised)."""
        log.info("[%s] Stage: fetch_lyrics", song_id)
        await self._update_state(song_id, SongState.FETCHING_LYRICS)

        lyrics_result = await fetch_lyrics(dl_result.title, dl_result.artist or "", youtube_id=song_id)

        aligned_lrc: Optional[str] = None
        if lyrics_result.lyrics_type == "synced" and lyrics_result.lrc:
            # Try word-level alignment via WhisperX
            log.info("[%s] Stage: align", song_id)
            await self._update_state(song_id, SongState.ALIGNING)

            # Check cache
            ass_cache = settings.data_dir / "media" / song_id / "lyrics.ass"
            if ass_cache.exists() and ass_cache.stat().st_size > 0:
                log.info("[%s] Alignment cache hit, skipping WhisperX", song_id)
                # Return aligned LRC from cache
                aligned_lrc = lyrics_result.lrc
            else:
                audio_path = sep_result.vocal_path if sep_result else dl_result.video_path
                for attempt in range(self.config.max_retries):
                    try:
                        align_result = await self._whisperx.align(
                            song_id, audio_path, lyrics_result.lrc
                        )
                        aligned_lrc = align_result.aligned_lrc
                        break
                    except AlignTempError as exc:
                        if attempt < self.config.max_retries - 1:
                            delay = (10, 30, 60)[attempt] if attempt < 3 else 60
                            log.warning("[%s] Alignment temp error, retrying in %ds: %s", song_id, delay, exc)
                            await asyncio.sleep(delay)
                        else:
                            # Line-level fallback — keep original LRC
                            log.warning("[%s] Alignment failed, keeping line-level LRC: %s", song_id, exc)
                            aligned_lrc = lyrics_result.lrc
                    except AlignPermError as exc:
                        # Keep line-level LRC without word alignment
                        log.warning("[%s] Alignment perm error, keeping line-level: %s", song_id, exc)
                        aligned_lrc = lyrics_result.lrc

        if aligned_lrc is None:
            aligned_lrc = lyrics_result.lrc

        return lyrics_result, aligned_lrc

    async def _package(
        self,
        song_id: str,
        dl_result: DownloadResult,
        sep_result: Optional[SeparationResult],
        lyrics_result: LyricsResult,
        aligned_lrc: Optional[str],
    ) -> dict:
        """Stage 4: LRC→ASS conversion + write final Song DB record."""
        log.info("[%s] Stage: package", song_id)
        await self._update_state(song_id, SongState.PACKAGING)

        files: dict = {
            "video": str(dl_result.video_path),
        }

        # Transcode oversized / >1080p video into media dir so streaming
        # serves a Tunnel-friendly file (huge 4K downloads cause playback lag).
        await self._transcode_video_async(song_id, dl_result.video_path)

        # ASS file (only when we have timed LRC)
        if aligned_lrc and lyrics_result.lyrics_type == "synced":
            try:
                lrc_converter = self._lrc_converter
                cache_dir = settings.data_dir / "media"
                lrc_converter.cache_dir = cache_dir
                ass_result = lrc_converter.convert(
                    song_id,
                    aligned_lrc,
                    total_duration_sec=dl_result.duration_sec,
                )
                files["lyrics_ass"] = str(ass_result.ass_path)
            except ConversionError as exc:
                log.warning("[%s] ASS conversion failed, skipping: %s", song_id, exc)

        # Plain-text lyrics — always save the text version when we have any lyrics
        if aligned_lrc:
            import re as _re
            text_lines = []
            for line in aligned_lrc.splitlines():
                stripped = _re.sub(r"\[\d{1,2}:\d{2}(?:\.\d{1,3})?\]", "", line).strip()
                if stripped:
                    text_lines.append(stripped)
            if text_lines:
                txt_path = settings.data_dir / "media" / song_id / "lyrics.txt"
                txt_path.parent.mkdir(parents=True, exist_ok=True)
                txt_path.write_text("\n".join(text_lines), encoding="utf-8")
                files["lyrics_text"] = str(txt_path)

        if sep_result:
            files["vocal"] = str(sep_result.vocal_path)
            files["instrumental"] = str(sep_result.instrumental_path)

            # Eagerly convert WAV → Opus so first play is smooth
            await self._convert_opus_async(sep_result.vocal_path)
            await self._convert_opus_async(sep_result.instrumental_path)

        # Write Song record
        with get_db_session() as db:
            song = db.query(Song).filter(Song.id == song_id).first()
            if song:
                song.title = dl_result.title
                song.artist = dl_result.artist
                song.duration_sec = dl_result.duration_sec
                song.thumbnail_url = dl_result.thumbnail_url
                song.files = files
                song.lyrics_source = lyrics_result.source
                song.lyrics_quality = lyrics_result.quality
                song.has_timing = lyrics_result.lyrics_type == "synced"
                song.processed_at = _utcnow()

        return files

    async def _transcode_video_async(self, song_id: str, video_path: Path) -> None:
        """Re-encode video to ≤1080p H.264 ~2Mbps into media/{id}/video.mp4.

        Skips if already ≤1080p AND under ~60MB (already Tunnel-friendly).
        The streaming endpoint prefers the media path, so this transparently
        replaces an oversized cache file without touching it.
        """
        if not video_path.exists():
            return
        media_out = settings.data_dir / "media" / song_id / "video.mp4"
        if media_out.exists() and media_out.stat().st_size > 0:
            return  # already transcoded

        import subprocess

        def _probe_and_run() -> None:
            try:
                size_mb = video_path.stat().st_size / (1024 * 1024)
                h = subprocess.run(
                    ["ffprobe", "-v", "error", "-select_streams", "v:0",
                     "-show_entries", "stream=height", "-of", "csv=p=0", str(video_path)],
                    capture_output=True, text=True, timeout=30,
                )
                height = int((h.stdout.strip() or "0").split(",")[0] or 0)
            except Exception:
                height, size_mb = 9999, 9999  # be safe → transcode

            media_out.parent.mkdir(parents=True, exist_ok=True)
            if height <= 1080 and size_mb < 60:
                # Small enough — just hardlink/copy into media for stable path
                try:
                    import shutil
                    shutil.copy2(video_path, media_out)
                    log.info("[%s] Video already small (%dp, %.0fMB) — copied",
                             song_id, height, size_mb)
                    return
                except Exception:
                    pass
            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(video_path),
                     "-vf", "scale='min(1920,iw)':'min(1080,ih)':"
                            "force_original_aspect_ratio=decrease",
                     "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
                     "-maxrate", "2500k", "-bufsize", "5000k",
                     "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
                     str(media_out)],
                    capture_output=True, timeout=900,
                )
                if media_out.exists():
                    new_mb = media_out.stat().st_size / (1024 * 1024)
                    log.info("[%s] Transcoded video %.0fMB → %.0fMB",
                             song_id, size_mb, new_mb)
            except Exception as exc:
                log.warning("[%s] Video transcode failed: %s", song_id, exc)

        await asyncio.to_thread(_probe_and_run)

    async def _convert_opus_async(self, wav_path: Path) -> None:
        """Convert wav_path to .opus with loudness normalization.

        Applies EBU R128 loudnorm to bring each track to -14 LUFS so the
        Demucs-separated vocal isn't perceptually quieter than the
        instrumental — without this the vocal slider feels useless because
        the raw vocal track is typically ~5-15 dB quieter than the original.
        """
        opus_path = wav_path.with_suffix(".opus")
        if opus_path.exists() and opus_path.stat().st_size > 0:
            return
        import subprocess

        def _run() -> None:
            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-i", str(wav_path),
                     "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
                     "-c:a", "libopus", "-b:a", "128k", "-vbr", "on",
                     str(opus_path)],
                    capture_output=True, timeout=180,
                )
            except Exception as exc:
                log.warning("Opus conversion failed for %s: %s", wav_path.name, exc)

        await asyncio.to_thread(_run)
        if opus_path.exists():
            log.info("Converted %s → %s (loudnorm applied)", wav_path.name, opus_path.name)

    # ------------------------------------------------------------------
    # State / DB helpers
    # ------------------------------------------------------------------

    # Rough progress percent per stage, for UI overlay
    _STAGE_PERCENT = {
        SongState.DOWNLOADING: 15,
        SongState.SEPARATING: 35,
        SongState.FETCHING_LYRICS: 55,
        SongState.ALIGNING: 75,
        SongState.PACKAGING: 90,
        SongState.READY: 100,
    }

    async def _update_state(self, song_id: str, state: SongState) -> None:
        """Update DB stage label + broadcast song.processing to the room.

        Frontend QueueList / NowPlaying STAGE_LABELS read from QueueItem.status,
        so writing the stage name there lights up the right label without
        adding a new field.
        """
        log.info("[%s] State: %s", song_id, state.value)

        # Update QueueItem.status to the stage name (kept in DB)
        if self._queue_item_id is not None:
            try:
                with get_db_session() as db:
                    item = db.query(QueueItem).filter(QueueItem.id == self._queue_item_id).first()
                    if item:
                        item.status = state.value
                        item.last_heartbeat = _utcnow()
            except Exception as exc:
                log.debug("[%s] queue status update failed: %s", song_id, exc)

        # Broadcast song.processing so clients can update their overlay
        if self._room_id is not None and self._queue_item_id is not None:
            try:
                from .ws_manager import manager
                percent = self._STAGE_PERCENT.get(state, 0)
                await manager.broadcast_song_processing(
                    self._room_id, self._queue_item_id, state.value, percent,
                )
                # Also refresh the queue list so QueueItem.status changes are visible
                from api.ws import _qi_to_dict  # local import to avoid cycle at module load
                from .queue_manager import QueueManager
                from .models import Song as SongModel, Guest as GuestModel
                with get_db_session() as db:
                    mgr = QueueManager(db)
                    queue = mgr.get_queue(self._room_id)
                    song_map = {s.id: s for s in db.query(SongModel).all()}
                    guest_map = {g.id: g for g in db.query(GuestModel).all()}
                    queue_dicts = [
                        _qi_to_dict(qi, song_map.get(qi.song_id), guest_map.get(qi.guest_id))
                        for qi in queue
                    ]
                await manager.broadcast_queue_updated(self._room_id, queue_dicts)
            except Exception as exc:
                log.debug("[%s] broadcast failed: %s", song_id, exc)

    async def _mark_ready(self, song_id: str) -> None:
        with get_db_session() as db:
            song = db.query(Song).filter(Song.id == song_id).first()
            if song:
                song.status = "ready"
                song.processed_at = _utcnow()

    async def _mark_failed_perm(self, song_id: str, reason: str) -> None:
        log.error("[%s] Marking failed_perm: %s", song_id, reason)
        with get_db_session() as db:
            song = db.query(Song).filter(Song.id == song_id).first()
            if song:
                song.status = "failed_perm"
                song.error_message = reason
                song.processed_at = _utcnow()

    # ------------------------------------------------------------------
    # Heartbeat loop (runs every 30s)
    # ------------------------------------------------------------------

    async def _heartbeat_loop(self, song_id: str) -> None:
        interval = self.config.heartbeat_interval_sec
        log.debug("[%s] Heartbeat started (every %ds)", song_id, interval)
        try:
            while True:
                await asyncio.sleep(interval)
                if self._cancel.is_set():
                    break
                # Update Song status (every beat, not just transition)
                try:
                    with get_db_session() as db:
                        song = db.query(Song).filter(Song.id == song_id).first()
                        if song:
                            song.last_heartbeat = _utcnow()
                except Exception as exc:
                    log.debug("[%s] Heartbeat DB update failed (non-critical): %s", song_id, exc)
        except asyncio.CancelledError:
            log.debug("[%s] Heartbeat cancelled", song_id)


# ---------------------------------------------------------------------------
# CLI entry point (M1-T7 deliverable)
# ---------------------------------------------------------------------------

async def process_song(youtube_url: str, position: str = "end") -> dict:
    """CLI entry: process one song from YouTube URL.

    Returns ``{"ok": True, "song_id": "...", "files": {...}}``
    or ``{"ok": False, "error": "..."}``.

    Usage::

        uv run python -m ktv_pipeline.pipeline_orchestrator "https://youtube.com/..."

    This function:
      1. Extracts youtube_id from URL
      2. Creates or updates Song DB record (status=pending)
      3. Runs the full pipeline
      4. Returns result dict
    """
    init_db()

    # Extract youtube_id
    import re
    _YOUTUBE_ID_RE = re.compile(
        r"(?:v=|youtu\.be/|embed/|/v/|/shorts/)([a-zA-Z0-9_-]{11})"
    )
    m = _YOUTUBE_ID_RE.search(youtube_url)
    if not m:
        return {"ok": False, "error": "invalid_youtube_url", "perm": True}
    youtube_id = m.group(1)

    # Ensure Song record exists in DB
    with get_db_session() as db:
        existing = db.query(Song).filter(Song.id == youtube_id).first()
        if not existing:
            song = Song(
                id=youtube_id,
                title="pending",
                processed_at=_utcnow(),
            )
            db.add(song)

    orchestrator = PipelineOrchestrator()
    return await orchestrator.run(youtube_id)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m ktv_pipeline.pipeline_orchestrator <youtube_url>")
        sys.exit(1)

    url = sys.argv[1]
    result = asyncio.run(process_song(url))
    print(result)