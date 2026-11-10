"""Tests for pipeline_orchestrator.py"""

import asyncio
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

from ktv_pipeline.pipeline_orchestrator import (
    PipelineOrchestrator,
    PipelineConfig,
    TotalTimeoutError,
    FailedPermError,
    SongState,
    process_song,
)
from ktv_pipeline.pipeline.ytdlp import DownloadResult, PermDownloadError as YtPermError, TempDownloadError as YtTempError
from ktv_pipeline.pipeline.demucs import SeparationResult


class TestPipelineConfig:
    def test_default_values(self):
        cfg = PipelineConfig()
        assert cfg.max_retries == 3
        assert cfg.heartbeat_interval_sec == 30

    def test_custom_values(self):
        cfg = PipelineConfig(max_retries=5, heartbeat_interval_sec=10, total_timeout_sec=600)
        assert cfg.max_retries == 5
        assert cfg.heartbeat_interval_sec == 10
        assert cfg.total_timeout_sec == 600


class TestSongState:
    def test_all_states_defined(self):
        states = [
            SongState.QUEUED, SongState.PENDING, SongState.DOWNLOADING,
            SongState.SEPARATING, SongState.FETCHING_LYRICS, SongState.ALIGNING,
            SongState.PACKAGING, SongState.READY, SongState.PLAYING, SongState.DONE,
            SongState.FAILED_TEMP, SongState.FAILED_PERM, SongState.INTERRUPTED, SongState.STALE,
        ]
        assert len(states) == 14

    def test_state_is_string_enum(self):
        assert SongState.DOWNLOADING == "downloading"
        assert SongState.FAILED_PERM == "failed_perm"


class TestPipelineOrchestratorInit:
    def test_default_wrappers_created(self):
        orch = PipelineOrchestrator()
        assert orch._ytdlp is not None
        assert orch._demucs is not None
        assert orch._whisperx is not None
        assert orch._lrc_converter is not None

    def test_custom_wrappers_injected(self):
        mock_ytdlp = MagicMock()
        mock_demucs = MagicMock()
        mock_whisperx = MagicMock()
        mock_lrc = MagicMock()
        cfg = PipelineConfig(max_retries=1)
        orch = PipelineOrchestrator(
            config=cfg,
            ytdlp=mock_ytdlp,
            demucs=mock_demucs,
            whisperx=mock_whisperx,
            lrc_converter=mock_lrc,
        )
        assert orch._ytdlp is mock_ytdlp
        assert orch._demucs is mock_demucs
        assert orch._whisperx is mock_whisperx
        assert orch._lrc_converter is mock_lrc
        assert orch.config is cfg

    def test_heartbeat_not_started_on_init(self):
        orch = PipelineOrchestrator()
        assert orch._heartbeat_task is None


class TestOrchestratorRunPermDownloadError:
    """Tests for perm/temp error classification."""

    @pytest.mark.asyncio
    async def test_perm_download_error_returns_failed_perm(self):
        import tempfile
        mock_ytdlp = MagicMock()
        mock_ytdlp.download = AsyncMock(side_effect=YtPermError("video unavailable"))
        mock_ytdlp.cache_dir = Path(tempfile.mkdtemp())  # real path, not MagicMock
        mock_demucs = MagicMock()
        mock_demucs.separate = AsyncMock()
        mock_whisperx = MagicMock()
        mock_lrc_conv = MagicMock()

        orch = PipelineOrchestrator(
            ytdlp=mock_ytdlp, demucs=mock_demucs,
            whisperx=mock_whisperx, lrc_converter=mock_lrc_conv,
        )
        orch._started_at = 0.0
        orch._cancel = MagicMock()
        orch._cancel.is_set = MagicMock(return_value=False)
        orch._heartbeat_task = None

        # Mock _update_state as a regular async function
        async def noop_update(*args):
            pass
        orch._update_state = noop_update

        result = await orch._run_pipeline("abc123")
        assert result.get("ok") is False
        assert result.get("perm") is True


class TestOrchestratorHeartbeat:
    @pytest.mark.asyncio
    async def test_heartbeat_loop_runs_without_error(self):
        orch = PipelineOrchestrator()
        orch._cancel = asyncio.Event()
        orch._cancel.set()  # stop immediately
        orch._heartbeat_task = None
        orch._started_at = MagicMock()

        # Should not raise
        await orch._heartbeat_loop("abc123")


class TestProcessSong:
    @pytest.mark.asyncio
    async def test_invalid_url_returns_error(self):
        with patch("ktv_pipeline.pipeline_orchestrator.init_db"):
            result = await process_song("not-a-youtube-url")
        assert result["ok"] is False
        assert result["error"] == "invalid_video_url"
        assert result["perm"] is True

    @pytest.mark.asyncio
    async def test_valid_url_extracts_id_and_runs_pipeline(self):
        # Patch to avoid DB operations
        with patch("ktv_pipeline.pipeline_orchestrator.init_db"):
            with patch("ktv_pipeline.pipeline_orchestrator.get_db_session") as mock_db:
                mock_session = MagicMock()
                mock_session.__enter__ = MagicMock(return_value=mock_session)
                mock_session.__exit__ = MagicMock(return_value=None)
                mock_db.return_value = mock_session
                mock_session.query.return_value.filter.return_value.first.return_value = None

                mock_orch = MagicMock()
                mock_orch.run = AsyncMock(return_value={"ok": True, "files": {}})

                with patch("ktv_pipeline.pipeline_orchestrator.PipelineOrchestrator", return_value=mock_orch):
                    result = await process_song("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

                mock_orch.run.assert_called_once_with("dQw4w9WgXcQ")
                assert result["ok"] is True


class TestIdempotentDownloadCache:
    """Test that download stage is idempotent and skips re-download."""

    @pytest.mark.asyncio
    async def test_download_cache_hit_skips_ytdlp_download_call(self):
        """When video.mp4 + info.json exist, _ytdlp.download should NOT be called."""
        mock_ytdlp = MagicMock()
        mock_ytdlp.download = AsyncMock()  # Should NOT be called on cache hit
        mock_demucs = MagicMock()
        mock_demucs.separate = AsyncMock()
        mock_whisperx = MagicMock()
        mock_lrc_conv = MagicMock()

        # Create a real temp directory for the cache
        cache_root = Path("/tmp/test_cache_parent")
        song_dir = cache_root / "abc123"
        song_dir.mkdir(parents=True, exist_ok=True)
        (song_dir / "video.mp4").write_bytes(b"fake video content")
        (song_dir / "info.json").write_text('{"title":"Cached Song","uploader":"Cached Artist"}')

        # Set cache_dir on the mock so _download() finds the right path
        mock_ytdlp.cache_dir = cache_root

        orch = PipelineOrchestrator(
            ytdlp=mock_ytdlp, demucs=mock_demucs,
            whisperx=mock_whisperx, lrc_converter=mock_lrc_conv,
        )
        orch._started_at = 0.0
        orch._cancel = MagicMock()
        orch._cancel.is_set = MagicMock(return_value=False)
        orch._heartbeat_task = None

        async def noop_update(*args):
            pass
        orch._update_state = noop_update

        with patch("ktv_pipeline.pipeline_orchestrator.settings") as mock_settings:
            mock_settings.data_dir = cache_root
            result = await orch._download("abc123")

        # yt-dlp download should NOT have been called (cache hit)
        mock_ytdlp.download.assert_not_called()
        # Should have returned a result with the cached title
        assert result.youtube_id == "abc123"
        assert result.title == "Cached Song"


class TestStateMachine:
    def test_state_values_match_spec(self):
        """Verify state machine matches CLAUDE.md §21.4."""
        assert SongState.PENDING == "pending"
        assert SongState.DOWNLOADING == "downloading"
        assert SongState.SEPARATING == "separating"
        assert SongState.FETCHING_LYRICS == "fetching_lyrics"
        assert SongState.ALIGNING == "aligning"
        assert SongState.PACKAGING == "packaging"
        assert SongState.READY == "ready"
        assert SongState.PLAYING == "playing"
        assert SongState.DONE == "done"
        assert SongState.FAILED_TEMP == "failed_temp"
        assert SongState.FAILED_PERM == "failed_perm"
        assert SongState.INTERRUPTED == "interrupted"
        assert SongState.STALE == "stale"