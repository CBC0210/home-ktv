import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).with_name("migrate_demucs_wav_to_opus.py")
SPEC = importlib.util.spec_from_file_location("wav_migration", SCRIPT)
assert SPEC and SPEC.loader
migration = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = migration
SPEC.loader.exec_module(migration)


def make_pair(directory: Path, stem: str, opus_duration: float = 1.0) -> tuple[Path, Path]:
    directory.mkdir(parents=True)
    wav = directory / f"{stem}.wav"
    opus = directory / f"{stem}.opus"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "pcm_s16le", str(wav)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={opus_duration}", "-c:a", "libopus", str(opus)], check=True)
    return wav, opus


def run_tool(cache_root: Path, manifest: Path, *args: str) -> dict:
    completed = subprocess.run([sys.executable, str(SCRIPT), "--cache-root", str(cache_root), "--manifest", str(manifest), *args], text=True, capture_output=True, check=True)
    return json.loads(completed.stdout)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_dry_run_keeps_wav_and_records_verified_candidate(tmp_path: Path):
    root = tmp_path / "demucs"
    wav, opus = make_pair(root / "song-a", "vocals")
    manifest = tmp_path / "audit.jsonl"

    summary = run_tool(root, manifest)

    rows = [json.loads(line) for line in manifest.read_text().splitlines()]
    verified = next(row for row in rows if row["wav_path"] == str(wav))
    assert summary["would_delete"] == 1
    assert wav.exists() and opus.exists()
    assert verified["eligible"] is True
    assert verified["action"] == "would_delete"


def test_apply_deletes_only_verified_wav_and_not_other_files(tmp_path: Path):
    root = tmp_path / "demucs"
    wav, opus = make_pair(root / "song-a", "no_vocals")
    untouched = root / "song-a" / "notes.txt"
    untouched.write_text("keep me")
    manifest = tmp_path / "audit.jsonl"

    summary = run_tool(root, manifest, "--apply")

    assert summary["deleted"] == 1
    assert not wav.exists()
    assert opus.exists()
    assert untouched.read_text() == "keep me"


def test_duration_mismatch_is_kept(tmp_path: Path):
    root = tmp_path / "demucs"
    wav, _ = make_pair(root / "song-a", "vocals", opus_duration=3.0)
    manifest = tmp_path / "audit.jsonl"

    summary = run_tool(root, manifest)

    rows = [json.loads(line) for line in manifest.read_text().splitlines()]
    row = next(row for row in rows if row["wav_path"] == str(wav))
    assert summary["would_delete"] == 0
    assert wav.exists()
    assert row["reason"] == "WAV and Opus durations differ beyond tolerance"
