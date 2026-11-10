#!/usr/bin/env python3
"""Safely retire verified Demucs WAV copies once their Opus twins are usable.

The default is a dry run.  A WAV is eligible only when it is exactly
``<cache-root>/<song_id>/vocals.wav`` or ``no_vocals.wav``, its adjacent Opus
file has passed ffprobe and a full ffmpeg decode, and their durations agree.

Examples:
    python3 scripts/migrate_demucs_wav_to_opus.py --manifest /tmp/demucs.jsonl
    python3 scripts/migrate_demucs_wav_to_opus.py --manifest /tmp/demucs.jsonl --apply --workers 1

The JSONL manifest is an audit record.  Review the dry-run manifest before
using --apply.  The tool never scans recursively and never deletes an Opus
file or any filename other than the two explicit WAV targets.
"""
import argparse
import concurrent.futures
import json
import math
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any


DEFAULT_CACHE_ROOT = Path("/data/ktv/cache/demucs")
TARGET_FILENAMES = ("vocals.wav", "no_vocals.wav")
DEFAULT_WORKERS = 1
MAX_WORKERS = 4
DEFAULT_TIMEOUT_SECONDS = 120


def safe_regular_file(path: Path, expected_parent: Path) -> bool:
    """Return True only for a non-symlink regular file directly in its song dir."""
    try:
        return path.parent == expected_parent and path.is_file() and not path.is_symlink()
    except OSError:
        return False


def file_snapshot(path: Path) -> dict[str, int]:
    stat = path.stat(follow_symlinks=False)
    return {"device": stat.st_dev, "inode": stat.st_ino, "size_bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def run_command(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)


def probe_audio(path: Path, timeout: int) -> dict[str, Any]:
    """Run ffprobe and return compact, manifest-safe facts or a failure reason."""
    command = [
        "ffprobe", "-v", "error", "-show_entries",
        "format=format_name,duration:stream=codec_type,codec_name,duration",
        "-of", "json", "--", str(path),
    ]
    try:
        completed = run_command(command, timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": f"ffprobe failed: {exc}"}
    if completed.returncode != 0:
        return {"ok": False, "error": "ffprobe returned non-zero", "stderr": completed.stderr[-500:]}
    try:
        data = json.loads(completed.stdout)
        audio = next(stream for stream in data.get("streams", []) if stream.get("codec_type") == "audio")
        duration = float(data.get("format", {}).get("duration", "nan"))
    except (ValueError, TypeError, StopIteration, json.JSONDecodeError) as exc:
        return {"ok": False, "error": f"ffprobe output invalid: {exc}"}
    if not math.isfinite(duration) or duration <= 0:
        return {"ok": False, "error": "ffprobe duration is not positive and finite"}
    return {
        "ok": True,
        "duration_seconds": duration,
        "format_name": data.get("format", {}).get("format_name"),
        "codec_name": audio.get("codec_name"),
    }


def decode_audio(path: Path, timeout: int) -> dict[str, Any]:
    """Fully decode the first audio stream; ffmpeg's null muxer consumes all frames."""
    command = ["ffmpeg", "-v", "error", "-xerror", "-nostdin", "-threads", "1", "-i", str(path), "-map", "0:a:0", "-f", "null", "-"]
    try:
        completed = run_command(command, timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": f"ffmpeg decode failed: {exc}"}
    if completed.returncode != 0 or completed.stderr.strip():
        return {"ok": False, "error": "ffmpeg decode returned errors", "stderr": completed.stderr[-500:]}
    return {"ok": True}


def duration_tolerance(wav_duration: float, opus_duration: float) -> float:
    """Allow only a small Opus encoder padding margin, never lost seconds."""
    return 0.15


def inspect_candidate(song_dir: Path, filename: str, timeout: int) -> dict[str, Any]:
    wav = song_dir / filename
    opus = wav.with_suffix(".opus")
    record: dict[str, Any] = {
        "song_id": song_dir.name,
        "wav_path": str(wav),
        "opus_path": str(opus),
        "mode": "dry_run",
        "action": "keep",
        "eligible": False,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    if not safe_regular_file(wav, song_dir):
        record["reason"] = "WAV is missing, not a regular file, or is a symlink"
        return record
    if not safe_regular_file(opus, song_dir):
        record["reason"] = "adjacent Opus is missing, not a regular file, or is a symlink"
        return record
    try:
        record["wav_snapshot"] = file_snapshot(wav)
        record["opus_snapshot"] = file_snapshot(opus)
    except OSError as exc:
        record["reason"] = f"cannot stat candidate: {exc}"
        return record

    wav_probe = probe_audio(wav, timeout)
    opus_probe = probe_audio(opus, timeout)
    record["wav_probe"] = wav_probe
    record["opus_probe"] = opus_probe
    if not wav_probe.get("ok") or not opus_probe.get("ok"):
        record["reason"] = "ffprobe validation failed"
        return record
    if "wav" not in str(wav_probe.get("format_name", "")).split(","):
        record["reason"] = "WAV target did not probe as WAV"
        return record
    if opus_probe.get("codec_name") != "opus":
        record["reason"] = "Opus target did not probe as codec opus"
        return record

    record["wav_decode"] = decode_audio(wav, timeout)
    record["opus_decode"] = decode_audio(opus, timeout)
    if not record["wav_decode"].get("ok") or not record["opus_decode"].get("ok"):
        record["reason"] = "full ffmpeg decode validation failed"
        return record

    difference = abs(wav_probe["duration_seconds"] - opus_probe["duration_seconds"])
    tolerance = duration_tolerance(wav_probe["duration_seconds"], opus_probe["duration_seconds"])
    record["duration_difference_seconds"] = difference
    record["duration_tolerance_seconds"] = tolerance
    if difference > tolerance:
        record["reason"] = "WAV and Opus durations differ beyond tolerance"
        return record
    record.update(eligible=True, action="would_delete", reason="verified adjacent Opus replacement")
    return record


def candidates(cache_root: Path) -> list[tuple[Path, str]]:
    """List only exact filenames in immediate, real song directories."""
    try:
        children = sorted(cache_root.iterdir())
    except OSError:
        return []
    return [
        (child, filename)
        for child in children
        if child.is_dir() and not child.is_symlink()
        for filename in TARGET_FILENAMES
    ]


def unchanged_and_safe(path: Path, parent: Path, snapshot: dict[str, int]) -> bool:
    try:
        return safe_regular_file(path, parent) and file_snapshot(path) == snapshot
    except OSError:
        return False


def apply_deletion(record: dict[str, Any]) -> None:
    wav = Path(record["wav_path"])
    opus = Path(record["opus_path"])
    song_dir = wav.parent
    if not unchanged_and_safe(wav, song_dir, record["wav_snapshot"]):
        record.update(action="keep", eligible=False, reason="WAV changed after validation; not deleted")
        return
    if not unchanged_and_safe(opus, song_dir, record["opus_snapshot"]):
        record.update(action="keep", eligible=False, reason="Opus changed after validation; not deleted")
        return
    try:
        wav.unlink()
    except OSError as exc:
        record.update(action="keep", eligible=False, reason=f"WAV deletion failed: {exc}")
        return
    record.update(action="deleted", mode="apply")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT, help=f"Demucs cache root (default: {DEFAULT_CACHE_ROOT})")
    parser.add_argument("--manifest", type=Path, required=True, help="JSONL audit output; must not be inside --cache-root")
    parser.add_argument("--resume-manifest", type=Path, help="reuse successful validations only when both file snapshots are unchanged")
    parser.add_argument("--apply", action="store_true", help="delete verified WAV files (default: dry-run)")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help=f"parallel validation workers, 1-{MAX_WORKERS} (default: {DEFAULT_WORKERS})")
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS, help="per ffprobe/ffmpeg command timeout")
    args = parser.parse_args()
    if not 1 <= args.workers <= MAX_WORKERS:
        parser.error(f"--workers must be between 1 and {MAX_WORKERS}")
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    try:
        if args.manifest.resolve().is_relative_to(args.cache_root.resolve()):
            parser.error("--manifest must be outside --cache-root")
    except OSError:
        parser.error("cannot resolve --cache-root or --manifest")
    return args


def main() -> int:
    args = parse_args()
    cache_root = args.cache_root
    if not cache_root.is_dir() or cache_root.is_symlink():
        print(f"Refusing to scan unsafe or missing cache root: {cache_root}", file=sys.stderr)
        return 2
    if args.manifest.exists() and args.manifest.is_symlink():
        print(f"Refusing to write manifest through symlink: {args.manifest}", file=sys.stderr)
        return 2
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    work = candidates(cache_root)
    verified = {}
    if args.resume_manifest:
        if args.resume_manifest.resolve() == args.manifest.resolve():
            print("Input and output manifests must differ", file=sys.stderr)
            return 2
        for line in args.resume_manifest.read_text().splitlines():
            row = json.loads(line)
            if (row.get("eligible") and row.get("wav_decode", {}).get("ok")
                    and row.get("opus_decode", {}).get("ok")
                    and row.get("duration_difference_seconds", 999) <= 0.15):
                verified[row["wav_path"]] = row

    def inspect_or_reuse(song_dir, filename):
        wav = song_dir / filename
        opus = wav.with_suffix(".opus")
        row = verified.get(str(wav))
        if (row and row.get("opus_path") == str(opus)
                and unchanged_and_safe(wav, song_dir, row.get("wav_snapshot", {}))
                and unchanged_and_safe(opus, song_dir, row.get("opus_snapshot", {}))):
            row = dict(row)
            row.update(action="would_delete", eligible=True, reused_validation=True)
            return row
        return inspect_candidate(song_dir, filename, args.timeout_seconds)
    mode = "apply" if args.apply else "dry-run"
    counts = {"would_delete": 0, "deleted": 0, "keep": 0}
    with args.manifest.open("w", encoding="utf-8") as manifest:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = [executor.submit(inspect_or_reuse, song_dir, filename) for song_dir, filename in work]
            for future in concurrent.futures.as_completed(futures):
                record = future.result()
                record["mode"] = mode
                if args.apply and record["eligible"]:
                    apply_deletion(record)
                counts[record["action"]] += 1
                manifest.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                manifest.flush()
    print(json.dumps({"mode": mode, "cache_root": str(cache_root), "manifest": str(args.manifest), "candidates": len(work), **counts}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
