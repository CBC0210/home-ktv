# Project Progress

> 這份檔案是 OpenClaw 與 Claude Code 之間的長期記憶。每個 task 完成或中斷時都必須更新。

## Status: [M0 — 專案初始化]

Last updated: 2026-05-10 17:30
Current Claude session ID: claude-sonnet-4-6
OpenClaw heartbeat: alive (2026-05-10 17:30)

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

---

## In Progress

(無)

---

## Next Up

### M0 — 專案初始化（剩餘）

- [ ] **M0-T5**: GPU 環境檢查與安裝（CUDA toolkit 安裝被 SIGKILL 中斷，需重試）
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
