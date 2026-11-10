"""Tests for DemucsWrapper.

All tests use mocks — no real GPU or model downloads.
"""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from ktv_pipeline.pipeline.demucs import (
    DemucsWrapper,
    SeparationResult,
    DemucsError,
    TemporaryError,
    PermanentError,
    _classify_exception,
    _outputs_exist,
    _cleanup_partial,
    _effective_device,
    _try_flush_cuda_cache,
    _GPU_LOCK,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def wrapper(tmp_path):
    return DemucsWrapper(
        cache_dir=tmp_path / "demucs",
        model_name="htdemucs_ft",
        device="cpu",
        timeout_sec=10,
        max_retries=3,
    )


@pytest.fixture()
def audio_file(tmp_path) -> Path:
    p = tmp_path / "video.mp4"
    p.write_bytes(b"fake-audio-data")
    return p


def _make_outputs(out_dir: Path) -> None:
    """Write non-empty stub output files."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "vocals.wav").write_bytes(b"vocals-data")
    (out_dir / "no_vocals.wav").write_bytes(b"instrumental-data")


# ---------------------------------------------------------------------------
# Unit tests — pure logic
# ---------------------------------------------------------------------------


class TestClassifyException:
    def test_oom_is_temporary(self):
        exc = RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")
        result = _classify_exception(exc)
        assert isinstance(result, TemporaryError)

    def test_corrupt_model_is_permanent(self):
        exc = RuntimeError("corrupt model file")
        result = _classify_exception(exc)
        assert isinstance(result, PermanentError)

    def test_missing_file_is_permanent(self):
        exc = FileNotFoundError("no such file: model.th")
        result = _classify_exception(exc)
        assert isinstance(result, PermanentError)

    def test_invalid_header_is_permanent(self):
        exc = RuntimeError("invalid header bytes")
        result = _classify_exception(exc)
        assert isinstance(result, PermanentError)

    def test_network_error_is_temporary(self):
        exc = ConnectionError("connection refused")
        result = _classify_exception(exc)
        assert isinstance(result, TemporaryError)

    def test_io_error_is_temporary(self):
        exc = OSError("disk I/O error")
        result = _classify_exception(exc)
        assert isinstance(result, TemporaryError)


class TestDeviceFallback:
    def test_unavailable_cuda_resolves_to_cpu(self):
        torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: False))
        assert _effective_device(torch, "cuda") == "cpu"

    def test_cuda_probe_failure_resolves_to_cpu(self):
        def broken_probe():
            raise RuntimeError("driver mismatch")

        torch = SimpleNamespace(cuda=SimpleNamespace(is_available=broken_probe))
        assert _effective_device(torch, "cuda") == "cpu"

    def test_explicit_cpu_stays_cpu_without_cuda_probe(self):
        torch = SimpleNamespace(
            cuda=SimpleNamespace(is_available=MagicMock(side_effect=AssertionError))
        )
        assert _effective_device(torch, "cpu") == "cpu"
        torch.cuda.is_available.assert_not_called()


class TestOutputsExist:
    def test_returns_false_when_dir_empty(self, tmp_path):
        assert not _outputs_exist(tmp_path / "missing")

    def test_returns_false_when_only_vocals(self, tmp_path):
        d = tmp_path / "song"
        d.mkdir()
        (d / "vocals.wav").write_bytes(b"x")
        assert not _outputs_exist(d)

    def test_returns_false_when_file_empty(self, tmp_path):
        d = tmp_path / "song"
        d.mkdir()
        (d / "vocals.wav").write_bytes(b"")
        (d / "no_vocals.wav").write_bytes(b"x")
        assert not _outputs_exist(d)

    def test_returns_true_when_both_exist(self, tmp_path):
        d = tmp_path / "song"
        _make_outputs(d)
        assert _outputs_exist(d)


class TestCleanupPartial:
    def test_removes_existing_files(self, tmp_path):
        _make_outputs(tmp_path)
        _cleanup_partial(tmp_path)
        assert not (tmp_path / "vocals.wav").exists()
        assert not (tmp_path / "no_vocals.wav").exists()

    def test_no_error_when_files_absent(self, tmp_path):
        _cleanup_partial(tmp_path / "nonexistent")  # must not raise


class TestTryFlushCudaCache:
    def test_does_not_raise_when_cuda_unavailable(self):
        torch = SimpleNamespace(
            cuda=SimpleNamespace(
                is_available=MagicMock(return_value=False),
                empty_cache=MagicMock(),
            )
        )
        with patch.dict("sys.modules", {"torch": torch}):
            _try_flush_cuda_cache()  # must not raise
        torch.cuda.empty_cache.assert_not_called()

    def test_calls_empty_cache_when_cuda_available(self):
        torch = SimpleNamespace(
            cuda=SimpleNamespace(
                is_available=MagicMock(return_value=True),
                empty_cache=MagicMock(),
            )
        )
        with patch.dict("sys.modules", {"torch": torch}):
            _try_flush_cuda_cache()
        torch.cuda.empty_cache.assert_called_once()


# ---------------------------------------------------------------------------
# DemucsWrapper — interface
# ---------------------------------------------------------------------------


class TestDemucsWrapperInterface:
    def test_instantiation_defaults(self, tmp_path):
        w = DemucsWrapper(cache_dir=tmp_path)
        assert w.cache_dir == tmp_path
        assert w.model_name == "htdemucs"
        assert w.max_retries == 3
        assert w.timeout_sec == 600

    def test_instantiation_custom(self, tmp_path):
        w = DemucsWrapper(
            cache_dir=tmp_path,
            model_name="htdemucs",
            device="cpu",
            timeout_sec=30,
            max_retries=1,
        )
        assert w.model_name == "htdemucs"
        assert w.device == "cpu"

    def test_has_separate_method(self, tmp_path):
        w = DemucsWrapper(cache_dir=tmp_path)
        assert callable(w.separate)


# ---------------------------------------------------------------------------
# DemucsWrapper — async behaviour
# ---------------------------------------------------------------------------


class TestSeparateSuccess:
    async def test_returns_result_on_success(self, wrapper, audio_file, tmp_path):
        song_id = "abc123"
        out_dir = tmp_path / "demucs" / song_id

        def fake_run(audio_path, out_dir, model_name, device):
            _make_outputs(out_dir)

        with patch(
            "ktv_pipeline.pipeline.demucs._run_demucs_sync", side_effect=fake_run
        ):
            result = await wrapper.separate(song_id=song_id, audio_path=audio_file)

        assert isinstance(result, SeparationResult)
        assert result.song_id == song_id
        assert result.vocal_path.name == "vocals.wav"
        assert result.instrumental_path.name == "no_vocals.wav"

    async def test_output_paths_correct(self, wrapper, audio_file, tmp_path):
        song_id = "xyz789"
        out_dir = tmp_path / "demucs" / song_id

        def fake_run(audio_path, od, model_name, device):
            _make_outputs(od)

        with patch(
            "ktv_pipeline.pipeline.demucs._run_demucs_sync", side_effect=fake_run
        ):
            result = await wrapper.separate(song_id=song_id, audio_path=audio_file)

        assert result.vocal_path == out_dir / "vocals.wav"
        assert result.instrumental_path == out_dir / "no_vocals.wav"


class TestIdempotency:
    async def test_skips_separation_if_outputs_exist(self, wrapper, audio_file, tmp_path):
        song_id = "cached_song"
        out_dir = tmp_path / "demucs" / song_id
        _make_outputs(out_dir)

        with patch(
            "ktv_pipeline.pipeline.demucs._run_demucs_sync"
        ) as mock_run:
            result = await wrapper.separate(song_id=song_id, audio_path=audio_file)
            mock_run.assert_not_called()

        assert result.song_id == song_id

    async def test_re_runs_if_outputs_missing(self, wrapper, audio_file, tmp_path):
        song_id = "not_cached"
        out_dir = tmp_path / "demucs" / song_id

        def fake_run(audio_path, od, model_name, device):
            _make_outputs(od)

        with patch(
            "ktv_pipeline.pipeline.demucs._run_demucs_sync", side_effect=fake_run
        ) as mock_run:
            await wrapper.separate(song_id=song_id, audio_path=audio_file)
            mock_run.assert_called_once()


class TestPermanentErrors:
    async def test_raises_permanent_for_missing_input(self, wrapper, tmp_path):
        missing = tmp_path / "does_not_exist.mp4"
        with pytest.raises(PermanentError, match="Input file not found"):
            await wrapper.separate(song_id="x", audio_path=missing)

    async def test_raises_permanent_for_corrupt_model(self, wrapper, audio_file):
        with patch(
            "ktv_pipeline.pipeline.demucs._run_demucs_sync",
            side_effect=RuntimeError("corrupt model file"),
        ):
            with pytest.raises(PermanentError):
                await wrapper.separate(song_id="x", audio_path=audio_file)

    async def test_does_not_retry_permanent_errors(self, wrapper, audio_file):
        call_count = 0

        def fail_perm(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("no such file: model.th")

        with patch("ktv_pipeline.pipeline.demucs._run_demucs_sync", side_effect=fail_perm):
            with pytest.raises(PermanentError):
                await wrapper.separate(song_id="x", audio_path=audio_file)

        assert call_count == 1  # no retries


class TestTemporaryErrors:
    async def test_retries_temp_error_then_succeeds(self, wrapper, audio_file, tmp_path):
        song_id = "retry_song"
        out_dir = tmp_path / "demucs" / song_id
        call_count = 0

        def flaky_run(audio_path, od, model_name, device):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise OSError("disk I/O error")
            _make_outputs(od)

        with patch("ktv_pipeline.pipeline.demucs._run_demucs_sync", side_effect=flaky_run), \
             patch("asyncio.sleep"):
            result = await wrapper.separate(song_id=song_id, audio_path=audio_file)

        assert call_count == 3
        assert result.song_id == song_id

    async def test_raises_temp_after_all_retries_exhausted(self, wrapper, audio_file):
        with patch(
            "ktv_pipeline.pipeline.demucs._run_demucs_sync",
            side_effect=OSError("I/O error"),
        ), patch("asyncio.sleep"):
            with pytest.raises(TemporaryError):
                await wrapper.separate(song_id="x", audio_path=audio_file)

    async def test_raises_temp_on_timeout(self, wrapper, audio_file):
        wrapper.max_retries = 1

        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()), \
             patch("asyncio.sleep"):
            with pytest.raises(TemporaryError, match="timed out"):
                await wrapper.separate(song_id="x", audio_path=audio_file)

    async def test_cleans_partial_output_before_retry(self, wrapper, audio_file, tmp_path):
        song_id = "partial_song"
        out_dir = tmp_path / "demucs" / song_id
        call_count = 0

        def write_then_fail(audio_path, od, model_name, device):
            nonlocal call_count
            call_count += 1
            od.mkdir(parents=True, exist_ok=True)
            (od / "vocals.wav").write_bytes(b"partial")
            raise OSError("write interrupted")

        with patch("ktv_pipeline.pipeline.demucs._run_demucs_sync", side_effect=write_then_fail), \
             patch("asyncio.sleep"):
            with pytest.raises(TemporaryError):
                await wrapper.separate(song_id=song_id, audio_path=audio_file)

        # After all retries, partial files should be cleaned up
        assert not (out_dir / "vocals.wav").exists()


class TestGpuLock:
    async def test_gpu_lock_serializes_calls(self, tmp_path, audio_file):
        """Verify that concurrent separate() calls are serialized via _GPU_LOCK."""
        order = []
        wrapper = DemucsWrapper(
            cache_dir=tmp_path / "demucs",
            device="cpu",
            timeout_sec=10,
            max_retries=1,
        )

        def shared_run(audio_path, od, model_name, device):
            # od.name is the song_id (directory name)
            song_id = od.name
            order.append(f"start:{song_id}")
            _make_outputs(od)
            order.append(f"end:{song_id}")

        # Single patch covers both concurrent calls — avoids patch-override race.
        with patch(
            "ktv_pipeline.pipeline.demucs._run_demucs_sync", side_effect=shared_run
        ):
            await asyncio.gather(
                wrapper.separate(song_id="song_a", audio_path=audio_file),
                wrapper.separate(song_id="song_b", audio_path=audio_file),
            )

        # Verify no interleaving: start→end pairs must be adjacent
        starts = [i for i, x in enumerate(order) if x.startswith("start:")]
        ends = [i for i, x in enumerate(order) if x.startswith("end:")]
        for s, e in zip(starts, ends):
            assert e == s + 1, f"Interleaved execution detected: {order}"


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------


class TestErrorHierarchy:
    def test_temporary_is_demucs_error(self):
        assert issubclass(TemporaryError, DemucsError)

    def test_permanent_is_demucs_error(self):
        assert issubclass(PermanentError, DemucsError)

    def test_demucs_error_is_exception(self):
        assert issubclass(DemucsError, Exception)
