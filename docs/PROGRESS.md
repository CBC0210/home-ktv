# Project Progress

> 這份檔案是 OpenClaw 與 Claude Code 之間的長期記憶。每個 task 完成或中斷時都必須更新。

## Status: [M1 — CLI Pipeline] 進行中

Last updated: 2026-05-10 19:00
Current Claude session ID: (M1 待启动)
OpenClaw heartbeat: alive (2026-05-10 19:00)

---

## Done

- [x] **M0-T1**: 建立 GitHub repo（ CBC 操作）
- [x] **M0-T2**: 初始化專案目錄（2026-05-10）
  - Commit: abed44e + df044b9
  - `backend/` — uv + FastAPI skeleton，pytest ✓
  - `frontend/` — Next.js 15 + TypeScript + Tailwind v4，pnpm build ✓
  - `data/` — media/ cache/ logs/ tmp/
- [x] **M0-T3**: 確認 `docs/` 下的初版檔案完整
- [x] **M0-T4**: 寫 `openclaw-skill/SKILL.md`
- [x] **M0-T5**: GPU 環境檢查與安裝（2026-05-10）
  - GTX 1650 4GB，Driver 580.65.06，CUDA 12.0，PyTorch CUDA ✅
  - ⚠️ 4GB VRAM（非 6GB），Demucs/whisperX 需用 smaller models
- [x] **M0-T6**: Cloudflare Tunnel（2026-05-10 18:54 CBC 完成）
  - Tunnel ID: `2c326bd5-f60f-48bb-be39-9b543689ad79`
  - DNS CNAME: ktv.bc-verse.com → tunnel ✅
  - `curl https://ktv.bc-verse.com/` → `{"status":"ok","app":"ktv-backend"}` ✅
  - ⚠️ systemd service 尚未設定（SETUP.md §4.7）
- [x] **M0-T7**: watchdog cron jobs（2026-05-10）
  - OpenClaw cron "home-ktv watchdog — 10min patrol" ✅
  - OpenClaw cron "home-ktv daily summary — 22:00" ✅

---

## In Progress

(無 — M1 待 CBC 啟動)

---

## Next Up

### M1 — CLI Pipeline（下一個 milestone）

CBC 說「開始 M1」後從 M1-T1 開始。

- [ ] **M1-T1**: 後端專案 scaffolding
- [ ] **M1-T2**: yt-dlp wrapper + 測試
- [ ] **M1-T3**: Demucs wrapper + 測試
- [ ] **M1-T4**: 歌詞抓取 manager + 各 source
- [ ] **M1-T5**: WhisperX forced alignment + 測試
- [ ] **M1-T6**: LRC → ASS 轉換 + 測試
- [ ] **M1-T7**: Pipeline orchestrator（heartbeat + state machine + 總 timeout 15min）
- [ ] **M1-T8**: 整合 CLI + 使用者驗收

### M2+ 詳見 CLAUDE.md §18

---

## ⚠️ User Action Required

(無)

---

## Blocked

(無)

---

## Recent Errors

(無，見 `docs/ERRORS.md`)

---

## Decision Log

- 2026-05-10 M0-T2: frontend 用 pnpm，需 `pnpm.onlyBuiltDependencies` 允許 sharp build
- 2026-05-10 M0-T2: backend 套件名 `ktv-pipeline`（Python: `ktv_pipeline`）
- 2026-05-10 M0-T5: 實際 GPU 為 GTX 1650 4GB（非 1660 Super 6GB），Demucs/whisperX model size 需調整
- 2026-05-10 M0-T6: Cloudflare Tunnel 已接通，backend 回應正常