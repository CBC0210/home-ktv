"""MEDIA_ROOT_DIR：影音檔（media/、cache/）可放在 DATA_DIR 以外的位置。"""
from pathlib import Path

import pytest

from ktv_pipeline.config import Settings


def _settings(tmp_path: Path, **kw) -> Settings:
    return Settings(_env_file=None, data_dir=tmp_path / "data", **kw)


def test_defaults_to_data_dir(tmp_path):
    s = _settings(tmp_path)
    assert s.media_root == tmp_path / "data"
    s.check_media_root()  # unset → never refuses


def test_blank_value_means_unset(tmp_path):
    s = _settings(tmp_path, media_root_dir="  ")
    assert s.media_root_dir is None
    assert s.media_root == tmp_path / "data"


def test_separate_media_root(tmp_path):
    media = tmp_path / "hdd"
    media.mkdir()
    s = _settings(tmp_path, media_root_dir=str(media))
    assert s.media_root == media
    assert s.db_path == tmp_path / "data" / "ktv.db"   # DB stays in DATA_DIR
    assert s.log_dir == tmp_path / "data" / "logs"
    s.check_media_root()


def test_missing_media_root_refuses_to_start(tmp_path):
    s = _settings(tmp_path, media_root_dir=str(tmp_path / "not-mounted"))
    with pytest.raises(RuntimeError, match="MEDIA_ROOT_DIR"):
        s.check_media_root()
    assert not (tmp_path / "not-mounted").exists()  # must not be created


def test_streaming_reads_from_media_root(tmp_path, monkeypatch):
    from api import streaming

    media = tmp_path / "hdd"
    monkeypatch.setattr(streaming.settings, "media_root_dir", media)
    assert streaming._song_media_dir("abc") == media / "media" / "abc"
    assert streaming._song_video_path("abc") == media / "cache" / "abc" / "video.mp4"
