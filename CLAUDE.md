# Home KTV（響窩 Echonest）— 開發指南

自架的家庭 KTV：電視瀏覽器開 Player，手機掃 QR code 點歌。下載、人聲分離、歌詞對齊都在伺服器完成，處理結果永久快取。

- 部署：[docs/SETUP.md](docs/SETUP.md)
- 架構：[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- API／WebSocket 協議：[docs/API.md](docs/API.md)
- 架構決策：[docs/DECISIONS.md](docs/DECISIONS.md)
- 協作流程：[CONTRIBUTING.md](CONTRIBUTING.md)

## 技術棧

| 層 | 選型 |
|---|---|
| 後端 | FastAPI、SQLAlchemy 2.0、SQLite（WAL）、asyncio；以 `uv` 管理（Python 3.12） |
| Pipeline | yt-dlp（含 deno + bgutil PO token）、Demucs、WhisperX、FFmpeg、多來源歌詞 |
| 前端 | Next.js 15（App Router、standalone 輸出）、TypeScript、Tailwind、Zustand、hls.js、libass-wasm；以 `pnpm` 管理（Node 24） |
| 部署 | systemd user services（`scripts/install-user-services.sh`），Cloudflare Tunnel 可選 |

## 目錄

```
backend/src/main.py                FastAPI app、啟動流程、middleware
backend/src/api/                   REST 與 WebSocket 路由（rooms、guests、queue、songs、streaming、admin、library、ws）
backend/src/ktv_pipeline/          核心邏輯：config、models、auth、security、queue_manager、pipeline_orchestrator…
backend/src/ktv_pipeline/pipeline/ 各處理階段：ytdlp、demucs、lyrics、whisperx_align、lrc_to_ass、_gpu_lock
backend/tests/                     pytest
frontend/app/                      頁面：r/[roomId]/player、r/[roomId]/remote、admin、rooms
frontend/components/{player,remote,shared}/
frontend/lib/                      api.ts、ws.ts、types.ts、stores/
deploy/                            systemd user-service 範本、Dockerfile、nginx、cloudflared 範本
scripts/                           安裝、備份、watchdog、維運工具
```

## 常用指令

```bash
# 後端
cd backend && uv sync --locked
uv run uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
uv run pytest -q tests ../scripts/test_migrate_demucs_wav_to_opus.py

# 前端
cd frontend && pnpm install --frozen-lockfile
pnpm dev          # 開發
pnpm build        # 正式建置，同時做型別檢查（CI 也跑這個）
```

設定檔是 repo 根目錄的 `.env`（範本 `.env.example`）。

## 硬規則

1. **GPU 工作一律序列化**：Demucs、WhisperX 等透過 `pipeline/_gpu_lock.py` 同一時間只跑一個，避免 OOM。CPU 工作不受限。
2. **Pipeline 階段要 idempotent**：先檢查產物是否存在且有效再決定要不要重跑。狀態寫進 DB，不只放在記憶體；失敗要分 `failed_temp`（退避重試）與 `failed_perm`（跳過）。
3. **沒處理完的歌不能進播放**：只有音軌驗證完成的歌才能變成 `ready`。
4. **權限判斷用 helper**：系統管理員與房間管理員的 scope 不同。授權一律用 `auth.py` 的 `is_system_admin()`、`ensure_room_access()` 等函式，不要直接讀 token 的 `is_admin`。
5. **測試不得碰真實資料**：`tests/conftest.py` 會把 `DATA_DIR` 隔離到暫存目錄。維運腳本不得有指向真實資料的預設值，路徑一律由參數或 `DATA_DIR` 提供。
6. **不放機器專屬的東西**：密碼、網域、家目錄路徑都放 `.env`，或在執行時偵測。`.env` 永遠不進 git。
7. **刻意的設計**：曲庫、公共排行榜跨房間共用；訪客以暱稱識別，同名訪客跨房間共用收藏與歷史。不要「修正」這兩點。
8. 型別註記用 `Optional[X]` 風格。文件與 UI 文案使用繁體中文。

## 開發流程

- `main` 有分支保護，不能直接 push。從最新 `main` 開分支（`feat/…`、`fix/…`、`chore/…`、`docs/…`），完成後開 PR，CI（`backend`、`frontend`）通過才能合併。
- Commit 訊息用 `type(scope): 簡述`（feat／fix／refactor／test／docs／chore），內文說明做了什麼與為什麼。
- 改了行為就補或更新測試。改了部署或設定方式，同步更新 `docs/SETUP.md` 與 `.env.example`。
- 正式機部署 release tag，不直接追 `main`。
