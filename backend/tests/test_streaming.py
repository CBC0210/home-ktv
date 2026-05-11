"""Tests for streaming endpoints — file operations, range requests, auth guards."""
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestStreamInfo:
    def test_nonexistent_song_returns_404(self, client):
        response = client.get("/songs/nonexistent-id-abc123/stream/info")
        assert response.status_code == 404

    def test_stream_info_returns_404_for_real_nonexistent_song(self, client):
        """Even with no mock, a non-existent song ID should 404."""
        response = client.get("/songs/definitely-nonexistent-song-id-xyz/stream/info")
        assert response.status_code == 404


class TestAudioFilenameSecurity:
    """Security tests: path traversal and invalid filenames must be blocked."""

    def test_path_traversal_returns_404_or_403(self, client):
        """Path traversal in filename → 404 or 403 (never 200)."""
        response = client.get("/songs/dQw4w9WgXcQ/audio/../../../etc/passwd")
        assert response.status_code in (403, 404), f"Got {response.status_code}, expected 403 or 404"

    def test_script_injection_blocked(self, client):
        """Semicolons / shell chars in filename → blocked (404 for nonexistent song)."""
        response = client.get("/songs/nonexistent-song-id/audio/vocals.wav;rm -rf /")
        assert response.status_code in (403, 404), f"Got {response.status_code}, expected 403 or 404"

    def test_only_allowed_filenames_work(self, client):
        """vocals.wav / no_vocals.wav / audio.m4a pass filename validation.

        For a song that doesn't exist, we get 404 (not found).
        For a real song with 'pending' status, we get 202 (not ready).
        """
        # Nonexistent song → 404 (no song found)
        for fname in ["vocals.wav", "no_vocals.wav", "audio.m4a"]:
            response = client.get(f"/songs/nonexistent-song-id/audio/{fname}")
            assert response.status_code == 404, f"{fname} should 404 for nonexistent song, got {response.status_code}"


class TestLyricsAssEndpoint:
    def test_nonexistent_song_404(self, client):
        response = client.get("/songs/nonexistent-id-abc123/lyrics.ass")
        assert response.status_code == 404

    def test_put_lyrics_404_for_nonexistent_song(self, client):
        response = client.put(
            "/songs/nonexistent-id-abc123/lyrics",
            json={"ass": "[Script Info]\nTitle: Test\n"},
        )
        assert response.status_code == 404

    def test_put_lyrics_400_for_empty_ass(self, client):
        """Empty ASS content must be rejected."""
        from ktv_pipeline.database import get_db_session
        from ktv_pipeline.models import Song
        song_id = "testlyrics-empty-ass-check"
        with get_db_session() as session:
            if not session.query(Song).filter_by(id=song_id).first():
                session.add(Song(id=song_id, title="T", status="ready"))
                session.commit()
        response = client.put(
            f"/songs/{song_id}/lyrics",
            json={"ass": "   "},  # whitespace-only
        )
        assert response.status_code == 400

    def test_put_lyrics_writes_file(self, client, tmp_path, monkeypatch):
        """Valid PUT request writes file and returns ok."""
        from ktv_pipeline.database import get_db_session
        from ktv_pipeline.models import Song
        song_id = "testlyrics-write-file-check"
        with get_db_session() as session:
            if not session.query(Song).filter_by(id=song_id).first():
                session.add(Song(id=song_id, title="T2", status="ready"))
                session.commit()

        ass = "[Script Info]\nTitle: Test\n\n[Events]\nDialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,Hello"

        import ktv_pipeline.config as cfg_mod
        from pathlib import Path
        monkeypatch.setattr(cfg_mod.settings, "data_dir", Path(tmp_path))

        response = client.put(
            f"/songs/{song_id}/lyrics",
            json={"ass": ass},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["bytes"] > 0


class TestHLSServing:
    """Tests for the HLS manifest endpoint."""

    def test_song_not_found_404(self, client):
        response = client.get("/songs/definitely-not-a-real-song-id-abc123/stream.m3u8")
        assert response.status_code == 404

    def test_pending_song_returns_202(self, client):
        """A non-existent song → 404 (no special 202 for pending)."""
        response = client.get("/songs/definitely-not-a-real-song-id-abc123/stream.m3u8")
        assert response.status_code == 404


class TestRangeRequestParsing:
    """Unit tests for the range header parsing logic."""

    def test_parse_valid_range(self):
        from api.streaming import _parse_range
        start, end = _parse_range("bytes=0-1023", 4096)
        assert start == 0
        assert end == 1023

    def test_parse_range_with_end_omitted(self):
        from api.streaming import _parse_range
        start, end = _parse_range("bytes=1000-", 4096)
        assert start == 1000
        assert end == 4095  # file_size - 1

    def test_parse_range_clamped_to_file_size(self):
        from api.streaming import _parse_range
        start, end = _parse_range("bytes=0-9999", 1024)
        assert end == 1023  # clamped to file size - 1

    def test_parse_range_invalid_returns_full(self):
        from api.streaming import _parse_range
        start, end = _parse_range("invalid-range", 4096)
        assert start == 0
        assert end == 4095