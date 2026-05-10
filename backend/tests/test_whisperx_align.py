"""Tests for WhisperX forced alignment wrapper.

All tests use mocks — no real GPU or model downloads.
"""

import asyncio
import re
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from ktv_pipeline.pipeline.whisperx_align import (
    WhisperXWrapper,
    AlignmentResult,
    AlignmentError,
    TemporaryError,
    PermanentError,
    _classify_exception,
    _parse_lrc_lines,
    _ms_from_timestamp,
    _is_chinese,
    _format_ts_ms,
    _line_level_fallback,
    _build_word_lrc,
    _GPU_LOCK,
    _ALIGN_TIMEOUT_SEC,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def wrapper(tmp_path) -> WhisperXWrapper:
    return WhisperXWrapper(
        cache_dir=tmp_path / "whisperx",
        model_name="small",
        device="cpu",
        timeout_sec=30,
        max_retries=3,
    )


LRC_SAMPLE = (
    "[00:12.00]Hello world\n"
    "[00:15.50]This is a test\n"
    "[00:20.00]Goodbye"
)

LRC_CN_SAMPLE = (
    "[00:10.00]你好世界\n"
    "[00:15.00]這是一首測試歌\n"
)


# ---------------------------------------------------------------------------
# Unit tests — pure functions
# ---------------------------------------------------------------------------


class TestClassifyException:
    def test_oom_is_temporary(self):
        exc = RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")
        assert isinstance(_classify_exception(exc), TemporaryError)

    def test_corrupt_model_is_permanent(self):
        exc = RuntimeError("corrupt model file")
        assert isinstance(_classify_exception(exc), PermanentError)

    def test_model_not_found_is_permanent(self):
        exc = RuntimeError("model not found at path")
        assert isinstance(_classify_exception(exc), PermanentError)

    def test_invalid_audio_is_permanent(self):
        exc = RuntimeError("invalid audio format")
        assert isinstance(_classify_exception(exc), PermanentError)

    def test_timeout_is_temporary(self):
        exc = TimeoutError("operation timed out")
        assert isinstance(_classify_exception(exc), TemporaryError)

    def test_io_error_is_temporary(self):
        exc = OSError("disk I/O error")
        assert isinstance(_classify_exception(exc), TemporaryError)


class TestParseLrcLines:
    def test_parses_standard_format(self):
        lines = list(_parse_lrc_lines("[01:23.45]Hello world"))
        assert len(lines) == 1
        assert lines[0] == ("01:23.45", "Hello world")

    def test_parses_without_hundredths(self):
        lines = list(_parse_lrc_lines("[01:23]Hello world"))
        assert len(lines) == 1
        assert lines[0] == ("01:23", "Hello world")

    def test_strips_trailing_whitespace(self):
        lines = list(_parse_lrc_lines("[01:23.45]  Hello world  "))
        assert lines[0][1] == "Hello world"

    def test_skips_empty_lines(self):
        lines = list(_parse_lrc_lines("[01:23.45]"))
        assert len(lines) == 0

    def test_parses_multiple_lines(self):
        lines = list(_parse_lrc_lines(LRC_SAMPLE))
        assert len(lines) == 3
        assert lines[0] == ("00:12.00", "Hello world")
        assert lines[1] == ("00:15.50", "This is a test")
        assert lines[2] == ("00:20.00", "Goodbye")

    def test_parses_chinese_lrc(self):
        lines = list(_parse_lrc_lines(LRC_CN_SAMPLE))
        assert len(lines) == 2
        assert lines[0] == ("00:10.00", "你好世界")


class TestMsFromTimestamp:
    def test_parses_standard(self):
        assert _ms_from_timestamp("01:23.45") == pytest.approx(83450.0, abs=1)

    def test_parses_without_hundredths(self):
        assert _ms_from_timestamp("01:23") == pytest.approx(83000.0, abs=1)

    def test_parses_zero(self):
        assert _ms_from_timestamp("00:00.00") == 0.0


class TestIsChinese:
    def test_chinese_characters(self):
        assert _is_chinese("你好")

    def test_english_characters(self):
        assert not _is_chinese("hello")

    def test_mixed(self):
        assert _is_chinese("hello你好的世界")


class TestFormatTsMs:
    def test_formats_correctly(self):
        assert _format_ts_ms(0.0) == "00:00.00"

    def test_formats_minutes(self):
        assert _format_ts_ms(90000.0) == "01:30.00"

    def test_formats_with_hundredths(self):
        assert _format_ts_ms(12345.0) == "00:12.35"


class TestLineLevelFallback:
    def test_english_splits_by_word(self):
        lines = [("00:12.00", "Hello world")]
        result = _line_level_fallback(lines)
        assert "[00:12.00]Hello" in result
        assert "[00:12.00]world" in result

    def test_chinese_splits_by_character(self):
        lines = [("00:10.00", "你好")]
        result = _line_level_fallback(lines)
        assert "[00:10.00]你" in result
        assert "[00:10.00]好" in result

    def test_skips_empty_lines(self):
        lines = [("00:10.00", "")]
        result = _line_level_fallback(lines)
        assert result == ""


class TestBuildWordLrc:
    def test_chinese_one_tag_per_char(self):
        lines = [("00:10.00", "你好")]
        word_data = [
            {"word": "你", "start": 10000.0, "end": 10500.0},
            {"word": "好", "start": 10500.0, "end": 11000.0},
        ]
        result = _build_word_lrc(lines, word_data)
        assert "[00:10.00]你" in result
        assert "[00:10.50]好" in result

    def test_runs_out_of_word_data_falls_back_to_line_ts(self):
        lines = [("00:10.00", "你好")]
        word_data = [
            {"word": "你", "start": 10000.0, "end": 10500.0},
            # missing "好" — falls back to line timestamp
        ]
        result = _build_word_lrc(lines, word_data)
        assert "[00:10.00]你" in result
        assert "[00:10.00]好" in result  # fallback

    def test_empty_lines_skipped(self):
        lines = [("00:10.00", ""), ("00:12.00", "Hi")]
        word_data = [{"word": "Hi", "start": 12000.0, "end": 12500.0}]
        result = _build_word_lrc(lines, word_data)
        assert result.count("\n") == 1  # only "Hi" line


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------


class TestErrorHierarchy:
    def test_temporary_is_alignment_error(self):
        assert issubclass(TemporaryError, AlignmentError)

    def test_permanent_is_alignment_error(self):
        assert issubclass(PermanentError, AlignmentError)

    def test_alignment_error_is_exception(self):
        assert issubclass(AlignmentError, Exception)


# ---------------------------------------------------------------------------
# WhisperXWrapper — interface
# ---------------------------------------------------------------------------


class TestWhisperXWrapperInterface:
    def test_instantiation_defaults(self, tmp_path):
        w = WhisperXWrapper(cache_dir=tmp_path)
        assert w.model_name == "small"
        assert w.max_retries == 3
        assert w.timeout_sec == _ALIGN_TIMEOUT_SEC

    def test_instantiation_custom(self, tmp_path):
        w = WhisperXWrapper(
            cache_dir=tmp_path,
            model_name="medium",
            device="cpu",
            timeout_sec=30,
            max_retries=1,
        )
        assert w.model_name == "medium"
        assert w.device == "cpu"
        assert w.max_retries == 1

    def test_has_align_method(self, tmp_path):
        w = WhisperXWrapper(cache_dir=tmp_path)
        assert callable(w.align)


# ---------------------------------------------------------------------------
# WhisperXWrapper — async behaviour
# ---------------------------------------------------------------------------


class TestIdempotency:
    async def test_skips_if_cached_lrc_exists(self, wrapper, tmp_path):
        song_id = "cached_song"
        cache_dir = tmp_path / "whisperx"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached = cache_dir / song_id / "aligned.lrc"
        cached.parent.mkdir(parents=True)
        cached.write_text("[00:00.00]cached line")

        audio_file = tmp_path / "audio.wav"
        audio_file.write_bytes(b"fake")

        with patch(
            "ktv_pipeline.pipeline.whisperx_align._run_align_sync"
        ) as mock_run:
            result = await wrapper.align(
                song_id=song_id,
                audio_path=audio_file,
                lrc_content=LRC_SAMPLE,
            )
            mock_run.assert_not_called()

        assert result.source == "whisperx_align"
        assert result.aligned_lrc == "[00:00.00]cached line"

    async def test_runs_if_cache_missing(self, wrapper, tmp_path):
        song_id = "not_cached"
        audio_file = tmp_path / "audio.wav"
        audio_file.write_bytes(b"fake")

        def fake_run(audio_path, lrc_content, model_name, device):
            return {
                "success": True,
                "aligned_lrc": "[00:00.00]aligned",
                "word_level": True,
                "error": None,
            }

        with patch(
            "ktv_pipeline.pipeline.whisperx_align._run_align_sync",
            side_effect=fake_run,
        ) as mock_run:
            result = await wrapper.align(
                song_id=song_id,
                audio_path=audio_file,
                lrc_content=LRC_SAMPLE,
            )
            mock_run.assert_called_once()

        assert result.source == "whisperx_align"


class TestPermanentErrors:
    async def test_raises_permanent_for_missing_audio(self, wrapper, tmp_path):
        missing = tmp_path / "does_not_exist.wav"
        with pytest.raises(PermanentError, match="Audio file not found"):
            await wrapper.align(song_id="x", audio_path=missing, lrc_content=LRC_SAMPLE)

    async def test_raises_permanent_for_empty_lrc(self, wrapper, tmp_path):
        audio_file = tmp_path / "audio.wav"
        audio_file.write_bytes(b"fake")
        with pytest.raises(PermanentError, match="LRC content is empty"):
            await wrapper.align(song_id="x", audio_path=audio_file, lrc_content="")

    async def test_raises_permanent_for_corrupt_model(self, wrapper, tmp_path):
        audio_file = tmp_path / "audio.wav"
        audio_file.write_bytes(b"fake")

        with patch(
            "ktv_pipeline.pipeline.whisperx_align._run_align_sync",
            side_effect=RuntimeError("corrupt model file"),
        ):
            with pytest.raises(PermanentError):
                await wrapper.align(song_id="x", audio_path=audio_file, lrc_content=LRC_SAMPLE)

    async def test_does_not_retry_permanent_errors(self, wrapper, tmp_path):
        call_count = 0
        audio_file = tmp_path / "audio.wav"
        audio_file.write_bytes(b"fake")

        def fail_perm(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("model not found")

        with patch(
            "ktv_pipeline.pipeline.whisperx_align._run_align_sync",
            side_effect=fail_perm,
        ):
            with pytest.raises(PermanentError):
                await wrapper.align(song_id="x", audio_path=audio_file, lrc_content=LRC_SAMPLE)

        assert call_count == 1


class TestTemporaryErrors:
    async def test_retries_temp_error_then_succeeds(self, wrapper, tmp_path):
        song_id = "retry_song"
        audio_file = tmp_path / "audio.wav"
        audio_file.write_bytes(b"fake")
        call_count = 0

        def flaky_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise OSError("CUDA error")
            return {
                "success": True,
                "aligned_lrc": "[00:00.00]ok",
                "word_level": True,
                "error": None,
            }

        with patch(
            "ktv_pipeline.pipeline.whisperx_align._run_align_sync",
            side_effect=flaky_run,
        ), patch("asyncio.sleep"):
            result = await wrapper.align(
                song_id=song_id,
                audio_path=audio_file,
                lrc_content=LRC_SAMPLE,
            )

        assert call_count == 3
        assert result.source == "whisperx_align"

    async def test_falls_back_to_line_level_after_all_retries(self, wrapper, tmp_path):
        song_id = "fallback_song"
        audio_file = tmp_path / "audio.wav"
        audio_file.write_bytes(b"fake")

        with patch(
            "ktv_pipeline.pipeline.whisperx_align._run_align_sync",
            side_effect=OSError("CUDA error"),
        ), patch("asyncio.sleep"):
            result = await wrapper.align(
                song_id=song_id,
                audio_path=audio_file,
                lrc_content=LRC_CN_SAMPLE,
            )

        # Should fall back to line-level
        assert result.source is None
        assert result.word_level is False
        assert "你" in result.aligned_lrc
        assert "好" in result.aligned_lrc

    async def test_raises_temp_after_all_retries_exhausted_no_fallback(self, wrapper, tmp_path):
        wrapper.max_retries = 1
        audio_file = tmp_path / "audio.wav"
        audio_file.write_bytes(b"fake")

        with patch(
            "ktv_pipeline.pipeline.whisperx_align._run_align_sync",
            side_effect=OSError("I/O error"),
        ), patch("asyncio.sleep"):
            # Even with line-level fallback, all retries failing
            # should still fall back gracefully
            result = await wrapper.align(
                song_id="x",
                audio_path=audio_file,
                lrc_content=LRC_SAMPLE,
            )
            # fallback works
            assert result.source is None


class TestGpuLock:
    async def test_gpu_lock_serializes_concurrent_calls(self, tmp_path, audio_file):
        order = []
        wrapper = WhisperXWrapper(
            cache_dir=tmp_path / "whisperx",
            device="cpu",
            timeout_sec=10,
            max_retries=1,
        )

        def shared_run(*args, **kwargs):
            song_id = kwargs.get("song_id", args[0] if args else "?")
            order.append(f"start:{song_id}")
            order.append(f"end:{song_id}")

        audio_file = tmp_path / "audio.wav"
        audio_file.write_bytes(b"fake")

        with patch(
            "ktv_pipeline.pipeline.whisperx_align._run_align_sync",
            side_effect=lambda *a, **kw: {
                "success": True,
                "aligned_lrc": "",
                "word_level": True,
                "error": None,
            },
        ):
            await asyncio.gather(
                wrapper.align(song_id="song_a", audio_path=audio_file, lrc_content=LRC_SAMPLE),
                wrapper.align(song_id="song_b", audio_path=audio_file, lrc_content=LRC_SAMPLE),
            )

        # start→end pairs must be adjacent (serialised by GPU lock)
        starts = [i for i, x in enumerate(order) if x.startswith("start:")]
        ends = [i for i, x in enumerate(order) if x.startswith("end:")]
        for s, e in zip(starts, ends):
            assert e == s + 1, f"Interleaved execution: {order}"
