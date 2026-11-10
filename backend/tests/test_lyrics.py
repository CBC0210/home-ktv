"""Tests for backend/src/ktv_pipeline/pipeline/lyrics.py — M1-T4."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

from ktv_pipeline.pipeline.lyrics import (
    LyricsResult,
    LyricsError,
    TempLyricsError,
    PermLyricsError,
    fetch_netease,
    fetch_amll,
    fetch_qq,
    fetch_syncedlyrics,
    fetch_lyrics,
    _has_timing_markers,
    _strip_html,
    _parse_plaintext,
    _build_result,
    _classify_http_error,
)


# ---------------------------------------------------------------------------
# Helpers — unit tests
# ---------------------------------------------------------------------------

class TestHasTimingMarkers:
    def test_timing_tag_minsec(self):
        assert _has_timing_markers("[00:10.00]hello")

    def test_timing_tag_with_ms(self):
        assert _has_timing_markers("[01:23.456]world")

    def test_no_timing_returns_false(self):
        assert _has_timing_markers("hello world") is False
        assert _has_timing_markers("") is False

    def test_plain_lrc_line_no_tag(self):
        assert _has_timing_markers("hello\nworld\nfoo bar") is False


class TestStripHtml:
    def test_br_to_newline(self):
        assert _strip_html("hello<br/>world") == "hello\nworld"
        assert _strip_html("foo<br>bar") == "foo\nbar"

    def test_strips_tags(self):
        assert _strip_html("<b>bold</b> normal") == "bold normal"

    def test_multiple_brs_collapsed(self):
        assert _strip_html("a<br/><br/><br/>b") == "a\n\nb"

    def test_whitespace_trimmed(self):
        assert _strip_html("  hello  ").strip() == "hello"


class TestParsePlaintext:
    def test_filters_short_lines(self):
        text = "hello\nthis is a longer line here\nworld"
        result = _parse_plaintext(text, min_len=10)
        assert "hello" not in result  # too short
        assert "world" not in result   # too short
        assert "this is a longer line here" in result

    def test_preserves_unicode(self):
        text = "這是一句很長的普通歌詞文字內容\n短的不保留"
        result = _parse_plaintext(text, min_len=15)
        assert "這是一句很長的普通歌詞文字內容" in result


class TestClassifyHttpError:
    def test_404_is_perm(self):
        assert isinstance(_classify_http_error(404), PermLyricsError)

    def test_500_is_temp(self):
        assert isinstance(_classify_http_error(500), TempLyricsError)

    def test_502_is_temp(self):
        assert isinstance(_classify_http_error(502), TempLyricsError)

    def test_400_is_perm(self):
        assert isinstance(_classify_http_error(400), PermLyricsError)


class TestBuildResult:
    def test_synced_when_has_timing(self):
        result = _build_result("[00:10.00]hello", source="netease", quality="official_line")
        assert result.lyrics_type == "synced"
        assert result.source == "netease"
        assert result.quality == "official_line"

    def test_plain_when_no_timing(self):
        result = _build_result("hello world plain text", source="mojim", quality="plaintext")
        assert result.lyrics_type == "plain"
        assert result.source == "mojim"

    def test_to_dict_format(self):
        result = _build_result("[00:10]foo", source="qq", quality="official_line")
        d = result.to_dict()
        assert d["lyrics_type"] == "synced"
        assert d["lrc"] == "[00:10]foo"
        assert d["source"] == "qq"


class TestLyricsResultDataclass:
    def test_default_fields(self):
        r = LyricsResult(lyrics_type="synced", lrc="[00:10]hello", source="netease", quality="official_line")
        assert r.lyrics_type == "synced"
        assert r.lrc == "[00:10]hello"
        assert r.source == "netease"
        assert r.quality == "official_line"

    def test_to_dict_roundtrip(self):
        r = LyricsResult(lyrics_type="plain", lrc="plain text", source="mojim", quality="plaintext")
        d = r.to_dict()
        assert d["lyrics_type"] == "plain"
        assert d["lrc"] == "plain text"
        assert d["source"] == "mojim"

    def test_none_source(self):
        r = LyricsResult(lyrics_type="plain", lrc="", source=None, quality="none")
        assert r.source is None
        assert r.quality == "none"


# ---------------------------------------------------------------------------
# fetch_netease — mocked HTTP
# ---------------------------------------------------------------------------

class TestFetchNetease:
    @pytest.mark.asyncio
    async def test_returns_result_on_success(self):
        search_json = {"result": {"songs": [{"id": 12345, "name": "晴天", "artist": "周杰伦"}]}}
        lrc_json = {"lrc": {"lyric": "[00:10.00]晴天\n[00:20.00]快给我一点"}}

        async def mock_get(url, **kwargs):
            m = MagicMock()
            if "search" in url:
                m.json = MagicMock(return_value=search_json)
                m.status_code = 200
            else:
                m.json = MagicMock(return_value=lrc_json)
                m.status_code = 200
            return m

        with patch("ktv_pipeline.pipeline.lyrics._http_lock", AsyncMock()):
            with patch("ktv_pipeline.pipeline.lyrics.httpx.AsyncClient") as MockClient:
                instance = MockClient.return_value.__aenter__.return_value
                instance.get = AsyncMock(side_effect=mock_get)

                result = await fetch_netease("晴天", "周杰伦")

        assert result is not None
        assert result.lyrics_type == "synced"
        assert result.source == "netease"
        assert "[00:10.00]" in result.lrc

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self):
        async def mock_get(url, **kwargs):
            m = MagicMock()
            m.json = MagicMock(return_value={"result": {"songs": []}})
            m.status_code = 200
            return m

        with patch("ktv_pipeline.pipeline.lyrics._http_lock", AsyncMock()):
            with patch("ktv_pipeline.pipeline.lyrics.httpx.AsyncClient") as MockClient:
                instance = MockClient.return_value.__aenter__.return_value
                instance.get = AsyncMock(side_effect=lambda url, **kw: mock_get(url, **kw))
                result = await fetch_netease("nonexistent song xyz", "Unknown")
        assert result is None


# ---------------------------------------------------------------------------
# fetch_lyrics — fallback chain integration
# ---------------------------------------------------------------------------

class TestFetchLyricsManager:
    @pytest.mark.asyncio
    async def test_all_sources_fail_returns_quality_none(self):
        """When every source fails, return quality=none."""
        synced = [(name, AsyncMock(return_value=None)) for name in ("amll_ttml", "netease", "qq", "syncedlyrics")]
        plaintext = [(name, AsyncMock(return_value=None)) for name in ("mojim", "kkbox", "genius")]
        with patch("ktv_pipeline.pipeline.lyrics._SYNCED_SOURCES", synced), \
             patch("ktv_pipeline.pipeline.lyrics._PLAINTEXT_SOURCES", plaintext):
            result = await fetch_lyrics("nonexistent", "unknown")

        assert result.quality == "none"
        assert result.source is None
        assert result.lrc == ""
        assert result.lyrics_type == "plain"

    @pytest.mark.asyncio
    async def test_returns_first_successful_synced_source(self):
        success_result = LyricsResult(lyrics_type="synced", lrc="[00:10]foo", source="netease", quality="official_line")
        synced = [
            ("amll_ttml", AsyncMock(return_value=None)),
            ("netease", AsyncMock(return_value=success_result)),
            ("qq", AsyncMock(return_value=None)),
            ("syncedlyrics", AsyncMock(return_value=None)),
        ]
        with patch("ktv_pipeline.pipeline.lyrics._SYNCED_SOURCES", synced), \
             patch("ktv_pipeline.pipeline.lyrics._PLAINTEXT_SOURCES", []):
            result = await fetch_lyrics("test", "artist")

        assert result.source == "netease"
        assert result.lyrics_type == "synced"

    @pytest.mark.asyncio
    async def test_falls_back_to_plaintext_after_synced_fail(self):
        plain_result = LyricsResult(lyrics_type="plain", lrc="plain lyrics text", source="mojim", quality="plaintext")
        synced = [(name, AsyncMock(return_value=None)) for name in ("amll_ttml", "netease", "qq", "syncedlyrics")]
        plaintext = [
            ("mojim", AsyncMock(return_value=plain_result)),
            ("kkbox", AsyncMock(return_value=None)),
            ("genius", AsyncMock(return_value=None)),
        ]
        with patch("ktv_pipeline.pipeline.lyrics._SYNCED_SOURCES", synced), \
             patch("ktv_pipeline.pipeline.lyrics._PLAINTEXT_SOURCES", plaintext):
            result = await fetch_lyrics("test", "artist")

        assert result.source == "mojim"
        assert result.lyrics_type == "plain"
        assert result.quality == "plaintext"

    @pytest.mark.asyncio
    async def test_skips_perm_errors_and_continues(self):
        """A PermLyricsError from one source should not stop the chain."""
        plain_result = LyricsResult(lyrics_type="plain", lrc="genius lyrics", source="genius", quality="plaintext")
        synced = [
            ("amll_ttml", AsyncMock(return_value=None)),
            ("netease", AsyncMock(side_effect=PermLyricsError("not found"))),
            ("qq", AsyncMock(return_value=None)),
            ("syncedlyrics", AsyncMock(return_value=None)),
        ]
        plaintext = [
            ("mojim", AsyncMock(return_value=None)),
            ("kkbox", AsyncMock(return_value=None)),
            ("genius", AsyncMock(return_value=plain_result)),
        ]
        with patch("ktv_pipeline.pipeline.lyrics._SYNCED_SOURCES", synced), \
             patch("ktv_pipeline.pipeline.lyrics._PLAINTEXT_SOURCES", plaintext):
            result = await fetch_lyrics("test", "artist")

        assert result.source == "genius"

    @pytest.mark.asyncio
    async def test_amll_takes_priority_over_netease(self):
        """AMLL is source 1 in the chain."""
        amll_result = LyricsResult(lyrics_type="synced", lrc="[00:10]amll timed", source="amll_ttml", quality="official_word")
        netease_result = LyricsResult(lyrics_type="synced", lrc="[00:10]netease lrc", source="netease", quality="official_line")
        fetch_amll_mock = AsyncMock(return_value=amll_result)
        fetch_netease_mock = AsyncMock(return_value=netease_result)
        synced = [("amll_ttml", fetch_amll_mock), ("netease", fetch_netease_mock)]
        with patch("ktv_pipeline.pipeline.lyrics._SYNCED_SOURCES", synced), \
             patch("ktv_pipeline.pipeline.lyrics._PLAINTEXT_SOURCES", []):
            result = await fetch_lyrics("test", "artist")

        assert result.source == "amll_ttml"
        fetch_netease_mock.assert_not_awaited()

    def test_source_chain_order(self):
        """The real fallback order: official word-level first, plaintext last."""
        from ktv_pipeline.pipeline import lyrics
        assert [name for name, _ in lyrics._SYNCED_SOURCES] == ["amll_ttml", "netease", "qq", "syncedlyrics"]
        assert [name for name, _ in lyrics._PLAINTEXT_SOURCES] == ["mojim", "kkbox", "genius"]


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------

class TestExceptionHierarchy:
    def test_temp_is_base(self):
        assert issubclass(TempLyricsError, LyricsError)

    def test_perm_is_base(self):
        assert issubclass(PermLyricsError, LyricsError)

    def test_not_same_class(self):
        assert TempLyricsError is not LyricsError
        assert PermLyricsError is not LyricsError
