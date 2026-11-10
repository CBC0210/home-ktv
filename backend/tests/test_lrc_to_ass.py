"""Tests for LRC → ASS conversion.

Unit tests cover pure functions — no real file I/O, no GPU.
"""

import re
from pathlib import Path

import pytest

from ktv_pipeline.pipeline.lrc_to_ass import (
    # Class + result + config
    LrcToAssConverter,
    LrcToAssResult,
    AssConfig,
    # Module-level function
    convert_lrc_to_ass,
    # Parsing / helpers
    parse_lrc_tokens,
    fmt_ass_time,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def cfg() -> AssConfig:
    return AssConfig(
        play_res_x=1920,
        play_res_y=1080,
        font_name="黑体",
        font_size=72,
        bold=True,
    )


@pytest.fixture()
def converter(tmp_path: Path) -> LrcToAssConverter:
    return LrcToAssConverter(
        cache_dir=tmp_path / "ass_cache",
        config=AssConfig(),
    )


# ---------------------------------------------------------------------------
# LRC samples
# ---------------------------------------------------------------------------

LRC_LINE_EN = (
    "[00:12.00]Hello world\n"
    "[00:15.50]This is a test\n"
    "[00:20.00]Goodbye"
)

LRC_LINE_CN = (
    "[00:10.00]你好世界\n"
    "[00:15.00]這是一首測試歌\n"
)

# Word-level English: separate line per word, gaps > 1500 ms so each is its own group
# (actual _LINE_GAP_MS = 1500, tokens < gap get grouped together)
LRC_WORD_EN = (
    "[00:12.00]Hello\n"
    "[00:14.00]world\n"
    "[00:17.00]This\n"
    "[00:18.50]is\n"
    "[00:20.00]a\n"
    "[00:22.00]test\n"
)

# Word-level Chinese: separate line per character
LRC_WORD_CN = (
    "[00:10.00]你\n"
    "[00:10.30]好\n"
    "[00:15.00]世\n"
    "[00:15.30]界\n"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count_dialogue(ass: str) -> tuple[int, int]:
    """Return dialogue counts grouped by the current and legacy styles."""
    defaults = [l for l in ass.splitlines() if "Dialogue:" in l and ",Default," in l]
    previews = [l for l in ass.splitlines() if "Dialogue:" in l and ",Preview," in l]
    return len(defaults), len(previews)


# ---------------------------------------------------------------------------
# Tests — parse_lrc_tokens
# ---------------------------------------------------------------------------


class TestParseLrcTokens:
    def test_basic_line_level(self):
        tokens = parse_lrc_tokens(LRC_LINE_EN)
        assert len(tokens) == 3
        assert tokens[0].text == "Hello world"
        assert tokens[1].text == "This is a test"
        assert tokens[2].text == "Goodbye"

    def test_timestamps_in_ms(self):
        tokens = parse_lrc_tokens(LRC_LINE_EN)
        assert tokens[0].ms == 12_000.0
        assert tokens[1].ms == 15_500.0
        assert tokens[2].ms == 20_000.0

    def test_chinese(self):
        tokens = parse_lrc_tokens(LRC_LINE_CN)
        assert len(tokens) == 2
        assert tokens[0].text == "你好世界"

    def test_empty_text_skipped(self):
        tokens = parse_lrc_tokens("[00:12.00]Hello\n[00:15.00]\n[00:20.00]Bye")
        assert len(tokens) == 2

    def test_no_milliseconds(self):
        tokens = parse_lrc_tokens("[00:12]Hello")
        assert len(tokens) == 1
        assert tokens[0].ms == 12_000.0

    def test_fractional_ms(self):
        tokens = parse_lrc_tokens("[00:12.5]Hello")  # 0.5 sec = 500ms
        assert tokens[0].ms == 12_500.0

    def test_no_timestamps(self):
        tokens = parse_lrc_tokens("Just some text\nNo timestamps here")
        assert tokens == []


# ---------------------------------------------------------------------------
# Tests — fmt_ass_time
# ---------------------------------------------------------------------------


class TestFmtAssTime:
    def test_zero(self):
        assert fmt_ass_time(0) == "0:00:00.00"

    def test_basic(self):
        assert fmt_ass_time(12_000) == "0:00:12.00"

    def test_with_fraction(self):
        assert fmt_ass_time(12_500) == "0:00:12.50"

    def test_hours(self):
        assert fmt_ass_time(3_600_000) == "1:00:00.00"

    def test_large_minutes(self):
        assert fmt_ass_time(330_000) == "0:05:30.00"


# ---------------------------------------------------------------------------
# Tests — convert_lrc_to_ass (header + structure)
# ---------------------------------------------------------------------------


class TestConvertLrcToAss:
    def test_script_info_present(self):
        ass = convert_lrc_to_ass(LRC_LINE_EN, song_id="test1")
        assert "[Script Info]" in ass
        assert "ScriptType: v4.00+" in ass

    def test_play_res(self):
        ass = convert_lrc_to_ass(LRC_LINE_EN, song_id="test2")
        assert "PlayResX: 1920" in ass
        assert "PlayResY: 1080" in ass

    def test_styles_present(self):
        ass = convert_lrc_to_ass(LRC_LINE_EN, song_id="test3")
        assert "[V4+ Styles]" in ass
        assert "Style: Default" in ass
        assert "Style: Preview" not in ass

    def test_events_present(self):
        ass = convert_lrc_to_ass(LRC_LINE_EN, song_id="test4")
        assert "[Events]" in ass
        assert "Format: Layer, Start, End, Style, Name" in ass

    def test_line_level_uses_rolling_window(self):
        """Each timing window shows the current line and nearby context."""
        ass = convert_lrc_to_ass(LRC_LINE_EN, song_id="test5l")
        defaults, previews = _count_dialogue(ass)
        assert defaults == 8
        assert previews == 0

    def test_line_level_text_appears(self):
        """Line-level ASS should contain the lyric texts (possibly with \\kf tags)."""
        ass = convert_lrc_to_ass(LRC_LINE_EN, song_id="test6")
        # Texts appear in ASS (possibly split by \kf tags or space)
        assert "Hello" in ass
        assert "world" in ass
        assert "This is a test" in ass
        assert "Goodbye" in ass

    def test_chinese(self):
        ass = convert_lrc_to_ass(LRC_LINE_CN, song_id="test7")
        assert "你好世界" in ass
        assert "這是一首測試歌" in ass

    def test_empty_lrc_raises(self):
        """Empty LRC raises ConversionError (no silent empty output)."""
        with pytest.raises(Exception):  # ConversionError
            convert_lrc_to_ass("", song_id="test_empty")

    def test_no_timestamps_raises(self):
        """LRC with no valid timestamps raises ConversionError."""
        with pytest.raises(Exception):
            convert_lrc_to_ass("Just some text\nNo timestamps", song_id="test_no_ts")

    def test_ass_timestamps_valid_format(self):
        """All ASS timestamps in Dialogue lines match H:MM:SS.CC."""
        ass = convert_lrc_to_ass(LRC_LINE_EN, song_id="test_ts")
        timestamps = re.findall(r"Dialogue: \d+,(\d+:\d{2}:\d{2}\.\d{2}),", ass)
        assert len(timestamps) >= 3
        for ts in timestamps:
            assert re.match(r"\d+:\d{2}:\d{2}\.\d{2}", ts), f"Bad ASS timestamp: {ts}"

    def test_custom_config(self):
        """Custom AssConfig is reflected in output."""
        custom = AssConfig(
            play_res_x=1280,
            play_res_y=720,
            font_name="Arial",
            font_size=48,
        )
        ass = convert_lrc_to_ass(LRC_LINE_EN, song_id="test_custom", config=custom)
        assert "PlayResX: 1280" in ass
        assert "PlayResY: 720" in ass
        assert "Arial" in ass
        assert "48" in ass

    def test_word_level_true_uses_static_text(self):
        """Unreliable word timestamps do not produce karaoke fill tags."""
        ass = convert_lrc_to_ass(LRC_WORD_EN, word_level=True, song_id="test_wl")
        assert r"{\k" not in ass
        assert "Hello" in ass

    def test_word_level_true_fade_in_tag(self):
        """word_level=True includes fade-in tag."""
        ass = convert_lrc_to_ass(LRC_WORD_EN, word_level=True, song_id="test_fade")
        assert r"\fad(100,0)" in ass

    def test_preview_lines_for_next_song(self):
        """Preview lines should contain the NEXT line's full text."""
        ass = convert_lrc_to_ass(LRC_LINE_EN, song_id="test_prev")
        # Preview 1 should show "This is a test" (next line after Hello world)
        # Preview 2 should show "Goodbye" (next line after This is a test)
        assert "This is a test" in ass
        assert "Goodbye" in ass

    def test_dialogue_count_word_level(self):
        """Word-level groups are rendered in rolling context windows."""
        ass = convert_lrc_to_ass(LRC_WORD_EN, word_level=True, song_id="test5w")
        defaults, previews = _count_dialogue(ass)
        # Six groups, each showing up to previous/current/next/next2.
        assert defaults == 20
        assert previews == 0


# ---------------------------------------------------------------------------
# Tests — LrcToAssConverter class
# ---------------------------------------------------------------------------


class TestLrcToAssConverter:
    def test_convert_returns_result(self, converter):
        result = converter.convert("song1", LRC_LINE_EN)
        assert isinstance(result, LrcToAssResult)
        assert result.ass_content
        assert result.ass_path is not None
        assert not result.from_cache

    def test_convert_writes_cache(self, converter, tmp_path):
        result = converter.convert("song2", LRC_LINE_EN)
        assert result.ass_path is not None
        assert result.ass_path.exists()
        assert result.ass_path.read_text() == result.ass_content

    def test_idempotent_cached(self, converter):
        r1 = converter.convert("song3", LRC_LINE_EN)
        r2 = converter.convert("song3", LRC_LINE_EN)
        assert r2.from_cache is True
        assert r2.ass_content == r1.ass_content

    def test_overwrite_true_reconverts(self, converter):
        r1 = converter.convert("song4", LRC_LINE_EN)
        r2 = converter.convert("song4", LRC_WORD_EN, overwrite=True)
        assert r2.from_cache is False
        # Different content (different word grouping)
        assert r2.ass_content != r1.ass_content

    def test_overwrite_false_returns_cache(self, converter):
        """Second call with overwrite=False returns cached content."""
        converter.convert("song5", LRC_LINE_EN)
        r2 = converter.convert("song5", LRC_WORD_EN)
        assert r2.from_cache is True

    def test_no_cache_dir(self, tmp_path):
        conv = LrcToAssConverter(cache_dir=None)
        result = conv.convert("nocache", LRC_LINE_EN)
        assert result.ass_path is None
        assert result.ass_content

    def test_different_song_ids_different_cache(self, converter):
        """Different song IDs get different cache paths."""
        r1 = converter.convert("songA", LRC_LINE_EN)
        r2 = converter.convert("songB", LRC_LINE_CN)
        assert r1.ass_path != r2.ass_path
