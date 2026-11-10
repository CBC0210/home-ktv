#!/usr/bin/env python3
"""Purge pytest artifacts from the production KTV database.

Historically pytest could load a deployment DATA_DIR and write its fixtures
straight into the live database — "Test Song N" / "HLS Test Song"
entries then showed up in the 曲庫. tests/conftest.py now isolates tests in a
temp DATA_DIR, so pollution stops recurring; this script removes what already
leaked.

Usage:
    DATA_DIR=/path/to/data python3 scripts/cleanup_test_data.py
    python3 scripts/cleanup_test_data.py --db /path/to/ktv.db --apply

Only matches explicit test fixture patterns (lb-song-*, smoketester-*,
test-* rooms, ...). Real songs have 11-char YouTube / BV… Bilibili ids and
are never touched.
"""
import argparse
import os
from pathlib import Path
import sqlite3
import sys

# Fixture patterns from backend/tests/ — keep in sync when new test id
# schemes appear. (SQL LIKE patterns.)
SONG_WHERE = """
    id LIKE 'lb-song-%'
    OR id IN ('song1', 'song2', 'song3', 'advsong1')
    OR id LIKE 'testly%'
    OR title LIKE '%Test Song%'
    OR title IN ('Adv Song', 'Song One', 'Song Two', 'Song Three')
"""

ROOM_WHERE = """
    id LIKE 'test-%'
    OR id LIKE 'e2e-%'
    OR id LIKE 'smoke%'
    OR id LIKE 'lb-room-%'
    OR id LIKE 'lb-hist-room-%'
"""

GUEST_WHERE = """
    nickname LIKE 'smoketester-%'
    OR nickname LIKE 'lb-guest%'
    OR nickname IN ('ws_test', 'test_skip', 'test_rmt', 'test-cli', 'test',
                    't_admchk', 'WSTester', 'AdvTester', 'SmokeGuest',
                    'Alice', 'Bob', 'Carol')
    OR id = 'ws-test-guest'
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, help="database path (default: $DATA_DIR/ktv.db)")
    ap.add_argument("--apply", action="store_true", help="delete (default: dry-run)")
    args = ap.parse_args()
    if args.db is None:
        data_dir = os.environ.get("DATA_DIR")
        if not data_dir:
            ap.error("set DATA_DIR or pass --db; refusing to guess a deployment database")
        args.db = Path(data_dir) / "ktv.db"

    db = sqlite3.connect(args.db)
    c = db.cursor()

    song_ids = [r[0] for r in c.execute(f"SELECT id FROM songs WHERE {SONG_WHERE}")]
    room_ids = [r[0] for r in c.execute(f"SELECT id FROM rooms WHERE {ROOM_WHERE}")]
    guest_ids = [r[0] for r in c.execute(f"SELECT id FROM guests WHERE {GUEST_WHERE}")]

    # (table, fk column, matching ids) — children first, then the parents.
    plan = []
    for col, ids in (("song_id", song_ids), ("room_id", room_ids), ("guest_id", guest_ids)):
        if not ids:
            continue
        plan.append(("queue_items", col, ids))
        plan.append(("play_history", col, ids))
        if col in ("song_id", "guest_id"):
            plan.append(("favorites", col, ids))
    for table, ids in (("songs", song_ids), ("rooms", room_ids), ("guests", guest_ids)):
        if ids:
            plan.append((table, "id", ids))

    print(f"songs to delete:  {len(song_ids)}")
    print(f"rooms to delete:  {len(room_ids)}")
    print(f"guests to delete: {len(guest_ids)}")

    total = 0
    for table, col, ids in plan:
        marks = ",".join("?" * len(ids))
        if args.apply:
            cur = c.execute(f"DELETE FROM {table} WHERE {col} IN ({marks})", ids)
            n = cur.rowcount
        else:
            n = c.execute(f"SELECT COUNT(*) FROM {table} WHERE {col} IN ({marks})", ids).fetchone()[0]
        total += n
        verb = "deleted" if args.apply else "would delete"
        print(f"  {verb} {n:4d} rows from {table} (by {col})")

    if args.apply:
        db.commit()
        c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        print(f"\nDeleted {total} rows total. Done.")
    else:
        print(f"\nDry-run: {total} rows would be deleted. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
