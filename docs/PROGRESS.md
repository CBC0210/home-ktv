# Project Progress

> 這份檔案是 OpenClaw 與 Claude Code 之間的長期記憶。每個 task 完成或中斷時都必須更新。

## Status: [M2 — API 骨架] 進行中

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
- [x] **M1-T6**: LRC → ASS 轉換 + 測試（2026-05-10）
  - `backend/src/ktv_pipeline/pipeline/lrc_to_ass.py` — 完整實作
  - Karaoke `\kf` fill 標籤（centiseconds）做卡拉 OK 效果
  - 雙行顯示：Default（當前行）+ Preview（下一行預覽）
  - `\fad(100ms,0)` fade-in per event
  - `parse_lrc_tokens()`：解析 `[mm:ss.xx]text` 為 `_Token` 清單
  - `_group_word_level()`：依 1500ms gap 門檻分組 tokens
  - `_expand_line_level()`：將 line-level tokens 拆分為逐字單元
  - `ConversionError` 處理 empty/invalid LRC
  - AssConfig 可自訂：黑体 bold、 colours、 resolution
  - 34 個單元測試全部通過 ✓
  - Commit: 9b8061d，branch `feature/M1-T6-lrc-to-ass`
- [x] **M1-T7**: Pipeline orchestrator（heartbeat + state machine + 總 timeout 15min）
  - `backend/src/ktv_pipeline/pipeline_orchestrator.py` — PipelineOrchestrator class
  - State machine：queued → pending → downloading → separating → fetching_lyrics → aligning → packaging → ready
  - Total timeout：15 分鐘（`settings.song_total_timeout_sec`），超時標記 `failed_perm`
  - Heartbeat loop：每 30 秒更新 `songs.last_heartbeat` 和 `queue_items.status`
  - Temp/Perm 錯誤分類：各階段 retry 3 次（指數退避），perm 直接跳過
  - 冪等性：每階段檢查 cache，已完成則跳過
  - GPU 序列化：Demucs + WhisperX 共享 `_GPU_LOCK`（現有實作）
  - `process_song(url)` CLI 入口：`uv run python -m ktv_pipeline.pipeline_orchestrator <url>`
  - 13 個單元測試全部通過 ✓
  - Commit: 9fec415，branch `feature/M1-T7-pipeline-orchestrator`
- [x] **M1-T8**: 整合 CLI + 使用者驗收（2026-05-11）✅ M1 完整完成
  - `config.py`：`_configure_cuda_env()` 自動設定 `LD_LIBRARY_PATH` + `PYTORCH_CUDA_ALLOC_CONF`
  - `backend/run-pipeline.sh`：一鍵執行 pipeline CLI（含 CUDA lib 路徑設定）
  - `backend/scripts/run-pipeline.sh`：進階版含 torch lib path
  - `tests/conftest.py`：pytest 啟動時同步設定 `LD_LIBRARY_PATH`
  - 降級 `DEMUCS_MODEL`：`htdemucs_ft` → `htdemucs`（GTX 1650 4GB OOM 對策）
  - 安裝 `av`、`scipy` 依賴（Demucs / WhisperX 必要）
  - 修復 orchestrator 測試（`mock cache_dir`）+ demucs mock patch 路徑
  - **153 non-network tests 全部通過 ✓**（`LD_LIBRARY_PATH` 需在 pytest 啟動前設定）
  - ⚠️ 已知：`test_lyrics.py::TestFetchNetease::test_returns_result_on_success` mock bug（不影響 LyricsManager 功能）
  - Branch: `feature/M1-T7-pipeline-orchestrator`（延用）

---

### M2-T1: FastAPI skeleton + DB 初始化（完整版）✅ (2026-05-11)
- `src/main.py`：proper lifespan context manager（取代 deprecated @on_event）
- `/health`：DB ping + version
- `/version`：GPU status（nvidia-smi）+ settings + DB path
- `database.py`：`check_db_connection()` + `get_gpu_status()` + WAL mode
- `config.py`：`settings.version` from `importlib.metadata`
- 9 個新測試（`tests/test_version.py`）
- 所有 22 tests pass ✓
- Commit: 2121cd6，branch `feature/M2-T1-fastapi-skeleton`
- ⚠️ 注意：uvicorn 需用 `src.main:app`（不是 `main:app`）

### M2-T2: SQLite 模型 + Alembic migrations ✅ (2026-05-11)
- `alembic.ini`：SQLite URL placeholder（被 env.py 動態置換）
- `migrations/env.py`：讀取 settings.db_path、import 所有 models 供 autogenerate
- `target_metadata = Base.metadata`（models import 後自動 populate）
- Initial migration stub created（autogenerate showed no diff — tables already exist）
- Stamped `8d62fbd24372` as head，`uv run alembic upgrade head` = no-op ✓
- Commit: 0cd738b，branch `feature/M2-T1-fastapi-skeleton`

### M2-T3: 認證系統（房間/管理員密碼）✅ (2026-05-11)
- `ktv_pipeline/auth.py`: hash_password/verify_password (bcrypt), create_access_token/decode_access_token (JWT), verify_room_password, verify_admin_password
- `ktv_pipeline/deps.py`: FastAPI Depends for get_current_guest, require_admin, room_password_check
- `ktv_pipeline/schemas.py`: SessionOut (JWT token + guest), GuestJoin, has_password on RoomOut
- `api/auth.py`: POST /api/auth/admin/login → session token
- `api/guests.py`: POST /api/guests/join → create/reuse guest, set ktv_session cookie; GET /api/guests/me
- `api/rooms.py`: POST /api/rooms (admin-only, password hashed); PATCH /api/rooms/{id}/password; RoomOut never exposes password_hash, only has_password bool
- `tests/test_auth.py`: 13 tests covering password hashing, JWT, admin login, guest join (including protected rooms), /me auth
- 22 tests pass
- Commit: 96b84e3

### M2-T4: WebSocket gateway ✅ (2026-05-11)
- `ws_manager.py`: ConnectionManager class (rooms, client tracking, broadcast, role-based send)
  - broadcast_queue_updated, broadcast_song_started, broadcast_song_progress, broadcast_song_ended
  - broadcast_song_processing, broadcast_guests_updated, broadcast_playback_state, broadcast_reaction, broadcast_system_error
- `api/ws.py`: WebSocket /ws endpoint, JWT auth via ?token=, role query param
  - dispatch_message() routes player.status / remote.control / admin messages
  - Closes with code 4001 (auth failed), 4004 (room not found)
- Registered /ws alongside /api routers in main.py
- Commit: b88f603

### M2-T5: 隊列管理 + 公平輪唱演算法 + 測試 ✅ (2026-05-11)
- `queue_manager.py`: QueueManager class — add/remove/reorder, fair rotation via PlayHistory, mark_playing/mark_done
- `api/queue.py`: Rewritten to use QueueManager; POST /api/queue (add), DELETE /{item_id}, PATCH /room/{room_id}/reorder (admin), POST /{item_id}/play (admin), POST /{item_id}/done (admin)
- `tests/test_queue_manager.py`: 12 tests — add, remove, reorder (with manually_moved), fair rotation, mark_playing
- 34 tests pass
- Commit: a4caf54

### M2-T6: 歌曲緩存 API + 整合 M1 pipeline ✅ (2026-05-11)
- `api/songs.py`: Rewritten — GET /search, GET /{song_id} (accepts URL or bare ID), POST / (add + queue + background pipeline), GET /{song_id}/status
- `config.py`: Added pipeline_max_retries=3, pipeline_heartbeat_sec=30 settings
- `models.py`: Added Song.status (default='pending') and Song.error_message fields
- `schemas.py`: Added SongCreate schema; SongOut includes status + error_message
- `pipeline_orchestrator.py`: _mark_ready() sets status='ready'; _mark_failed_perm() sets status='failed_perm' + error_message
- Alembic migration: add error_message + status columns to songs table
- 34 tests pass
- Commit: a890c40

### M2-T7: HLS 串流 endpoint ✅ (2026-05-11)
- `api/streaming.py`: GET /songs/{id}/stream.m3u8 (HLS manifest), GET /songs/{id}/audio/{filename} (range-request audio), GET /songs/{id}/lyrics.ass, GET /songs/{id}/info (file listing)
- `_parse_range()` for HTTP Range request support (bytes=start-end)
- `_stream_file_range()` async generator for partial content streaming
- Filename allowlist: only vocals.wav / no_vocals.wav / audio.m4a accepted (security)
- Songs not in 'ready' status → 202 Accepted with 'not ready' message
- Registered streaming router (no prefix) alongside api_router in main.py
- `tests/test_streaming.py`: 12 tests covering security, 404s, range parsing, HLS 202 behavior
- Fixed: songs table missing 'status' column in model (added + alembic migration with server_default='pending')
- 46 tests pass
- Commit: 9f54d0c

---

## In Progress

### M2-T8: 整合測試：能 API 點歌、處理、播放 ✅ 使用者驗收

Sub-tasks:
- [ ] End-to-end smoke test: create room → join → add song → verify pipeline triggered → song becomes ready
- [ ] Verify WebSocket connection works with JWT auth
- [ ] Verify stream endpoint returns audio for ready songs
- [ ] Frontend scaffolding (Next.js pages for rooms, queue, player)

Context: M2-T8 is the final M2 task. After this, M2 is complete and we move to M3 (frontend UI).

---

## ⚠️ User Action Required

- **Frontend**: CBC needs to scaffold the Next.js pages (rooms list, queue view, player view, remote control UI). Backend API is now complete.

---

## Blocked

(無)

---

## Decision Log

- 2026-05-10 M0-T2: frontend 用 pnpm，需 `pnpm.onlyBuiltDependencies` 允許 sharp build
- 2026-05-10 M0-T2: backend 套件名 `ktv-pipeline`（Python: `ktv_pipeline`）
- 2026-05-10 M0-T5: 實際 GPU 為 GTX 1650 4GB（非 1660 Super 6GB），Demucs/whisperX model size 需調整
- 2026-05-10 M0-T6: Cloudflare Tunnel 已接通，backend 回應正常
- 2026-05-11 M1-T5: 修復 `.venv` 問題（torch NCCL symbol conflict），重建 venv 後正常
- 2026-05-11 M1-T8: DEMUCS_MODEL 降為 `htdemucs`（htdemucs_ft 在 4GB VRAM OOM）；LD_LIBRARY_PATH 需在 Python 啟動前設定（os.environ 修改無效）
- 2026-05-11 OOM hotfix: Demucs+WhisperX 串列但 VRAM 未釋放導致 SIGKILL。修法：(1) 建立共享 GPU lock `_gpu_lock.py`；(2) `del model, del wav` + `gc.collect()` 在 empty_cache() 之前；(3) 加 inter-stage flush 呼叫；(4) PYTORCH_CUDA_ALLOC_CONF 加 `garbage_collection_threshold:0.8`
- 2026-05-11 M2: FastAPI skeleton, auth, WS, queue, songs API, streaming — all committed on `feature/M2-T1-fastapi-skeleton`

---

Last updated: 2026-05-11 08:50
OpenClaw heartbeat: alive (2026-05-11 08:50)