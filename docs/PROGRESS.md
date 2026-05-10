# Project Progress

> 這份檔案是 OpenClaw 與 Claude Code 之間的長期記憶。每個 task 完成或中斷時都必須更新。

## Status: [M0 — 專案初始化]

Last updated: 2026-05-10 16:55
Current Claude session ID: claude-sonnet-4-6
OpenClaw heartbeat: alive (2026-05-10 16:55)

---

## Done

- [x] **M0-T1**: 建立 GitHub repo（⚠️ 使用者操作）
- [x] **M0-T3**: 確認 `docs/` 下的初版檔案完整
- [x] **M0-T4**: 寫 `openclaw-skill/SKILL.md`
- [x] **M0-T2**: 初始化專案目錄、backend/ + frontend/ scaffold + data/ 目錄結構
  - Commit: abed44e + df044b9 (2026-05-10)
  - 完成內容：
    - `backend/` — uv 專案（ktv-pipeline），FastAPI skeleton，/health 端點，pytest 測試通過
    - `frontend/` — Next.js 15 + TypeScript + Tailwind v4，4 個頁面骨架（player/remote/admin/room），pnpm build ✓
    - `data/` — media/ cache/ logs/ tmp/ 目錄結構（.gitkeep）
    - `.gitignore` — 更新 data/ 規則允許 .gitkeep
  - ✅ 測試：`uv run pytest tests/test_health.py` 1 passed；`pnpm build` ✓（含 pnpm.onlyBuiltDependencies 設定）
- [x] **M0-T5**: GPU 環境檢查與安裝 (2026-05-10)
  - ✅ nvidia-smi: NVIDIA GeForce GTX 1650，Driver 580.65.06，CUDA Driver 13.0
  - ✅ nvcc (CUDA Toolkit 12.0): `/usr/bin/nvcc`（之前被 SIGKILL 中斷的安裝已完成）
  - ✅ PyTorch: `torch.cuda.is_available() == True`，CUDA 13.0
  - ⚠️ **重要**：實際 GPU 為 GTX 1650（4GB），非規格書 §3.3 的 GTX 1660 Super（6GB）
    - Demucs FP16 在 4GB 可能更緊張，需實測
    - WhisperX 建議從 `small` 開始，而非 `medium`
    - 已更新 `.env.example` 備注
  - 腳本執行記錄：`data/logs/gpu-setup.log`

---

## In Progress

(無)

---

## Next Up

### M0 — 專案初始化（剩餘）

- [ ] **M0-T6**: Cloudflare Tunnel 預先建立（⚠️ 使用者操作）
- [ ] **M0-T7**: 建立 watchdog cron 任務骨架（已有 scripts/watchdog.py 骨架）

### M1 — CLI Pipeline（M0 完成後開始）

- [ ] M1-T1: 後端專案 scaffolding（backend/src/ktv_pipeline/ 已有基礎，M0-T2 建好）
- [ ] M1-T2: yt-dlp wrapper + 測試（含 timeout、retry、temp/perm 分類）
- [ ] M1-T3: Demucs wrapper + 測試（含 timeout、idempotency）
- [ ] M1-T4: 歌詞抓取 manager + 各 source
- [ ] M1-T5: WhisperX forced alignment + 測試
- [ ] M1-T6: LRC → ASS 轉換 + 測試
- [ ] M1-T7: Pipeline orchestrator（heartbeat + state machine + 總 timeout 15min）
- [ ] M1-T8: 整合 CLI + 使用者驗收

### M2+ 詳見 CLAUDE.md §18 完整列表（含新增的 Recovery、監控、Resilience 測試 task）

---

## ⚠️ User Action Required

### M0-T1: 建立 GitHub repo

請執行：

1. 到 https://github.com/new 建立 repo `home-ktv`
2. **必須選 Private**
3. **不要勾選** "Initialize with README"、".gitignore"、"License"（我們自己會建）
4. 建立後在伺服器執行：

   ```bash
   cd /home/<你的使用者>/home-ktv
   git init
   git remote add origin git@github.com:<你的帳號>/home-ktv.git
   ```

5. 確認 SSH key 已設定：`ssh -T git@github.com`，看到 "successfully authenticated" 即可
6. 完成後在 Telegram 告訴 OpenClaw：「GitHub repo 已建好」

### M0-T6: Cloudflare Tunnel

詳見 `docs/SETUP.md` 的 Cloudflare 章節。

---

## Blocked

(無)

---

## Recent Errors

(無，見 `docs/ERRORS.md`)

---

## Decision Log（重大決策摘要，完整版見 docs/DECISIONS.md）

- 2026-05-10 M0-T2: frontend 套件管理確認用 pnpm（CLAUDE.md §11 規定）；需在 package.json 加入 `pnpm.onlyBuiltDependencies` 允許 sharp/unrs-resolver build scripts
- 2026-05-10 M0-T2: backend 套件名稱用 `ktv-pipeline`（Python package: `ktv_pipeline`），M1-T1 時再確認是否需改為 `ktv`
