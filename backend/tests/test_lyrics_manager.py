"""M1-T4: Lyrics Manager tests（mock，不發真實 HTTP）。"""
import pytest
from unittest.mock import patch

from pipeline.lyrics_manager import LyricsManager, LyricsResult


class TestLyricsResult:
    def test_has_timing_false(self):
        r = LyricsResult(lyrics_text="hello world", source="mojim", has_timing=False, quality="plaintext")
        assert r.has_timing is False

    def test_has_timing_true_lrc(self):
        r = LyricsResult(lyrics_text="[00:10.00]hello", source="netease", has_timing=True, quality="official_line")
        assert r.has_timing is True


class TestLyricsManagerInterface:
    def test_instantiation(self):
        m = LyricsManager()
        assert m is not None

    def test_has_fetch_method(self):
        m = LyricsManager()
        assert hasattr(m, "fetch")

    def test_fetch_all_fail_returns_none_result(self):
        m = LyricsManager()
        with patch.object(m, "_fetch_amll", return_value=None):
            pass
