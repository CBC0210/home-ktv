"""LRC → ASS subtitle converter with KTV karaoke tags.

Converts a timed LRC string into an ASS (Advanced SubStation Alpha) subtitle
file with \\kf karaoke tags and dual-line display (current + next preview).

CLAUDE.md §7.5 requirements implemented here:
  - \\k tags in centiseconds
  - Dual-line display: current line + next-line preview
  - Fade-in 100ms per event
  - Default style: 黑体 bold, white pre-highlight, golden-yellow post-highlight,
    dark outline

Caching: LrcToAssConverter checks for an existing lyrics.ass before converting.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

log = __import__("logging").getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LINE_GAP_MS = 1500      # gap > this between consecutive word tokens → new line
_LAST_LINE_EXTRA_MS = 5000  # extra ms added after the last line
_WORD_LEVEL_TEXT_LEN = 4    # token text shorter than this → treat as word-level


# ---------------------------------------------------------------------------
# AssConfig
# ---------------------------------------------------------------------------


@dataclass
class AssConfig:
    """Customisable ASS style parameters.

    ASS colour format: &HAABBGGRR (AA=alpha, BB=blue, GG=green, RR=red).
    AA=00 → fully opaque; AA=FF → fully transparent.
    """

    play_res_x: int = 1920
    play_res_y: int = 1080
    font_name: str = "黑体"

    # Main (current-line) style — large, lower-center
    font_size: int = 88
    primary_color: str = "&H0000CCFF"   # golden yellow — post-highlight (sung)
    secondary_color: str = "&H00FFFFFF"  # white — pre-highlight (not yet sung)
    outline_color: str = "&H00000000"   # black
    back_color: str = "&H00000000"
    bold: bool = True
    outline: float = 3.5
    shadow: float = 1.5
    margin_v: int = 250                  # px from bottom — lower-center area

    # Preview1 (next line) style
    font_size_preview: int = 68
    preview_color: str = "&H80FFFFFF"   # 50%-opaque white

    # Preview2 (line after next) style
    font_size_preview2: int = 56
    preview2_color: str = "&HB0FFFFFF"  # 31%-opaque white, more dimmed

    # Vertical gap between lines (px added to margin_v for each preview level)
    preview_gap: int = 115
    preview2_gap: int = 95

    # Fade-in per subtitle event
    fade_in_ms: int = 100


# ---------------------------------------------------------------------------
# Internal data model
# ---------------------------------------------------------------------------


@dataclass
class _Token:
    ms: float
    text: str


@dataclass
class _Line:
    start_ms: float
    end_ms: float
    tokens: List[_Token]

    @property
    def full_text(self) -> str:
        sep = "" if _is_cjk(self.tokens) else " "
        return sep.join(t.text for t in self.tokens)


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------


@dataclass
class LrcToAssResult:
    """Output of LRC → ASS conversion.

    Attributes
    ----------
    ass_content:
        Complete ASS file as a string.
    ass_path:
        Path to the written .ass file, or ``None`` if caching is disabled.
    from_cache:
        ``True`` when an existing cached file was returned.
    """

    ass_content: str
    ass_path: Optional[Path]
    from_cache: bool


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ConversionError(Exception):
    """Raised when LRC content is irrecoverably invalid."""


# ---------------------------------------------------------------------------
# LrcToAssConverter (idempotent, file-caching)
# ---------------------------------------------------------------------------


class LrcToAssConverter:
    """LRC → ASS converter with optional file-based caching.

    Parameters
    ----------
    cache_dir:
        Root directory for cached .ass files.  Subdirectories are created as
        ``<cache_dir>/<song_id>/lyrics.ass``.  If ``None``, caching is disabled.
    config:
        Style/layout configuration.  Defaults to ``AssConfig()``.
    max_retries:
        Kept for API parity with other pipeline wrappers; conversion is local
        and deterministic so retries are not used.
    """

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        config: Optional[AssConfig] = None,
        max_retries: int = 2,
    ):
        self.cache_dir = cache_dir
        self.config = config or AssConfig()
        self.max_retries = max_retries

    def convert(
        self,
        song_id: str,
        lrc_content: str,
        *,
        word_level: Optional[bool] = None,
        total_duration_sec: Optional[float] = None,
        overwrite: bool = False,
    ) -> LrcToAssResult:
        """Convert *lrc_content* to ASS.

        Parameters
        ----------
        song_id:
            Identifier used for cache path and logging.
        lrc_content:
            Raw LRC string (word-level or line-level).
        word_level:
            ``True`` → group tokens by gap detection (WhisperX output).
            ``False`` → treat each entry as a full line.
            ``None`` (default) → auto-detect.
        total_duration_sec:
            Audio duration; used to extend the last line's end timestamp.
        overwrite:
            If ``False`` and a cached .ass already exists, return it immediately.

        Returns
        -------
        LrcToAssResult
        """
        out_path: Optional[Path] = None
        if self.cache_dir:
            out_path = self.cache_dir / song_id / "lyrics.ass"
            if not overwrite and out_path.exists() and out_path.stat().st_size > 0:
                log.info("LRC→ASS cache hit for %s", song_id)
                return LrcToAssResult(
                    ass_content=out_path.read_text(),
                    ass_path=out_path,
                    from_cache=True,
                )

        ass_content = convert_lrc_to_ass(
            lrc_content,
            word_level=word_level,
            total_duration_sec=total_duration_sec,
            song_id=song_id,
            config=self.config,
        )

        if out_path:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(ass_content)
            log.info("Wrote ASS for %s → %s", song_id, out_path)

        return LrcToAssResult(
            ass_content=ass_content,
            ass_path=out_path,
            from_cache=False,
        )


# ---------------------------------------------------------------------------
# Module-level conversion function
# ---------------------------------------------------------------------------


def convert_lrc_to_ass(
    lrc: str,
    *,
    word_level: Optional[bool] = None,
    total_duration_sec: Optional[float] = None,
    song_id: str = "unknown",
    config: Optional[AssConfig] = None,
) -> str:
    """Convert a timed LRC string to a complete ASS file.

    Parameters
    ----------
    lrc:
        Raw LRC content.
    word_level:
        ``True`` → each entry is one word/char.
        ``False`` → each entry is a full line.
        ``None`` → auto-detect from entry text length.
    total_duration_sec:
        Audio duration in seconds (improves last-line timing).
    song_id:
        Used for logging only.
    config:
        Style override.

    Returns
    -------
    str
        Complete ASS file, or a header-only file if LRC has no parseable lines.
    """
    cfg = config or AssConfig()
    tokens = parse_lrc_tokens(lrc)

    if not tokens:
        raise ConversionError(
            f"[{song_id}] LRC is empty or contains no valid timestamp lines"
        )

    if word_level is None:
        word_level = _auto_detect_word_level(tokens)

    total_ms: Optional[float] = total_duration_sec * 1000 if total_duration_sec else None

    if word_level:
        lines = _group_word_level(tokens, total_ms)
    else:
        lines = _expand_line_level(tokens, total_ms)

    if not lines:
        raise ConversionError(
            f"[{song_id}] LRC produced no lyric lines after grouping"
        )

    return _render_header(cfg) + _render_events(lines, cfg)


# ---------------------------------------------------------------------------
# Grouping helpers
# ---------------------------------------------------------------------------


def _group_word_level(
    tokens: List[_Token], total_ms: Optional[float], gap_ms: int = _LINE_GAP_MS
) -> List[_Line]:
    """Group word/char tokens into subtitle lines via gap detection."""
    lines: List[_Line] = []
    current: List[_Token] = []

    for tok in tokens:
        if current and tok.ms - current[-1].ms >= gap_ms:
            lines.append(_Line(
                start_ms=current[0].ms,
                end_ms=tok.ms,
                tokens=list(current),
            ))
            current = []
        current.append(tok)

    if current:
        end_ms = (
            total_ms
            if total_ms is not None
            else current[-1].ms + _LAST_LINE_EXTRA_MS
        )
        lines.append(_Line(start_ms=current[0].ms, end_ms=end_ms, tokens=current))

    return lines


def _expand_line_level(
    tokens: List[_Token], total_ms: Optional[float]
) -> List[_Line]:
    """Treat each token as a full lyric line; split into words/chars."""
    lines: List[_Line] = []
    for i, tok in enumerate(tokens):
        start_ms = tok.ms
        end_ms = (
            tokens[i + 1].ms
            if i + 1 < len(tokens)
            else (total_ms if total_ms is not None else tok.ms + _LAST_LINE_EXTRA_MS)
        )

        is_cjk = bool(re.search(r"[一-鿿]", tok.text))
        units = list(tok.text) if is_cjk else tok.text.split()
        if not units:
            continue

        unit_ms = (end_ms - start_ms) / len(units)
        sub_tokens = [
            _Token(ms=start_ms + j * unit_ms, text=u) for j, u in enumerate(units)
        ]
        lines.append(_Line(start_ms=start_ms, end_ms=end_ms, tokens=sub_tokens))

    return lines


def _auto_detect_word_level(tokens: List[_Token]) -> bool:
    """Return True when most tokens contain exactly one word (or one CJK char)."""
    if not tokens:
        return False
    single_unit = sum(1 for t in tokens if len(t.text.split()) == 1)
    return single_unit / len(tokens) >= 0.7


# ---------------------------------------------------------------------------
# ASS rendering
# ---------------------------------------------------------------------------


def _render_header(cfg: AssConfig) -> str:
    bold_flag = "-1" if cfg.bold else "0"
    p1_v = cfg.margin_v + cfg.preview_gap
    p2_v = p1_v + cfg.preview2_gap
    return (
        f"[Script Info]\n"
        f"ScriptType: v4.00+\n"
        f"PlayResX: {cfg.play_res_x}\n"
        f"PlayResY: {cfg.play_res_y}\n"
        f"ScaledBorderAndShadow: yes\n"
        f"WrapStyle: 0\n"
        f"\n"
        f"[V4+ Styles]\n"
        f"Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{cfg.font_name},{cfg.font_size},{cfg.primary_color},{cfg.secondary_color},{cfg.outline_color},{cfg.back_color},{bold_flag},0,0,0,100,100,0,0,1,{cfg.outline},{cfg.shadow},2,40,40,{cfg.margin_v},1\n"
        f"Style: Preview,{cfg.font_name},{cfg.font_size_preview},{cfg.preview_color},{cfg.preview_color},{cfg.outline_color},{cfg.back_color},0,0,0,0,100,100,0,0,1,2,0,2,40,40,{p1_v},1\n"
        f"Style: Preview2,{cfg.font_name},{cfg.font_size_preview2},{cfg.preview2_color},{cfg.preview2_color},{cfg.outline_color},{cfg.back_color},0,0,0,0,100,100,0,0,1,2,0,2,40,40,{p2_v},1\n"
        f"\n"
        f"[Events]\n"
        f"Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )


def _render_events(lines: List[_Line], cfg: AssConfig) -> str:
    fade = f"{{\\fad({cfg.fade_in_ms},0)}}"
    parts: List[str] = []

    for i, line in enumerate(lines):
        t_start = fmt_ass_time(line.start_ms)
        t_end = fmt_ass_time(line.end_ms)
        k_text = _build_k_text(line)

        parts.append(
            f"Dialogue: 0,{t_start},{t_end},Default,,0,0,0,,{fade}{k_text}"
        )

        if i + 1 < len(lines):
            preview_text = lines[i + 1].full_text
            parts.append(
                f"Dialogue: 0,{t_start},{t_end},Preview,,0,0,0,,{fade}{preview_text}"
            )

        if i + 2 < len(lines):
            preview2_text = lines[i + 2].full_text
            parts.append(
                f"Dialogue: 0,{t_start},{t_end},Preview2,,0,0,0,,{fade}{preview2_text}"
            )

    return "\n".join(parts) + "\n"


def _build_k_text(line: _Line) -> str:
    """Build ``{\\kf<N>}text`` karaoke string for a subtitle line."""
    cjk = _is_cjk(line.tokens)
    parts: List[str] = []
    for i, tok in enumerate(line.tokens):
        next_ms = line.tokens[i + 1].ms if i + 1 < len(line.tokens) else line.end_ms
        duration_cs = max(round((next_ms - tok.ms) / 10), 1)
        sep = "" if cjk or i + 1 == len(line.tokens) else " "
        parts.append(f"{{\\kf{duration_cs}}}{tok.text}{sep}")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_lrc_tokens(lrc: str) -> List[_Token]:
    """Parse ``[mm:ss.xx]text`` entries from an LRC string.

    Entries with empty text are silently skipped.
    """
    pattern = re.compile(r"\[(\d{1,2}):(\d{2})(?:\.(\d{1,3}))?\](.*)")
    tokens: List[_Token] = []
    for line in lrc.splitlines():
        m = pattern.match(line.strip())
        if not m:
            continue
        mins = int(m.group(1))
        secs = int(m.group(2))
        frac = (m.group(3) or "0").ljust(3, "0")
        ms = float((mins * 60 + secs) * 1000 + int(frac))
        text = m.group(4).strip()
        if text:
            tokens.append(_Token(ms=ms, text=text))
    return tokens


def fmt_ass_time(ms: float) -> str:
    """Format milliseconds as ASS timestamp ``H:MM:SS.CC``."""
    total_cs = round(ms / 10)
    cs = total_cs % 100
    total_s = total_cs // 100
    secs = total_s % 60
    total_m = total_s // 60
    mins = total_m % 60
    hours = total_m // 60
    return f"{hours}:{mins:02d}:{secs:02d}.{cs:02d}"


def _is_cjk(tokens: List[_Token]) -> bool:
    return any(re.search(r"[一-鿿]", t.text) for t in tokens)
