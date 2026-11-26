"""清除 Cache 只能刪播放用不到的檔案（#5）。"""
import os
from pathlib import Path

from ktv_pipeline.cache_cleanup import reclaim_cache
from ktv_pipeline.playback_assets import playback_assets_ready


def _write(path: Path, data: bytes = b"x" * 100) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _stems(root: Path, sid: str) -> None:
    for stem in ("vocals", "no_vocals"):
        _write(root / "cache" / "demucs" / sid / f"{stem}.opus")


def test_keeps_every_playback_asset_of_ready_songs(tmp_path):
    # only-cache: the cache original is the only video → must stay
    _write(tmp_path / "cache" / "only-cache" / "video.mp4")
    _write(tmp_path / "cache" / "only-cache" / "info.json", b"{}")
    _stems(tmp_path, "only-cache")
    # linked: media copy is a hardlink of the original → freeing it gains nothing
    orig = _write(tmp_path / "cache" / "linked" / "video.mp4")
    (tmp_path / "media" / "linked").mkdir(parents=True)
    os.link(orig, tmp_path / "media" / "linked" / "video.mp4")
    _stems(tmp_path, "linked")

    r = reclaim_cache(tmp_path, {"only-cache": "ready", "linked": "ready"})

    assert r.files_removed == 0
    assert (tmp_path / "cache" / "only-cache" / "video.mp4").exists()
    assert (tmp_path / "cache" / "linked" / "video.mp4").exists()
    for sid in ("only-cache", "linked"):
        assert (tmp_path / "cache" / "demucs" / sid / "vocals.opus").exists()


def test_removes_transcoded_original_leftovers_and_orphans(tmp_path):
    _write(tmp_path / "cache" / "big" / "video.mp4", b"o" * 1000)
    _write(tmp_path / "media" / "big" / "video.mp4", b"t" * 10)
    _write(tmp_path / "cache" / "big" / "video.f399.mp4.part", b"p" * 50)
    _stems(tmp_path, "big")
    _write(tmp_path / "cache" / "gone" / "video.mp4")
    _stems(tmp_path, "gone")

    r = reclaim_cache(tmp_path, {"big": "ready"})

    assert not (tmp_path / "cache" / "big" / "video.mp4").exists()
    assert not (tmp_path / "cache" / "big" / "video.f399.mp4.part").exists()
    assert not (tmp_path / "cache" / "gone").exists()
    assert not (tmp_path / "cache" / "demucs" / "gone").exists()
    assert (tmp_path / "cache" / "demucs" / "big" / "vocals.opus").exists()
    assert r.bytes_freed == 1000 + 50 + 100 + 2 * 100


def test_songs_in_progress_are_untouched(tmp_path):
    _write(tmp_path / "cache" / "busy" / "video.mp4.part")
    _write(tmp_path / "cache" / "busy" / "video.mp4")
    _write(tmp_path / "media" / "busy" / "video.mp4", b"t")

    r = reclaim_cache(tmp_path, {"busy": "processing"})

    assert r.files_removed == 0
    assert (tmp_path / "cache" / "busy" / "video.mp4.part").exists()


def test_ready_song_still_plays_after_cleanup(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from ktv_pipeline import playback_assets

    monkeypatch.setattr(playback_assets.settings, "media_root_dir", tmp_path)
    _write(tmp_path / "cache" / "s1" / "video.mp4", b"o" * 1000)
    _write(tmp_path / "media" / "s1" / "video.mp4", b"t" * 10)
    _stems(tmp_path, "s1")
    song = SimpleNamespace(id="s1", extra_metadata={})
    assert playback_assets_ready(song)

    reclaim_cache(tmp_path, {"s1": "ready"})

    assert playback_assets_ready(song)
