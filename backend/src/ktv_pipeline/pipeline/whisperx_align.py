"""WhisperX forced alignment wrapper.

Aligns a line-level LRC lyrics transcript to word-level (and character-level for
Chinese) timestamps using WhisperX.  This is the final step in the lyrics pipeline
(ADR-005 §7.4) — it runs after lyrics have been fetched and before LRC→ASS
conversion.

Usage::

    wrapper = WhisperXWrapper()
    result = await wrapper.align(
        song_id="dQw4w9WgXcQ",
        audio_path=Path("vocals.wav"),
        lrc_content="[00:12.00]Hello world\n[00:15.50]This is a test",
    )
    # result.aligned_lrc   — word-level LRC with [mm:ss.xx] word tags
    # result.word-level True/False

GPU tasks are serialised via a module-level ``asyncio.Lock`` (shared with Demucs
— only one GPU job runs at a time on the 4 GB GTX 1650).

Model: ``settings.whisperx_model`` (default ``"small"``, safe for 4 GB VRAM).
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..config import settings

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lock — serialises ALL GPU tasks (WhisperX + Demucs share the same card).
# ---------------------------------------------------------------------------
_GPU_LOCK: asyncio.Lock = asyncio.Lock()

# Retry delays in seconds (exponential back-off) for TemporaryError.
_RETRY_DELAYS = (10, 30, 60)

# WhisperX alignment timeout per call.
_ALIGN_TIMEOUT_SEC = 600


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AlignmentError(Exception):
    """Base class."""


class TemporaryError(AlignmentError):
    """Transient error (OOM, CUDA, timeout) — caller should retry after a delay."""


class PermanentError(AlignmentError):
    """Non-recoverable error (model corrupt, unsupported audio) — do not retry."""


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


@dataclass
class AlignmentResult:
    """Output of WhisperX forced alignment.

    Attributes
    ----------
    aligned_lrc:
        LRC string with word-level timestamps.  Lines look like
        ``[00:12.00]word1 [00:12.45]word2`` for Chinese, or one ``[mm:ss.xx]word``
        tag per word for English.
        Empty string if all attempts failed.
    source:
        Always ``"whisperx_align"`` on success, else ``None``.
    word_level:
        ``True`` when word-level timing was obtained; ``False`` on fallback
        (line-level only).
    """

    aligned_lrc: str
    source: Optional[str]
    word_level: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _classify_exception(exc: Exception) -> AlignmentError:
    """Map a raw exception to TemporaryError or PermanentError."""
    msg = str(exc).lower()
    perm_signals = (
        "model not found",
        "corrupt",
        "invalid audio",
        "unsupported format",
        "state_dict",
    )
    for sig in perm_signals:
        if sig in msg:
            return PermanentError(str(exc))
    # CUDA OOM, timeout, I/O → temporary
    return TemporaryError(str(exc))


def _parse_lrc_lines(lrc: str) -> list[tuple[str, str]]:
    """Yield (timestamp, text) pairs from an LRC string.

    Handles both ``[mm:ss.xx]text`` and ``[mm:ss]text`` formats.
    Strips trailing whitespace from text.
    """
    pattern = re.compile(r"\[(\d{1,2}:\d{2}(?:\.\d{1,3})?)\](.*)")
    for line in lrc.splitlines():
        m = pattern.match(line.strip())
        if m and m.group(2).strip():
            yield m.group(1), m.group(2).strip()


def _ms_from_timestamp(ts: str) -> float:
    """Convert ``mm:ss.xx`` or ``mm:ss`` to total milliseconds (float)."""
    if ":" not in ts:
        return 0.0
    minutes, rest = ts.split(":", 1)
    if "." in rest:
        secs, hundredths = rest.split(".")
    else:
        secs, hundredths = rest, "0"
    return (float(minutes) * 60 + float(secs) + float(f"0.{hundredths:0<3}")) * 1000


def _is_chinese(text: str) -> bool:
    """Return True if *text* contains at least one CJK character."""
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def _build_word_lrc(
    lines: list[tuple[str, str]],
    word_data: list[dict],  # List[{"word": str, "start": float, "end": float}]
) -> str:
    """Build a word-level LRC string from WhisperX word-level output.

    Chinese: outputs one ``[mm:ss.xx]char`` tag per character.
    English: outputs one ``[mm:ss.xx]word`` tag per word.
    """
    output_lines = []
    wi = 0  # word_data index

    for ts, text in lines:
        if not text:
            continue

        if _is_chinese(text):
            # One tag per character, anchored to the line's timestamp
            for char in text:
                if wi < len(word_data):
                    wd = word_data[wi]
                    ts_out = _format_ts_ms(wd["start"])
                    output_lines.append(f"[{ts_out}]{char}")
                    wi += 1
                else:
                    # Fall back to the line timestamp if we run out of word data
                    output_lines.append(f"[{ts}]{char}")
        else:
            # English: one timestamped tag per word, consume from word_data in order.
            for word in text.split():
                if wi < len(word_data):
                    wd = word_data[wi]
                    ts_out = _format_ts_ms(wd["start"])
                    output_lines.append(f"[{ts_out}]{word}")
                    wi += 1
                else:
                    output_lines.append(f"[{ts}]{word}")

    return "\n".join(output_lines)


def _format_ts_ms(ms: float) -> str:
    """Format milliseconds as ``mm:ss.xx`` LRC timestamp."""
    total_secs = ms / 1000.0
    minutes = int(total_secs // 60)
    secs = total_secs % 60
    return f"{minutes:02d}:{secs:05.2f}"


def _line_level_fallback(lines: list[tuple[str, str]]) -> str:
    """When WhisperX fails, redistribute line timestamps evenly per character."""
    result_lines = []
    for ts, text in lines:
        if not text:
            continue
        if _is_chinese(text):
            for char in text:
                result_lines.append(f"[{ts}]{char}")
        else:
            for word in text.split():
                result_lines.append(f"[{ts}]{word}")
    return "\n".join(result_lines)


# ---------------------------------------------------------------------------
# Core alignment logic (runs in thread to avoid blocking the event loop)
# ---------------------------------------------------------------------------


def _run_align_sync(
    audio_path: Path,
    lrc_content: str,
    model_name: str,
    device: str,
) -> dict:
    """Run WhisperX alignment in a blocking thread.

    Returns a dict: ``{"success": bool, "aligned_lrc": str, "word_level": bool,
    "error": str | None}``
    """
    import torch

    # Import whisperx lazily — only when we actually need the GPU
    import whisperx

    log.info("Loading WhisperX model '%s' on device '%s'", model_name, device)

    # 1. Load audio
    audio = whisperx.load_audio(str(audio_path))

    # 2. Load model
    # compute_type: for 4 GB VRAM use "float16" (default) — tight but safe.
    # If OOM, caller catches and retries on CPU.
    model = whisperx.load_model(
        model_name,
        device=device,
        compute_type="float16",
    )

    # 3. Transcribe with word-level timestamps
    options = whisperx.DecodingOptions(
        language="zh" if any(_is_chinese(t) for _, t in _parse_lrc_lines(lrc_content)) else None,
        task="transcribe",
        word_timestamps=True,
    )
    result = whisperx.decoding.get_orbit_model(model).decode(
        model, audio, options=options
    )
    # result is a list; take the first entry
    segments = result[0].get("segments", []) if isinstance(result, list) else result.get("segments", [])

    # 4. Align LRC lines against WhisperX word segments
    lrc_lines = list(_parse_lrc_lines(lrc_content))
    all_words: list[dict] = []
    for seg in segments:
        for w in seg.get("words", []):
            all_words.append({
                "word": w.get("word", "").strip(),
                "start": w.get("start", 0.0) * 1000,  # ms
                "end": w.get("end", 0.0) * 1000,
            })

    if not all_words:
        raise PermanentError("WhisperX returned no word-level segments")

    aligned_lrc = _build_word_lrc(lrc_lines, all_words)

    # Clean up GPU memory
    del model
    if device == "cuda":
        torch.cuda.empty_cache()

    return {
        "success": True,
        "aligned_lrc": aligned_lrc,
        "word_level": True,
        "error": None,
    }


# ---------------------------------------------------------------------------
# Wrapper
# ---------------------------------------------------------------------------


class WhisperXWrapper:
    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        model_name: Optional[str] = None,
        device: Optional[str] = None,
        timeout_sec: int = _ALIGN_TIMEOUT_SEC,
        max_retries: int = 3,
    ):
        self.cache_dir = cache_dir or (settings.data_dir / "cache" / "whisperx")
        self.model_name = model_name or settings.whisperx_model
        self.device = device or ("cuda" if settings.enable_gpu else "cpu")
        self.timeout_sec = timeout_sec
        self.max_retries = max_retries

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def align(
        self,
        song_id: str,
        audio_path: Path,
        lrc_content: str,
    ) -> AlignmentResult:
        """Align *lrc_content* to word-level timestamps using WhisperX.

        Returns ``AlignmentResult`` with:
          - ``aligned_lrc``: word-level LRC string
          - ``source``: ``"whisperx_align"`` or ``None``
          - ``word_level``: ``True`` on success, ``False`` on fallback

        The operation is **idempotent**: if an aligned result already exists in
        the cache it is returned immediately without re-running WhisperX.

        Raises ``TemporaryError`` (retriable) or ``PermanentError`` (fatal).
        """
        if not audio_path.exists():
            raise PermanentError(f"Audio file not found: {audio_path}")

        lrc_lines = list(_parse_lrc_lines(lrc_content))
        if not lrc_lines:
            raise PermanentError("LRC content is empty or unparseable")

        out_dir = self.cache_dir / song_id
        cached = out_dir / "aligned.lrc"
        if cached.exists() and cached.stat().st_size > 0:
            log.info("WhisperX cache hit for %s, skipping alignment", song_id)
            return AlignmentResult(
                aligned_lrc=cached.read_text(),
                source="whisperx_align",
                word_level=True,
            )

        last_exc: Optional[Exception] = None
        delays = list(_RETRY_DELAYS)

        for attempt in range(self.max_retries):
            try:
                log.info(
                    "WhisperX alignment %s attempt %d/%d (acquiring GPU lock)",
                    song_id,
                    attempt + 1,
                    self.max_retries,
                )
                async with _GPU_LOCK:
                    log.info("GPU lock acquired for WhisperX %s", song_id)
                    ret_dict = await asyncio.wait_for(
                        asyncio.to_thread(
                            _run_align_sync,
                            audio_path,
                            lrc_content,
                            self.model_name,
                            self.device,
                        ),
                        timeout=self.timeout_sec,
                    )

                aligned_lrc = ret_dict["aligned_lrc"]
                word_level = ret_dict["word_level"]

                # Write to cache
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / "aligned.lrc").write_text(aligned_lrc)

                log.info("WhisperX alignment complete for %s", song_id)
                return AlignmentResult(
                    aligned_lrc=aligned_lrc,
                    source="whisperx_align",
                    word_level=word_level,
                )

            except asyncio.TimeoutError as exc:
                last_exc = TemporaryError(
                    f"WhisperX timed out after {self.timeout_sec}s for {song_id}"
                )
                log.warning("WhisperX timeout for %s attempt %d", song_id, attempt + 1)

            except Exception as exc:
                classified = _classify_exception(exc)
                if isinstance(classified, PermanentError):
                    log.error("WhisperX permanent error for %s: %s", song_id, exc)
                    raise classified from exc
                last_exc = classified
                log.warning(
                    "WhisperX temp error for %s attempt %d: %s",
                    song_id,
                    attempt + 1,
                    exc,
                )
                # Flush CUDA cache on OOM
                _try_flush_cuda_cache()

            if attempt < self.max_retries - 1:
                delay = delays[attempt] if attempt < len(delays) else delays[-1]
                log.info("Retrying WhisperX %s in %ds", song_id, delay)
                await asyncio.sleep(delay)

        # All retries exhausted → fallback to line-level distribution
        log.warning(
            "WhisperX failed after %d attempts for %s, using line-level fallback",
            self.max_retries,
            song_id,
        )
        fallback_lrc = _line_level_fallback(lrc_lines)
        return AlignmentResult(
            aligned_lrc=fallback_lrc,
            source=None,
            word_level=False,
        )


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _try_flush_cuda_cache() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            log.debug("CUDA cache flushed after WhisperX error")
    except Exception:
        pass
