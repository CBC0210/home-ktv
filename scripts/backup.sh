#!/usr/bin/env bash
# Home KTV — Backup script
# Backs up the SQLite database and configuration files.
# Media files (/data/ktv/cache/) are NOT backed up (too large, regenerable).
#
# Usage:
#   bash scripts/backup.sh
#   # Or via cron: 0 2 * * * /home/cbc/home-ktv/scripts/backup.sh >> /data/ktv/logs/backup.log 2>&1

set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────────
PROJECT_DIR="/home/cbc/home-ktv"
DATA_DIR="${DATA_DIR:-/data/ktv}"
BACKUP_BASE="${BACKUP_BASE:-/home/cbc/home-ktv-backups}"
DATE_TAG=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="${BACKUP_BASE}/${DATE_TAG}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-30}"

# ── Helpers ──────────────────────────────────────────────────────────────────
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# ── Pre-flight ───────────────────────────────────────────────────────────────
mkdir -p "${BACKUP_DIR}"
log "Backup started → ${BACKUP_DIR}"

# ── SQLite WAL checkpoint (ensures all WAL data is in the main DB file) ──────
SQLITE_DB="${DATA_DIR}/ktv.db"
if [[ -f "${SQLITE_DB}" ]]; then
    log "Checkpointing SQLite WAL..."
    sqlite3 "${SQLITE_DB}" "PRAGMA wal_checkpoint(TRUNCATE);" 2>/dev/null || true
fi

# ── Copy database files ───────────────────────────────────────────────────────
log "Backing up database..."
for f in "${SQLITE_DB}" "${SQLITE_DB}-wal" "${SQLITE_DB}-shm"; do
    [[ -f "${f}" ]] && cp "${f}" "${BACKUP_DIR}/" && log "  Copied: $(basename ${f})"
done

# ── Copy configuration ────────────────────────────────────────────────────────
log "Backing up configuration..."
CONFIG_DIR="${BACKUP_DIR}/config"
mkdir -p "${CONFIG_DIR}"

[[ -f "${PROJECT_DIR}/.env" ]]           && cp "${PROJECT_DIR}/.env" "${CONFIG_DIR}/"
[[ -f "/etc/cloudflared/config.yml" ]]   && cp "/etc/cloudflared/config.yml" "${CONFIG_DIR}/cloudflared.yml"

# ── Backup log files (last 7 days) ───────────────────────────────────────────
LOG_DIR="${DATA_DIR}/logs"
if [[ -d "${LOG_DIR}" ]]; then
    log "Backing up recent logs..."
    mkdir -p "${BACKUP_DIR}/logs"
    find "${LOG_DIR}" -name "*.log" -mtime -7 -exec cp {} "${BACKUP_DIR}/logs/" \;
fi

# ── Create compressed archive ────────────────────────────────────────────────
ARCHIVE="${BACKUP_BASE}/ktv-backup-${DATE_TAG}.tar.gz"
log "Compressing → ${ARCHIVE}"
tar -czf "${ARCHIVE}" -C "${BACKUP_BASE}" "${DATE_TAG}"
rm -rf "${BACKUP_DIR}"    # Remove uncompressed; keep only the archive
log "Archive size: $(du -sh "${ARCHIVE}" | cut -f1)"

# ── Prune old backups ─────────────────────────────────────────────────────────
log "Pruning backups older than ${KEEP_DAYS} days..."
find "${BACKUP_BASE}" -name "ktv-backup-*.tar.gz" -mtime "+${KEEP_DAYS}" -delete -print | \
    while read f; do log "  Deleted: $(basename ${f})"; done

# ── Done ─────────────────────────────────────────────────────────────────────
REMAINING=$(ls "${BACKUP_BASE}"/ktv-backup-*.tar.gz 2>/dev/null | wc -l)
log "Backup complete. ${REMAINING} backup(s) retained."
