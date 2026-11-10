"""Streaming responses must not retain a database connection."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from api import streaming


@pytest.mark.asyncio
async def test_audio_closes_db_before_returning_stream(tmp_path, monkeypatch):
    song_id = "connection-lifetime"
    audio = tmp_path / "cache" / "demucs" / song_id / "vocals.opus"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"OggS" + b"audio" * 20)
    state = {"open": False}
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = SimpleNamespace(status="ready")

    @contextmanager
    def db():
        state["open"] = True
        try:
            yield session
        finally:
            state["open"] = False

    monkeypatch.setattr(streaming, "get_db_session", db)
    monkeypatch.setattr(streaming.settings, "data_dir", tmp_path)
    request = MagicMock(headers={"range": "bytes=0-3"})

    response = await streaming.serve_audio_file(song_id, "vocals.wav", request)

    assert state["open"] is False
    assert response.status_code == 206
    chunks = [chunk async for chunk in response.body_iterator]
    assert b"".join(chunks) == b"OggS"
    assert state["open"] is False
