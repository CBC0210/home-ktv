"""Unit coverage for the pipeline's final playable-asset gate."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ktv_pipeline.pipeline_orchestrator import PipelineConfig, PipelineOrchestrator


def _db_for(song):
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = song
    context = MagicMock()
    context.__enter__.return_value = session
    context.__exit__.return_value = None
    return context


@pytest.mark.asyncio
async def test_failed_pipeline_result_is_never_promoted_to_ready():
    orch = PipelineOrchestrator(config=PipelineConfig(total_timeout_sec=5))
    orch._run_pipeline = AsyncMock(return_value={"ok": False, "error": "demucs failed", "perm": True})
    orch._mark_ready = AsyncMock(return_value=True)
    orch._mark_failed_perm = AsyncMock()

    result = await orch.run("failed-song")

    assert result["ok"] is False
    orch._mark_ready.assert_not_awaited()
    orch._mark_failed_perm.assert_awaited_once_with("failed-song", "demucs failed")


@pytest.mark.asyncio
async def test_video_only_song_is_not_ready_in_separated_mode(tmp_path):
    song = SimpleNamespace(
        id="video-only", status="packaging", error_message=None,
        processed_at=None, extra_metadata={},
    )
    video = tmp_path / "media" / song.id / "video.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"video")
    orch = PipelineOrchestrator()

    with patch("ktv_pipeline.pipeline_orchestrator.get_db_session", return_value=_db_for(song)), \
         patch("ktv_pipeline.playback_assets.settings") as config:
        config.data_dir = tmp_path
        assert await orch._mark_ready(song.id) is False

    assert song.status == "failed_perm"
    assert "playback assets" in song.error_message


@pytest.mark.asyncio
async def test_nonempty_opus_pair_promotes_song_to_ready(tmp_path):
    song = SimpleNamespace(
        id="opus-ready", status="packaging", error_message=None,
        processed_at=None, extra_metadata={"playback": {"use_original_audio": False}},
    )
    video = tmp_path / "cache" / song.id / "video.mp4"
    audio = tmp_path / "cache" / "demucs" / song.id
    video.parent.mkdir(parents=True)
    audio.mkdir(parents=True)
    video.write_bytes(b"video")
    (audio / "vocals.opus").write_bytes(b"opus vocals")
    (audio / "no_vocals.opus").write_bytes(b"opus instrumental")
    orch = PipelineOrchestrator()

    with patch("ktv_pipeline.pipeline_orchestrator.get_db_session", return_value=_db_for(song)), \
         patch("ktv_pipeline.playback_assets.settings") as config:
        config.data_dir = tmp_path
        assert await orch._mark_ready(song.id) is True

    assert song.status == "ready"
