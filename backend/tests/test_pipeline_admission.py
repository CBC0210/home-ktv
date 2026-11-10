import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from api import songs
from ktv_pipeline.pipeline.lyrics import LyricsResult
from ktv_pipeline.pipeline_orchestrator import PipelineOrchestrator


@pytest.mark.asyncio
async def test_waiting_song_does_not_start_timeout_and_removed_song_is_ignored(monkeypatch):
    monkeypatch.setattr(songs, "_PIPELINE_SLOT", asyncio.Semaphore(1))
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.side_effect = [
        SimpleNamespace(status="pending"), None,
    ]
    context = MagicMock()
    context.__enter__.return_value = session
    monkeypatch.setattr(songs, "get_db_session", lambda: context)
    started, release = asyncio.Event(), asyncio.Event()

    async def run(*args):
        started.set()
        await release.wait()

    worker = AsyncMock(side_effect=run)
    monkeypatch.setattr(songs, "_run_pipeline_task_now", worker)
    first = asyncio.create_task(songs._run_pipeline_task(1, "room"))
    await started.wait()
    second = asyncio.create_task(songs._run_pipeline_task(2, "room"))
    await asyncio.sleep(0)
    assert worker.await_count == 1
    release.set()
    await asyncio.gather(first, second)
    assert worker.await_count == 1


@pytest.mark.asyncio
async def test_disabled_word_alignment_keeps_line_lyrics(monkeypatch):
    import ktv_pipeline.pipeline_orchestrator as module

    lyrics = LyricsResult(lyrics_type="synced", lrc="[00:01.00]hello", source="test", quality="line")
    monkeypatch.setattr(module.settings, "enable_word_alignment", False)
    monkeypatch.setattr(module, "fetch_lyrics", AsyncMock(return_value=lyrics))
    orch = PipelineOrchestrator()
    orch._update_state = AsyncMock()
    orch._whisperx.align = AsyncMock()
    result, lrc = await orch._fetch_and_align(
        "song", SimpleNamespace(title="Song", artist="Artist", duration_sec=60), None,
    )
    assert result is lyrics
    assert lrc == lyrics.lrc
    orch._whisperx.align.assert_not_awaited()


@pytest.mark.asyncio
async def test_schedule_pipeline_returns_without_waiting_for_long_job(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()

    async def long_job(*args):
        started.set()
        await release.wait()

    monkeypatch.setattr(songs, "_run_pipeline_task", long_job)
    await songs._schedule_pipeline(42, "room")
    await started.wait()
    assert any(not task.done() for task in songs._PIPELINE_TASKS)
    release.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert not songs._PIPELINE_TASKS
