"""Demucs vocal-separation wrapper.

Separates vocals from instrumental using the htdemucs_ft model.
GPU tasks are serialized via a module-level asyncio.Lock to prevent OOM on
the 4 GB GTX 1650.

Usage::

    wrapper = DemucsWrapper()
    result = await wrapper.separate(song_id="dQw4w9WgXcQ", audio_path=Path("video.mp4"))
    # result.vocal_path, result.instrumental_path
"""

import asyncio
import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..config import settings

log = logging.getLogger(__name__)

# One lock shared across all DemucsWrapper instances — only one GPU job at a time.
_GPU_LOCK: asyncio.Lock = asyncio.Lock()

# Retry delays in seconds for TemporaryError (exponential back-off).
_RETRY_DELAYS = (5, 30, 120)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class DemucsError(Exception):
    """Base class for all Demucs errors."""


class TemporaryError(DemucsError):
    """Transient error (OOM, IO) — caller should retry after a delay."""


class PermanentError(DemucsError):
    """Permanent error (corrupt model, unsupported format) — do not retry."""


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass
class SeparationResult:
    song_id: str
    vocal_path: Path
    instrumental_path: Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _classify_exception(exc: Exception) -> DemucsError:
    """Map a raw exception to TemporaryError or PermanentError."""
    msg = str(exc).lower()
    perm_signals = (
        "no such file",
        "invalid header",
        "corrupt",
        "unsupported format",
        "runtimeerror: error(s) in loading state_dict",
        "model not found",
    )
    for sig in perm_signals:
        if sig in msg:
            return PermanentError(str(exc))
    return TemporaryError(str(exc))


def _output_dir(base: Path, song_id: str) -> Path:
    return base / song_id


def _outputs_exist(out_dir: Path) -> bool:
    """Return True if both output files exist and are non-empty."""
    vocal = out_dir / "vocals.wav"
    inst = out_dir / "no_vocals.wav"
    return (
        vocal.exists()
        and vocal.stat().st_size > 0
        and inst.exists()
        and inst.stat().st_size > 0
    )


def _run_demucs_sync(
    audio_path: Path,
    out_dir: Path,
    model_name: str,
    device: str,
) -> None:
    """Run Demucs in a thread (blocking).

    Demucs places output under ``out_dir/<model_name>/<stem>/track.wav``.
    We rename to the flat layout expected by the pipeline:
      - out_dir/vocals.wav
      - out_dir/no_vocals.wav
    """
    import torch
    from demucs.pretrained import get_model
    from demucs.apply import apply_model
    import torchaudio

    # Load model
    model = get_model(model_name)
    model.eval()
    if device == "cuda" and torch.cuda.is_available():
        model.cuda()
        log.info("Demucs running on CUDA")
    else:
        log.info("Demucs running on CPU")

    # Load audio → (channels, samples) float tensor
    wav, sr = torchaudio.load(str(audio_path))
    # Demucs expects shape (batch, channels, samples); ensure stereo
    if wav.shape[0] == 1:
        wav = wav.repeat(2, 1)
    wav = wav.unsqueeze(0)  # (1, 2, samples)

    if device == "cuda" and torch.cuda.is_available():
        wav = wav.cuda()

    with torch.no_grad():
        sources = apply_model(model, wav, device=device, progress=False)

    # sources shape: (1, n_stems, 2, samples)
    sources = sources.squeeze(0).cpu()

    stem_names = model.sources  # e.g. ['drums', 'bass', 'other', 'vocals']
    vocal_idx = stem_names.index("vocals")

    vocals = sources[vocal_idx]  # (2, samples)
    # instrumental = sum of all non-vocal stems
    non_vocal = sum(sources[i] for i, s in enumerate(stem_names) if s != "vocals")

    out_dir.mkdir(parents=True, exist_ok=True)
    torchaudio.save(str(out_dir / "vocals.wav"), vocals, sr)
    torchaudio.save(str(out_dir / "no_vocals.wav"), non_vocal, sr)

    # Release GPU memory explicitly
    if device == "cuda":
        torch.cuda.empty_cache()

    log.info("Demucs separation complete → %s", out_dir)


# ---------------------------------------------------------------------------
# Wrapper
# ---------------------------------------------------------------------------


class DemucsWrapper:
    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        model_name: Optional[str] = None,
        device: Optional[str] = None,
        timeout_sec: int = 600,
        max_retries: int = 3,
    ):
        self.cache_dir = cache_dir or (settings.data_dir / "cache" / "demucs")
        self.model_name = model_name or settings.demucs_model
        self.device = device or ("cuda" if settings.enable_gpu else "cpu")
        self.timeout_sec = timeout_sec
        self.max_retries = max_retries

    # ------------------------------------------------------------------

    async def separate(self, song_id: str, audio_path: Path) -> SeparationResult:
        """Separate vocals from *audio_path*.

        Returns SeparationResult with paths to vocals.wav and no_vocals.wav.
        Raises TemporaryError (retriable) or PermanentError (fatal).

        The operation is idempotent: if outputs already exist they are returned
        immediately without re-running Demucs.
        """
        if not audio_path.exists():
            raise PermanentError(f"Input file not found: {audio_path}")

        out_dir = _output_dir(self.cache_dir, song_id)

        # Idempotency check
        if _outputs_exist(out_dir):
            log.info("Demucs cache hit for %s, skipping separation", song_id)
            return SeparationResult(
                song_id=song_id,
                vocal_path=out_dir / "vocals.wav",
                instrumental_path=out_dir / "no_vocals.wav",
            )

        last_exc: Optional[Exception] = None
        delays = list(_RETRY_DELAYS)

        for attempt in range(self.max_retries):
            try:
                log.info(
                    "Demucs separation %s attempt %d/%d (acquiring GPU lock)",
                    song_id,
                    attempt + 1,
                    self.max_retries,
                )
                async with _GPU_LOCK:
                    log.info("GPU lock acquired for %s", song_id)
                    await asyncio.wait_for(
                        asyncio.to_thread(
                            _run_demucs_sync,
                            audio_path,
                            out_dir,
                            self.model_name,
                            self.device,
                        ),
                        timeout=self.timeout_sec,
                    )

                log.info("Demucs finished for %s", song_id)
                return SeparationResult(
                    song_id=song_id,
                    vocal_path=out_dir / "vocals.wav",
                    instrumental_path=out_dir / "no_vocals.wav",
                )

            except asyncio.TimeoutError as exc:
                last_exc = TemporaryError(
                    f"Demucs timed out after {self.timeout_sec}s for {song_id}"
                )
                log.warning("Demucs timeout for %s attempt %d", song_id, attempt + 1)
                # Remove partial outputs before retry
                _cleanup_partial(out_dir)

            except Exception as exc:
                classified = _classify_exception(exc)
                if isinstance(classified, PermanentError):
                    log.error("Demucs permanent error for %s: %s", song_id, exc)
                    raise classified from exc
                last_exc = classified
                log.warning(
                    "Demucs temp error for %s attempt %d: %s",
                    song_id,
                    attempt + 1,
                    exc,
                )
                _cleanup_partial(out_dir)
                # On CUDA OOM, flush cache before retry
                _try_flush_cuda_cache()

            if attempt < self.max_retries - 1:
                delay = delays[attempt] if attempt < len(delays) else delays[-1]
                log.info("Retrying %s in %ds", song_id, delay)
                await asyncio.sleep(delay)

        raise last_exc or TemporaryError(
            f"Demucs failed after {self.max_retries} attempts for {song_id}"
        )


# ---------------------------------------------------------------------------
# Internal utilities
# ---------------------------------------------------------------------------


def _cleanup_partial(out_dir: Path) -> None:
    """Remove incomplete output files so retry starts clean."""
    for fname in ("vocals.wav", "no_vocals.wav"):
        p = out_dir / fname
        if p.exists():
            try:
                p.unlink()
            except OSError:
                pass


def _try_flush_cuda_cache() -> None:
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            log.debug("CUDA cache flushed")
    except Exception:
        pass
