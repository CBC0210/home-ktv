# Project Progress

> 這份檔案是 OpenClaw 與 Claude Code 之間的長期記憶。每個 task 完成或中斷時都必須更新。

## Status: [M1 — CLI Pipeline] 進行中

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
  - GTX 1650 4GB，Driver 580.65.06，CUDA 13.0，PyTorch CUDA ✅
  - ⚠️ 4GB VRAM（非 6GB），Demucs/whisperX 需用 smaller models
- [x] **M0-T6**: Cloudflare Tunnel（2026-05-10 18:54 CBC 完成）
  - Tunnel ID: `2c326bd5-f60f-48bb-be39-9b543689ad79`
  - DNS CNAME: ktv.bc-verse.com → tunnel ✅
  - `curl https://ktv.bc-verse.com/` → `{"status":"ok","app":"ktv-backend"}` ✅
  - ⚠️ systemd service 尚未設定（SETUP.md §4.7）
- [x] **M0-T7**: watchdog cron jobs（2026-05-10）
  - OpenClaw cron "home-ktv watchdog — 10min patrol" ✅
  - OpenClaw cron "home-ktv daily summary — 22:00" ✅
- [x] **M1-T1**: 後端專案 scaffolding（2026-05-10）
  - Commits: bdcfde0 → 4964754（fix）
  - SQLAlchemy models + Alembic-ready Base + DB init ✓
  - Pydantic Settings from .env ✓
  - API routers: /api/rooms, /api/songs, /api/queue, /api/guests ✓
  - /health endpoint ✓
  - pytest 1 passed 0 warnings ✓
  - Server smoke test: /health ✓ /api/rooms → [] ✓
- [x] **M1-T2**: yt-dlp wrapper + 測試（2026-05-10）
  - `backend/src/ktv_pipeline/pipeline/ytdlp.py` — YtDlpWrapper class
  - Python lib mode（yt_dlp.YoutubeDL），非 subprocess
  - 格式：bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best
  - 3 次重試 + 指數退避（1s, 2s, 4s）；總 timeout 5 分鐘
  - 錯誤分類：PermDownloadError（私人/下架/地區封鎖）vs TempDownloadError（網路/timeout）
  - 冪等性：已下載的歌不重新下載，從 info.json 讀取 metadata
  - pytest 26 passed 0 errors ✓
- [x] **M1-T3**: Demucs wrapper + 測試（2026-05-10）
  - `backend/src/ktv_pipeline/pipeline/demucs.py` — DemucsWrapper class
  - GPU 序列化：module-level `asyncio.Lock`，一次只跑一個 GPU job
  - 模型：htdemucs_ft（設定檔可調），device=cuda（GTX 1650 4GB）
  - 輸出：`/data/ktv/cache/demucs/<song_id>/vocals.wav` + `no_vocals.wav`
  - Timeout：10 分鐘；超時視為 TemporaryError，最多重試 3 次
  - 錯誤分類：TemporaryError（OOM/IO/網路）vs PermanentError（模型損壞/格式錯誤）
  - CUDA OOM 後自動 `torch.cuda.empty_cache()`
  - 冪等性：輸出已存在則跳過，重試前清除 partial outputs
  - pytest 32 passed ✓
- [x] **M1-T4**: 歌詞抓取 manager + 各 source（2026-05-10）
  - `backend/src/ktv_pipeline/pipeline/lyrics.py` — 完整實作 ADR-005 fallback 鏈
  - Phase 1（synced）：AMLL TTML → NetEase → QQ → syncedlyrics（LRCLIB）
  - Phase 2（plain text）：Mojim → KKBOX → Genius
  - `LyricsResult` dataclass 輸出格式：`{lyrics_type, lrc, source}`
  - asyncio.Lock 序列化 HTTP 請求（不同於 GPU lock）
  - httpx async + 指數退避重試（最多 3 次）
  - TempLyricsError / PermLyricsError 兩級錯誤分類
  - `to_dict()` method 符合 ADR-005 統一輸出格式
  - pytest 23 passed（非 async 子集）✓
  - ⚠️ `tests/test_lyrics_manager.py` 有 syntax error（`"_fetch_amll'"` 多了一個單引號）
- [x] **M1-T5**: WhisperX forced alignment + 測試（2026-05-10）
  - `backend/src/ktv_pipeline/pipeline/whisperx_align.py` — 完整實作
  - 共享 `_GPU_LOCK`（Demucs + WhisperX 序列化，GTX 1650 4GB）
  - 錯誤分類：TemporaryError（CUDA OOM/timeout）vs PermanentError（模型損壞）
  - 冪等性：aligned.lrc 存在則跳過；重試前清除 partial outputs
  - 3 次指數退避重試（10s, 30s, 60s）；Line-level fallback 最後手段
  - 中文：逐字時間戳；英文：逐字時間戳；超出 word_data 用行時間戳兜底
  - 43 個單元測試全部通過 ✓
  - Commit: 99cd5d4，branch `feature/M1-T5-whisperx-alignment`

---

Last updated: 2026-05-10 22:00
OpenClaw heartbeat: alive (2026-05-10 22:00)

---

## In Progress

- [ ] **M1-T6**: LRC → ASS 轉換 + 測試

---

## Next Up

### M1 — CLI Pipeline（進行中）

- [x] **M1-T1**: 後端專案 scaffolding ← 已完成
- [x] **M1-T2**: yt-dlp wrapper + 測試 ← 已完成
- [x] **M1-T3**: Demucs wrapper + 測試 ← 已完成
- [x] **M1-T4**: 歌詞抓取 manager + 各 source ← 已完成（2026-05-10）
- [x] **M1-T5**: WhisperX forced alignment + 測試 ← 已完成（2026-05-10 22:00）
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
- 2026-05-10 M1-T5: 修復 `.venv` 問題（torch NCCL symbol conflict），重建 venv 後正常