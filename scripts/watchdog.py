#!/usr/bin/env python3
"""
Home KTV Watchdog
詳見 CLAUDE.md §21.11

由 systemd timer 每 10 分鐘呼叫一次。
功能：
1. 重置 stale pipeline tasks（last_heartbeat 超時）
2. 標記 stuck songs
3. 檢查磁碟空間
4. 檢查 GPU 健康
5. 檢查 cloudflared 服務
6. 通知 OpenClaw（透過寫入 alerts 檔案）

⚠️ 這是 M0-T7 的骨架，實際功能待 M2 後實作。
"""
import json
import shutil
import subprocess
import sys
import sqlite3
from datetime import datetime, timedelta
import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
DB_PATH = DATA_DIR / "ktv.db"
ALERTS_FILE = DATA_DIR / "watchdog-alerts.jsonl"

STALE_HEARTBEAT_MIN = 15      # pipeline stage 超時
DISK_CRITICAL_PCT = 5
DISK_WARN_PCT = 10
DISK_INFO_PCT = 20


def alert(level: str, message: str, data: dict | None = None) -> None:
    """寫入 alerts 檔案，OpenClaw 會讀並透過 Telegram 通知。"""
    ALERTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now().isoformat(),
        "level": level,
        "message": message,
        "data": data or {},
    }
    with ALERTS_FILE.open("a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"[{level}] {message}", file=sys.stderr)


def check_stale_pipeline() -> None:
    """重置 last_heartbeat 過舊的 processing items 為 pending。"""
    if not DB_PATH.exists():
        return  # DB 還沒建好（M2 前）
    conn = sqlite3.connect(DB_PATH)
    try:
        cutoff = (datetime.now() - timedelta(minutes=STALE_HEARTBEAT_MIN)).isoformat()
        cur = conn.execute(
            """
            SELECT id FROM queue_items
            WHERE status = 'processing' AND last_heartbeat < ?
            """,
            (cutoff,),
        )
        stale_ids = [row[0] for row in cur.fetchall()]
        if stale_ids:
            conn.execute(
                "UPDATE queue_items SET status = 'pending' WHERE id IN ({})".format(
                    ",".join("?" * len(stale_ids))
                ),
                stale_ids,
            )
            conn.commit()
            alert(
                "warning",
                f"Reset {len(stale_ids)} stale pipeline tasks",
                {"item_ids": stale_ids},
            )
    finally:
        conn.close()


def check_disk_space() -> None:
    if not DATA_DIR.exists():
        return
    usage = shutil.disk_usage(DATA_DIR)
    pct_free = (usage.free / usage.total) * 100
    if pct_free < DISK_CRITICAL_PCT:
        alert("critical", f"Disk space critical: {pct_free:.1f}% free")
    elif pct_free < DISK_WARN_PCT:
        alert("warning", f"Disk space low: {pct_free:.1f}% free")
    elif pct_free < DISK_INFO_PCT:
        alert("info", f"Disk space getting low: {pct_free:.1f}% free")


def check_gpu() -> None:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            alert("error", "GPU not responding (nvidia-smi failed)", {"stderr": result.stderr})
            return
        # 解析輸出，正常即可
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        alert("error", f"GPU check failed: {e}")


def check_cloudflared() -> None:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "cloudflared"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.stdout.strip() != "active":
            alert("warning", "cloudflared service not active", {"status": result.stdout.strip()})
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass  # 還沒裝（M0 前）


def check_ktv_backend() -> None:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "ktv-backend"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.stdout.strip() != "active":
            alert("warning", "ktv-backend service not active", {"status": result.stdout.strip()})
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass


def main() -> int:
    alert("info", "Watchdog tick")
    check_stale_pipeline()
    check_disk_space()
    check_gpu()
    check_cloudflared()
    check_ktv_backend()
    return 0


if __name__ == "__main__":
    sys.exit(main())
