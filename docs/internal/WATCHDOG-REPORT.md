# home-ktv Watchdog Report — 2026-05-13 09:49

## ⚠️ ACTION REQUIRED — Backend Offline

**System Status:**
- Disk: 21% used ✓
- GPU: 0%, 1 MiB ✓
- Cloudflared: active ✓
- Frontend (port 3000): running ✓
- **Backend (port 8000): ❌ NOT LISTENING**

**Root Cause:** `ktv-backend.service` not registered with systemd (ref: PROGRESS.md M0-T6 ⚠️)

**CBC Action Required:**
```bash
# Enable and start backend service
sudo systemctl enable /home/cbc/home-ktv/deploy/ktv-backend.service
sudo systemctl start ktv-backend

# Verify
curl http://localhost:8000/health
```

**Project Status:**
- M5-T5 complete (admin page done)
- No pending Claude tasks
- Branch: feature/M2-T1-fastapi-skeleton (21 commits ahead of origin)