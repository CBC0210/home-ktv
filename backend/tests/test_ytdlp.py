"""Tests for YtDlpWrapper.

All tests use mocks — no real YouTube downloads.
"""

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock

import pytest
import yt_dlp.utils

from ktv_pipeline.pipeline.ytdlp import (
    YtDlpWrapper,
    DownloadResult,
    YtDlpError,
    TempDownloadError,
    PermDownloadError,
    _classify_ytdlp_error,
    _bgutil_server_home,
    _extract_youtube_id,
    _js_runtimes,
)


# ---------------------------------------------------------------------------
# Unit tests — pure logic, no I/O
# ---------------------------------------------------------------------------


class TestExtractYoutubeId:
    def test_standard_watch_url(self):
        assert _extract_youtube_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_short_url(self):
        assert _extract_youtube_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_shorts_url(self):
        assert _extract_youtube_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_embed_url(self):
        assert _extract_youtube_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    def test_no_match_returns_none(self):
        assert _extract_youtube_id("https://example.com/notayoutube") is None


class TestClassifyError:
    def _make_exc(self, msg: str) -> yt_dlp.utils.DownloadError:
        e = yt_dlp.utils.DownloadError(msg)
        return e

    def test_private_video_is_perm(self):
        exc = self._make_exc("ERROR: Private video. Sign in if you've been granted access to this video")
        result = _classify_ytdlp_error(exc)
        assert isinstance(result, PermDownloadError)

    def test_video_unavailable_is_perm(self):
        exc = self._make_exc("ERROR: Video unavailable")
        result = _classify_ytdlp_error(exc)
        assert isinstance(result, PermDownloadError)

    def test_age_restricted_is_perm(self):
        exc = self._make_exc("ERROR: This video is age-restricted")
        result = _classify_ytdlp_error(exc)
        assert isinstance(result, PermDownloadError)

    def test_geo_blocked_is_perm(self):
        exc = self._make_exc("ERROR: The uploader has not made this video available in your country")
        result = _classify_ytdlp_error(exc)
        assert isinstance(result, PermDownloadError)

    def test_network_error_is_temp(self):
        exc = self._make_exc("ERROR: <urlopen error [Errno 110] Connection timed out>")
        result = _classify_ytdlp_error(exc)
        assert isinstance(result, TempDownloadError)

    def test_http_error_is_temp(self):
        exc = self._make_exc("ERROR: HTTP Error 503: Service Unavailable")
        result = _classify_ytdlp_error(exc)
        assert isinstance(result, TempDownloadError)

    def test_removed_video_is_perm(self):
        exc = self._make_exc("ERROR: This video has been removed by the user")
        result = _classify_ytdlp_error(exc)
        assert isinstance(result, PermDownloadError)


# ---------------------------------------------------------------------------
# YtDlpWrapper — instantiation and interface
# ---------------------------------------------------------------------------


class TestYtDlpWrapperInterface:
    def test_instantiation_with_defaults(self, tmp_path):
        wrapper = YtDlpWrapper(cache_dir=tmp_path)
        assert wrapper.cache_dir == tmp_path
        assert wrapper.max_retries == 3
        assert wrapper.timeout_sec == 300

    def test_instantiation_with_custom_values(self, tmp_path):
        wrapper = YtDlpWrapper(cache_dir=tmp_path, timeout_sec=60, max_retries=1)
        assert wrapper.timeout_sec == 60
        assert wrapper.max_retries == 1

    def test_has_download_method(self, tmp_path):
        wrapper = YtDlpWrapper(cache_dir=tmp_path)
        assert callable(wrapper.download)


class TestJsRuntimeConfiguration:
    @staticmethod
    def _executable(path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\n")
        path.chmod(0o755)
        return path

    def test_environment_override_has_priority(self, tmp_path, monkeypatch):
        deno = tmp_path / "deno"
        self._executable(deno)
        monkeypatch.setenv("KTV_YTDLP_DENO_PATH", str(deno))
        monkeypatch.setenv("KTV_YTDLP_NODE_PATH", str(tmp_path / "missing-node"))
        monkeypatch.setattr("shutil.which", lambda name: str(tmp_path / f"path-{name}"))
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))

        assert _js_runtimes() == {"deno": {"path": str(deno)}}

    def test_path_has_priority_over_home_fallback(self, tmp_path, monkeypatch):
        path_node = self._executable(tmp_path / "path/node")
        self._executable(tmp_path / "home/.nvm/versions/node/v99.0.0/bin/node")
        monkeypatch.delenv("KTV_YTDLP_DENO_PATH", raising=False)
        monkeypatch.delenv("KTV_YTDLP_NODE_PATH", raising=False)
        monkeypatch.setattr("shutil.which", lambda name: str(path_node) if name == "node" else None)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))

        assert _js_runtimes() == {"node": {"path": str(path_node)}}

    def test_home_fallback_uses_deno_and_latest_nvm_node(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        deno = self._executable(home / ".deno/bin/deno")
        self._executable(home / ".nvm/versions/node/v22.9.0/bin/node")
        node = self._executable(home / ".nvm/versions/node/v24.15.0/bin/node")
        monkeypatch.delenv("KTV_YTDLP_DENO_PATH", raising=False)
        monkeypatch.delenv("KTV_YTDLP_NODE_PATH", raising=False)
        monkeypatch.setattr("shutil.which", lambda name: None)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

        assert _js_runtimes() == {
            "deno": {"path": str(deno)},
            "node": {"path": str(node)},
        }

    def test_ydl_options_pass_configured_runtimes(self, tmp_path, monkeypatch):
        deno = tmp_path / "deno"
        deno.write_text("#!/bin/sh\n")
        deno.chmod(0o755)
        monkeypatch.setenv("KTV_YTDLP_DENO_PATH", str(deno))
        monkeypatch.setenv("KTV_YTDLP_NODE_PATH", str(tmp_path / "missing-node"))
        monkeypatch.setattr("shutil.which", lambda name: None)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))

        opts = YtDlpWrapper(cache_dir=tmp_path)._ydl_opts(str(tmp_path / "video.%(ext)s"))
        assert opts["js_runtimes"] == {"deno": {"path": str(deno)}}

    def test_ydl_options_use_mweb_client_for_po_token_provider(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KTV_BGUTIL_SERVER_HOME", str(tmp_path / "provider/server"))
        opts = YtDlpWrapper(cache_dir=tmp_path)._ydl_opts(str(tmp_path / "video.%(ext)s"))
        assert opts["extractor_args"]["youtube"] == {"player_client": ["mweb"]}
        assert opts["extractor_args"]["youtubepot-bgutilscript"]["server_home"] == [
            str(tmp_path / "provider/server")
        ]

    def test_bgutil_home_fallback(self, tmp_path, monkeypatch):
        monkeypatch.delenv("KTV_BGUTIL_SERVER_HOME", raising=False)
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

        assert _bgutil_server_home() == (
            tmp_path / ".local/share/home-ktv/bgutil-ytdlp-pot-provider/server"
        )


# ---------------------------------------------------------------------------
# YtDlpWrapper — async behaviour with mocks
# ---------------------------------------------------------------------------


FAKE_INFO = {
    "id": "dQw4w9WgXcQ",
    "title": "Rick Astley - Never Gonna Give You Up",
    "uploader": "Rick Astley",
    "channel": "RickAstleyVEVO",
    "duration": 212,
    "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg",
    "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
}

URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
YT_ID = "dQw4w9WgXcQ"


@pytest.fixture()
def wrapper(tmp_path):
    return YtDlpWrapper(cache_dir=tmp_path, timeout_sec=10, max_retries=3)


def _make_song_dir(tmp_path: Path, yt_id: str = YT_ID) -> Path:
    d = tmp_path / yt_id
    d.mkdir(parents=True, exist_ok=True)
    return d


class TestDownloadSuccess:
    async def test_download_returns_result(self, wrapper, tmp_path):
        song_dir = _make_song_dir(tmp_path)

        def fake_download(url, output_template):
            # Simulate yt-dlp creating the file
            video_file = song_dir / "video.mp4"
            video_file.write_bytes(b"fake-video-data")
            return FAKE_INFO

        with patch.object(wrapper, "_download_sync", side_effect=fake_download):
            result = await wrapper.download(URL)

        assert isinstance(result, DownloadResult)
        assert result.youtube_id == YT_ID
        assert result.title == FAKE_INFO["title"]
        assert result.artist == FAKE_INFO["uploader"]
        assert result.duration_sec == FAKE_INFO["duration"]
        assert result.thumbnail_url == FAKE_INFO["thumbnail"]
        assert result.video_path == song_dir / "video.mp4"

    async def test_info_json_saved_after_download(self, wrapper, tmp_path):
        song_dir = _make_song_dir(tmp_path)

        def fake_download(url, output_template):
            (song_dir / "video.mp4").write_bytes(b"x")
            return FAKE_INFO

        with patch.object(wrapper, "_download_sync", side_effect=fake_download):
            await wrapper.download(URL)

        info_path = song_dir / "info.json"
        assert info_path.exists()
        saved = json.loads(info_path.read_text())
        assert saved["title"] == FAKE_INFO["title"]


class TestCacheHit:
    async def test_skips_download_if_cached(self, wrapper, tmp_path):
        song_dir = _make_song_dir(tmp_path)
        video_path = song_dir / "video.mp4"
        video_path.write_bytes(b"cached-video")
        (song_dir / "info.json").write_text(json.dumps(FAKE_INFO))

        with patch.object(wrapper, "_download_sync") as mock_dl:
            result = await wrapper.download(URL)
            mock_dl.assert_not_called()

        assert result.youtube_id == YT_ID
        assert result.title == FAKE_INFO["title"]


class TestRetryBehaviour:
    async def test_retries_on_temp_error_then_succeeds(self, wrapper, tmp_path):
        song_dir = _make_song_dir(tmp_path)
        call_count = 0

        def fake_download(url, output_template):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise yt_dlp.utils.DownloadError("HTTP Error 503")
            # Third attempt succeeds
            (song_dir / "video.mp4").write_bytes(b"x")
            return FAKE_INFO

        with patch.object(wrapper, "_download_sync", side_effect=fake_download):
            with patch("asyncio.sleep"):  # skip actual sleep
                result = await wrapper.download(URL)

        assert call_count == 3
        assert result.youtube_id == YT_ID

    async def test_raises_temp_error_after_all_retries(self, wrapper, tmp_path):
        _make_song_dir(tmp_path)

        with patch.object(
            wrapper,
            "_download_sync",
            side_effect=yt_dlp.utils.DownloadError("HTTP Error 503"),
        ):
            with patch("asyncio.sleep"):
                with pytest.raises(TempDownloadError):
                    await wrapper.download(URL)

    async def test_does_not_retry_perm_error(self, wrapper, tmp_path):
        _make_song_dir(tmp_path)
        call_count = 0

        def fake_download(url, output_template):
            nonlocal call_count
            call_count += 1
            raise yt_dlp.utils.DownloadError("Video unavailable")

        with patch.object(wrapper, "_download_sync", side_effect=fake_download):
            with pytest.raises(PermDownloadError):
                await wrapper.download(URL)

        assert call_count == 1  # no retries for perm errors

    async def test_raises_temp_error_on_timeout(self, wrapper, tmp_path):
        _make_song_dir(tmp_path)
        wrapper.max_retries = 1

        async def slow_thread(*args, **kwargs):
            raise asyncio.TimeoutError()

        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()):
            with pytest.raises(TempDownloadError, match="timed out"):
                await wrapper.download(URL)


class TestErrorHierarchy:
    def test_temp_is_ytdlp_error(self):
        assert issubclass(TempDownloadError, YtDlpError)

    def test_perm_is_ytdlp_error(self):
        assert issubclass(PermDownloadError, YtDlpError)

    def test_ytdlp_error_is_exception(self):
        assert issubclass(YtDlpError, Exception)
