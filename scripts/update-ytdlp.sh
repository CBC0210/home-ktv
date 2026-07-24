#!/usr/bin/env bash
# Upgrade yt-dlp and restart the backend.
#
# YouTube / Bilibili change their APIs regularly and an outdated yt-dlp is
# the #1 cause of download failures (bilibili returns HTTP 412 with old
# versions). Run this when downloads start failing, or monthly via cron:
#   0 5 1 * * /path/to/home-ktv/scripts/update-ytdlp.sh
set -euo pipefail
cd "$(dirname "$0")/../backend"

BEFORE=$(uv run python -c "import yt_dlp; print(yt_dlp.version.__version__)")
uv lock --upgrade-package yt-dlp
uv sync
AFTER=$(uv run python -c "import yt_dlp; print(yt_dlp.version.__version__)")

echo "yt-dlp: ${BEFORE} → ${AFTER}"
if [ "${BEFORE}" != "${AFTER}" ]; then
  if systemctl is-active --quiet ktv-backend 2>/dev/null; then
    sudo systemctl restart ktv-backend
    echo "ktv-backend restarted"
  fi
fi
