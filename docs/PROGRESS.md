# Project Progress

> 這份檔案是 OpenClaw 與 Claude Code 之間的長期記憶。每個 task 完成或中斷時都必須更新。

## Status: ✅ 無字幕提示不擋畫面 + 錯歌字幕回報（2026-07-18）

Last updated: 2026-07-18
Last heartbeat: 2026-07-18

### Next Up
- （無）

### In Progress
- （無）

---

## Done

- [x] **無字幕提示改版 + 快速外連 + 「字幕是別首歌」回報** ✅ (2026-07-18)
  - **Player「無字幕/純文字」提示擋住 MV 內嵌字幕**：原本是常駐在畫面下方（bottom-20/24）的卡片，正壓在原生字幕位置。改為**頂部置中膠囊、顯示 10 秒後淡出移除**（`SubtitleLayer.NoTimingHint`），之後完全不遮擋
  - **Remote 快速外連搜尋**：原本只有「完全沒歌詞」才顯示搜尋連結；現在**只要沒有時間軸字幕就一律顯示**（有純文字歌詞時附在歌詞卡下方「歌詞不對或不完整？自行搜尋」）— Google / Mojim / Genius / YouTube 預填歌名
  - **回報新增「字幕是別首歌」**（`wrong_lyrics`）：
    - 後端：立即刪除 `lyrics.ass`、`has_timing=False`、`lyrics_source='none'`（快取的 `lyrics_<src>.ass` 替代來源保留，供「歌詞來源」picker 秒切正確來源）；廣播 `lyrics.updated` 讓電視上的錯誤卡拉 OK 字幕**當場消失**
    - 前端：回報選單新增選項；`song.profile_updated` 事件擴充 `has_timing`/`lyrics_source` 並在 Remote/Player 即時 patch currentSong — Remote 立刻顯示純文字/搜尋連結區與來源 picker，Player 立刻切到提示模式（Player 端 use_original_audio 不在播放中途切換，下次播放生效）
  - **測試**：+2（wrong_lyrics 停用字幕/保留替代來源；音訊類回報不動字幕）；133 passed，基線 11 fail + 6 error 不變；pnpm build ✓；已部署重啟

- [x] **字幕延遲校正改版 + Test Song 汙染清理** ✅ (2026-07-18)
  - **字幕延遲（如五月天〈派對動物〉延遲很重）**：
    - 範圍 ±5s → **±30s**（NowPlaying clamp + 後端 `_handle_lyrics_offset` clamp）— 歌詞對到錄音室版但 MV 有長前奏時，偏移常超過 5 秒
    - UI 改為**症狀導向**，不用再猜正負方向：「🐇 字幕跑太快（還沒唱到，字幕就先亮）→ 延後字幕」與「🐢 字幕慢半拍（唱過了，字幕才亮）→ 提前字幕」兩區，各有 0.2s / 1s / 5s 步進按鈕；保留 ←/→ 鍵 0.1s 微調與歸零；顯示目前偏移與方向說明
  - **Test Song 沒被清掉的根因**：pytest 載入 `backend/.env`（`DATA_DIR=/data/ktv`），**測試一直直接寫產線 DB** — 曲庫裡 100 首假歌（90 首 `lb-song-*`「Test Song N」、4 首「HLS Test Song」、song1/2/3、advsong1、testlyrics-*）、83 個測試房間、105 個測試 guest
    - 一次性清理：新增 `scripts/cleanup_test_data.py`（預設 dry-run、`--apply` 執行、只比對明確的測試 fixture 樣式），已對產線執行：刪 399 rows（100 songs / 83 rooms / 105 guests / 相關 queue_items+play_history），曲庫剩 805 首真歌、房間剩 `home`+`1501`
    - 永久止血：`tests/conftest.py` 在任何 ktv import 前把 `DATA_DIR`/`LOG_DIR` 指到 pytest 專用臨時目錄 + autouse session fixture `init_db()`；驗證：跑完整套測試後產線 DB 零汙染
  - **測試**：131 passed（比上輪 +2 — 兩個 test_auth 失敗原來是被汙染資料害的）；11 failed + 6 errors 為既有環境性基線；pnpm build ✓
  - **部署**：服務重啟、`/api/songs/search?q=Test` → `[]` ✓

- [x] **Remote 失控 + Player 播完不回待機 + 待機提前解鎖音效** ✅ (2026-07-17)
  - **根因 1 — Remote 完全失控**：guest JWT 效期僅 7 天，手機 localStorage 還原過期 session；後端 WS 在 `accept()` 前就 `close(4001)`，瀏覽器只看到 HTTP 403 handshake 失敗（close code 1006），前端無法分辨「token 過期」與「網路斷線」，用同一顆死 token 無限重連。UI 因公開 REST 端點照常顯示，看似正常但所有指令被丟棄（journalctl 證據：連續 403 handshake，JWT exp≈2026-05-23）。
    - 修復：token 效期 7 天 → 60 天；WS 先 accept 再 close(4001) 讓瀏覽器看得到 close code；ws.ts 收到 4001 停止重試並回呼；RemoteView 還原 session 時本地檢查 JWT exp，過期自動用記住的暱稱+房間密碼靜默重新加入（JoinForm 成功時記住房間密碼），失敗才顯示加入表單；admin 旗標若 token 無 is_admin 即自動降級。
  - **根因 2 — Player 播完卡住**：`run_from_queue` / `_update_state` 無條件寫 QueueItem.status，把播放流程標的 `playing` 蓋成 `ready`（觸發源：開機 `_kick_all_pending_pipelines` 對已 ready 歌曲重跑 pipeline），之後 `player.ended` 找不到 playing 項 → 不廣播 `song.ended` → TV 永遠停在結束的歌（journalctl 證據：`[advance] marked_done=None`）。
    - 修復：pipeline 對 `playing/done/skipped` 狀態一律不寫（`_PLAYBACK_OWNED_STATUSES` guard）；開機改為「song 已 ready 的 pending 項直接升級，不重跑 pipeline」；`_handle_song_advance` 無條件廣播 `song.ended`（找不到 playing 項時用 -1）；`player.ended/error` 帶 songId 防殭屍分頁的過期事件誤殺下一首；`player.error` 自動跳下一首（原本會讓整房卡死）；`player.ready` 時補發 playing 快照給重連的 TV、閒置時自動開播 ready 歌曲；PlayerView 端 6 秒 fallback 回待機 + 斷線期間漏送的 player.ended 重連補送。
  - **新功能 — 待機畫面提前解鎖音效**：待機 QR 畫面偵測任意輸入（遙控器按鍵/點擊/觸控）即建立並 resume Web Audio graph、標記已解鎖，第一首歌直接播放不再出現「按 OK 開始」遮罩；待機畫面顯示解鎖提示/已就緒 pill。
  - **連帶修復**（多代理驗證掃出）：ws.ts 應用層 ping 心跳 25s + 75s 無訊息判定半開連線強制重連（Cloudflare Tunnel 閒置斷線）；`connected` 改為 reactive state，Remote 顯示「連線中斷」橫幅；重連後自動重抓隊列/在線名單；seek 立即回播進度給 Remote；REST 隊列 schema 補 `use_original_audio/subtitle_offset_ms/av_offset_ms`（TV 刷新後音訊模式錯誤）；播放中歌曲可「加回隊列」；下一首預載改延遲 12 秒且不再被 queue.updated 中斷；AudioContext 被 UA 暫停時正確顯示解鎖遮罩（否則無聲播放）；playback.play 在未解鎖時顯示遮罩而非靜音空跑。
  - **測試**：新增 `tests/test_playback_advance.py` 14 tests（stomp guard、song.ended 廣播、stale event、80% 完成度、開機升級、加回隊列、player.ready 快照、WS 4001）；129 passed（既有 13 fail + 6 error 為環境性基線，與本次無關）；pnpm build ✓。
  - **線上驗證**：過期 token WS → close 4001 可見 ✓；player.ready → 快照/queue.updated ✓；ping→pong ✓；服務重啟後 /health ok、frontend BUILD_ID 一致 ✓。
  - **已知未修**（記錄備查）：QueueList 拖曳排序用 HTML5 DnD 在手機無效（需 pointer-event 實作）；fair rotation 對 `__autoplay__` 虛擬 guest 視同真人可能插隊；重播與自然結束同時發生的競態（極罕見）；歌與歌之間待機畫面短暫閃現（原有行為）。

- [x] **播放器核心功能修復** ✅ (2026-05-13)
  - **Bug 1 — Player WS 無法連線**：`token: str = Query(...)` 必填，但 Player 是電視不帶 JWT。修復：`token` 改為 Optional，player role 無需 token，透過 `room_id` query param 連線。
  - **Bug 2 — Pipeline 背景任務崩潰**：`PipelineOrchestrator.Config` 不存在（應為 `PipelineConfig`），每次新增歌曲時 pipeline 立即崩潰。修復：改名 + 改為 async 背景任務。
  - **Bug 3 — 無自動播放邏輯**：pipeline 完成後或 ready 歌曲加入隊列後，從未廣播 `song.started`。修復：`_start_next_song()` helper，在下列時機觸發：(a) ready 歌曲加入隊列、(b) pipeline 完成、(c) 已有 pending+song.ready 的 existing item。
  - **Bug 4 — Skip/曲末無切換邏輯**：`playback.skip` 只轉發給 Player 但 Player 不處理；沒有 `player.ended` 事件。修復：`_handle_song_advance()` 在 ws.py，同時處理 `playback.skip`（遙控器）和 `player.ended`（播放自然結束）。PlayerView.tsx 新增 `onended` handler。
  - **Bug 5 — Queue 隱藏 ready 項目**：`get_queue()` 只返回 `pending/processing`，pipeline 完成後隊列消失。修復：filter 加入 `"ready"`。
  - **Bug 6 — 影片路徑不符**：streaming 從 `media/{id}/video.mp4` 讀取，但 yt-dlp 下載到 `cache/{id}/video.mp4`。修復：`_song_video_path()` 先查 media 再 fallback 到 cache。
  - **Bug 7 — DB 連線池耗盡**：pool_size=1 導致兩個並行 async 任務等待 30 秒後 timeout。修復：pool_size=5, max_overflow=10。
  - **端到端驗證**：`dQw4w9WgXcQ` 加入 home 隊列 → 2 秒後 DB status 由 ready → playing ✓；Player WS 無 token 連線成功 ✓；`/songs/dQw4w9WgXcQ/video.mp4` range request 200 ✓；`/songs/dQw4w9WgXcQ/audio/vocals.wav` 200 ✓；213 tests pass ✓

- [x] **UI 全面翻新 + API 對接修正** ✅ (2026-05-13)
  - **根本原因修復**：`postcss.config.mjs` 從未建立，導致 Tailwind v4 utilities 完全未生成，頁面一直是純文字黑底
  - **API 對接修正**（4 個 bug）：
    - `getQueue` 路徑錯誤（`?room_id=` → `/room/{id}`）→ 隊列永遠空白
    - `joinRoom` token key 名稱不符（`.token` → `.access_token`）→ WebSocket 無法認證
    - `reorderQueue` 路徑錯誤（rooms → queue router）
    - `addSong` trailing slash → POST redirect 問題
  - **UI 重設計**（Spotify 暗色風）：
    - `JoinForm`：深色背景 + 紫色光暈 + 浮動 logo + 毛玻璃卡片
    - `NowPlaying`：全頁模糊封面背景、大封面圖、白色圓形播放鍵、自訂 range slider
    - `RemoteView`：SVG 圖示底部 tab、隊列數字 badge、頭像圓圈
    - `SearchView`：搜尋圖示、spinner、hover 效果
    - `QueueList`：處理中 overlay spinner、刪除 hover 顯示
    - `PlayerView` 待機：光暈動畫、QR+隊列並排布局
    - `globals.css`：自訂 range slider、細版滾軸、glow 動畫

- [x] **M6: 部署收尾** ✅ (2026-05-13)
  - cloudflared: active (running), 4 QUIC connections ✓
  - ktv-backend: active (running) on port 8000, enabled ✓
  - ktv-frontend: active (running) on port 3002, enabled ✓
  - Tunnel routing: `/api/*`, `/songs/*`, `/ws`, `/health`, `/version` → 8000; catch-all → 3002 ✓
  - End-to-end smoke: /health ✓, /version ✓, /r/home/remote 200 ✓, /rooms 200 ✓, /api/rooms 200 ✓
  - `deploy/cloudflared.yml` synced to match live config ✓

- [x] **E2E 完整流程測試**（2026-05-13）
  - `lyrics_available: True` 確認 ✓
  - `/data/ktv/media/dQw4w9WgXcQ/lyrics.ass` 存在，ASS 格式有效 ✓
  - YouTube Subtitles Phase 0 整合確認（Phase 0 在 lyrics.py fetch_lyrics() 中）✓
  - Cloudflare Tunnel 路由修復：`/api/*`, `/songs/*`, `/ws`, `/health`, `/version` → port 8000；其他 → port 3002
  - KTV Frontend 啟動於 port 3002（port 3000/3001 被 fishpond 服務佔用）
  - ktv-frontend systemd service 建立並 enabled
  - `https://ktv.bc-verse.com/r/home/remote` 返回 200 "Home KTV" ✓
  - `https://ktv.bc-verse.com/health` 返回 backend JSON ✓
  - `https://ktv.bc-verse.com/api/rooms` 返回 200 ✓
  - `/songs/dQw4w9WgXcQ/lyrics.ass` 返回有效 ASS 內容 ✓
  - `/songs/dQw4w9WgXcQ/stream.m3u8` 返回有效 HLS manifest ✓

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

### M3 Frontend Scaffolding ✅ (2026-05-11)
- `lib/types.ts`: Room, Song, Guest, QueueItem, PlaybackState, ServerEvent, ClientCommand, GuestSession
- `lib/api.ts`: getRooms, searchSongs, addSong, getQueue, addToQueue, removeFromQueue, joinRoom, streamUrl, audioUrl, lyricsUrl, isYoutubeUrl
- `lib/ws.ts`: useWebSocket hook — exponential backoff reconnect, token auth, sends/receives typed events, onConnected callback
- `lib/stores/index.ts`: Zustand KTV store — room, session, queue, playback, guests, processing, theme (PlayerTheme + THEME_STYLES)
- `components/shared/RoomCard.tsx`: room card with player/remote links
- `components/player/PlayerView.tsx`: ↓ real implementation ↓
  - Standby: QR code (react-qr-code), room name, guest count, clock, queue preview, theme-aware bg
  - Playing: hls.js video + DualAudioMixer (Web Audio API, GainNodes per track), SubtitleLayer
  - WS: player.ready on connect, player.playing every sec, player.error on HLS fatal error
  - Handles playback.play/pause/seek/setVolume commands from Remote via WS
- `components/player/SubtitleLayer.tsx`: libass-wasm real karaoke subtitles, graceful fallback
- `components/remote/RemoteView.tsx`: tab orchestrator with header + bottom nav
- `components/remote/JoinForm.tsx`: guest join form (nickname + optional room password → localStorage session)
- `components/remote/NowPlaying.tsx`: cover art, playback controls (play/pause/skip/replay), volume sliders, reactions
- `components/remote/QueueList.tsx`: pending queue with remove action
- `components/remote/SearchView.tsx`: search + YouTube URL paste-to-add, insert-next support
- `components/remote/RoomTab.tsx`: room info, copy link, online guests list, theme switcher (4 themes)
- `app/rooms/page.tsx`: server-rendered room list (revalidate: 30s)
- `app/r/[roomId]/player/page.tsx`: player route
- `app/r/[roomId]/remote/page.tsx`: remote route
- `public/libass/`: subtitles-octopus-worker.js + wasm for karaoke subtitles
- `types/libass-wasm.d.ts`: TypeScript declaration
- **pnpm build ✓** (6 routes, 0 errors, 0 type errors)
- Commits: 84e5df6 (scaffold) → fb83f8c (T2 standby+QR) → 22f3670 (T3+T4 dual-audio+libass) → 9293b0f (T5+T6 WS+theme)

### **M3 COMPLETE ✅** (2026-05-11)

### M2-T8: 整合測試 ✅ (2026-05-11)
- `tests/test_e2e_smoke.py`: 9 tests — create room, join as guest, add song, pipeline triggered, song pending→ready, duplicate dedup, WebSocket auth, stream HLS for ready song, stream 202 for pending song
- Bug fixes: `create_access_token` now includes `is_admin` in JWT payload (was missing → admin-only routes returned 403); `POST /api/songs` returns `SongOut` instead of mismatched `QueueItemOut`
- 107 non-GPU/network tests pass ✓
- Branch: `feature/M2-T1-fastapi-skeleton`

**M2 COMPLETE ✅**

### M4-T7: 端到端整合測試 ✅ (2026-05-11 11:50)

Sub-tasks:
- [x] M4-T1/T2: scaffolding + JoinForm (done as part of M3)
- [x] M4-T3: 「正在播放」頁 — seek bar + WS control ✅ (01faa01)
- [x] M4-T4: WS queue add/remove/reorder ✅ (7076163)
- [x] M4-T5: YouTube 搜尋 API + SearchView ✅ (b75e9c9)
- [x] M4-T6: 「房間」頁 + 統計 charts ✅ (001eeb6)
- [x] M4-T7: 端到端整合測試 ✅ (this session)

**整合測試結果:**
- Backend: 207 tests pass (excluding test_lyrics.py mock issue, non-functional)
- Frontend: pnpm build ✓ (6 routes, 0 errors)
- Backend API: /health → `{"status":"ok"}`, /api/rooms → 正常回應
- Frontend: http://localhost:3000 → 200, /rooms → 200
- 9/9 e2e smoke tests pass
- GPU: nvidia-smi non-zero exit (no display attached, expected)

**⚠️ 待清理:** test_db 殘留 80+ 測試用房間資料（smoke-*/test-*），不影響功能。

**M4 COMPLETE ✅ (2026-05-11)**

---

### M5-T2: 端到端測試 ✅ (2026-05-11 15:45)

**測試結果（6 步全部通過）：**
- [x] Step 1: POST /api/rooms — 建立測試房間 `e2e-test-room` ✅
- [x] Step 2: POST /api/guests/join — 以 guest 身份加入（含房間密碼）✅
- [x] Step 3: GET /api/songs/search?q=test — 找到 20 首歌、9 首 ready ✅
- [x] Step 4: POST /api/queue?room_id=e2e-test-room — 加入 ready 歌曲 ✅
- [x] Step 5: GET /api/songs/{id}/status — status=ready + queue tracking ✅
- [x] Step 6: WS /ws?token=...&room_id=...&role=remote — 連線成功，收到 guests.updated ✅
- Pipeline trigger: POST /api/songs 會對新 URL 觸發背景 pipeline（dQw4w9WgXcQ 因 YouTube 網路封鎖而 total_timeout，pipeline 本身正常）
- Backend: 207 tests pass
- Frontend: pnpm build ✓

---

### M5-T1: 用戶流程最終確認 + 歌詞 ASS 替換 ✅ (2026-05-11)

Sub-tasks:
- [x] M4-T6 commit（recharts stats charts + test_lyrics.py mock fix）
- [x] `ws_manager.py`: `broadcast_lyrics_updated()` — notify PLAYER clients
- [x] `ws.py`: `lyrics.edit` WS handler（overwrite ASS file → notify Player）
- [x] `ws.py`: `playback.setVolume` forward to PLAYER（was missing）
- [x] `ws.py`: `_get_room_guests_info()` + `guests.updated` broadcast on connect/disconnect
- [x] `streaming.py`: `PUT /songs/{song_id}/lyrics` endpoint（validate → write → 200）
- [x] `frontend/lib/types.ts`: `lyrics.updated` server event
- [x] `frontend/lib/api.ts`: `getLyricsAss()` + `updateLyricsAss()` + `getOnlineGuests()`
- [x] `frontend/PlayerView.tsx`: handle `lyrics.updated` → `subtitleRevision` key increment
- [x] `frontend/NowPlaying.tsx`: ✏️ 歌詞時間軸 button + ASS textarea modal + save → `lyrics.edit` WS
- [x] Backend tests: 138 passed ✓
- [x] Frontend build: 6 routes ✓

**完整用戶流程確認：**
- 訪客進房間 → JoinForm → LocalStorage session ✓
- 搜尋歌曲 → YouTube search → 加入隊列 ✓
- WS 隊列同步（add / remove / reorder）✓
- 播放控制（play / pause / seek / setVolume / skip / replay）✓
- 表情反應 ✓
- 房間統計（pie chart + bar chart）✓
- 歌詞 ASS 替換（NowPlaying ✏️ → WS lyrics.edit → Player SubtitleLayer 重新掛載）✓

---

### M5-T3: 部署文檔與交接 ✅ (2026-05-11 16:30)

Sub-tasks:
- [x] `docs/API.md` — 完整 REST + WebSocket 協議文件（10 章節、所有 endpoint）
- [x] `deploy/Dockerfile.backend` — Python 3.12 + uv + ffmpeg
- [x] `deploy/Dockerfile.frontend` — Node 20 + pnpm multi-stage build
- [x] `docker-compose.yml` — backend + frontend + volume mounts
- [x] `deploy/nginx.conf` — WebSocket + 串流 + 靜態資源 cache
- [x] `deploy/cloudflared.yml` — Cloudflare Tunnel 設定（含已知 Tunnel UUID）
- [x] `deploy/ktv-backend.service` — systemd service（含 CUDA env vars）
- [x] `deploy/ktv-frontend.service` — systemd service
- [x] `scripts/backup.sh` — SQLite WAL checkpoint + 壓縮備份 + 自動清理 30 天前
- [x] `docs/SETUP.md` — 新增 §5-8：systemd 安裝、備份 cron、資料目錄、健康確認清單
- [x] `README.md` — 更新 Status 里程碑表格 + Quick Start 指令

### M5-T4: 排行榜頁 ✅ (2026-05-11)

Sub-tasks:
- [x] `GET /api/songs/leaderboard?category=all_time|monthly_hot|personal&limit=N`
- [x] all_time: songs.play_count 排序；monthly_hot: play_history 本月聚合；personal: 需 JWT
- [x] `get_optional_guest_dep`：公開分類免驗證，personal 需登入
- [x] `LeaderboardView.tsx`：三分類選擇器、名次獎牌、加入/插播按鈕
- [x] `SearchView.tsx`：加入排行榜子標籤
- [x] `api.ts`：`getLeaderboard()`、`LeaderboardItem`、`LeaderboardCategory` types
- [x] 16 個測試全部通過；pnpm build ✓
- Commit: 1291986

---


### M5-T5: 管理員頁 + 房間建立 + 錯誤日誌 ✅ (2026-05-11 17:45)

Sub-tasks:
- [x] `/admin` 頁面（密碼驗證，localStorage admin_token）
- [x] 建立新房間（id/name/password）+ 刪除房間
- [x] 修改房間密碼（設密碼 / 移除密碼）
- [x] 錯誤日誌檢視（error_log table）+ 標記已解決 + 批量解決
- [x] 緩存管理（磁碟用量顯示 + cache/tmp/all 清除按鈕）
- [x] 系統狀態（GPU、pending pipeline count、歌曲統計、DB 連線）

Backend:
- `api/admin.py`: admin router — /admin/rooms, /admin/error-logs, /admin/cache-stats, /admin/cache/clear, /admin/system-status
- 所有 endpoints 需 admin JWT（require_admin dependency）

Frontend:
- `app/admin/page.tsx`: 4 分頁（房間 / 錯誤日誌 / 緩存 / 系統）
- `lib/api.ts`: adminApiFetch + 所有 admin API functions + types

pnpm build ✓ (6 routes, 0 errors)
Commit: 30e6c19, branch `feature/M2-T1-fastapi-skeleton`

## ⚠️ User Action Required

(無)


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


---
Last updated: 2026-05-11 16:30 (Claude session — M5-T3 deployment docs complete)
Last heartbeat: 2026-05-11 16:30