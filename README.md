# Home KTV

> 自用的雲端處理 + 本地播放家庭 KTV 系統。
> 透過手機掃 QR code 點歌，電視瀏覽器播放，所有重運算（YouTube 下載、人聲分離、歌詞對齊）都在伺服器完成。

## Status

🎤 **Phase**: M5 — 多人 + 評分 + 管理（進行中）

| 里程碑 | 狀態 | 說明 |
|---|---|---|
| M0 環境準備 | ✅ 完成 | GPU、Cloudflare Tunnel、watchdog cron |
| M1 CLI Pipeline | ✅ 完成 | yt-dlp + Demucs + WhisperX + LRC→ASS |
| M2 API 骨架 | ✅ 完成 | FastAPI + SQLite + WS + 認證 + 隊列 |
| M3 Player 網頁 | ✅ 完成 | Next.js + hls.js + libass-wasm |
| M4 Remote 網頁 | ✅ 完成 | 搜尋 + 隊列 + 播放控制 + 統計 |
| M5 多人+管理 | 🚧 進行中 | 用戶流程確認 + 端到端測試完成 |
| M6 部署 | ⏳ 待開始 | Docker Compose + systemd |

詳見 [`docs/PROGRESS.md`](docs/PROGRESS.md)

## Architecture

完整規格請看 [`CLAUDE.md`](CLAUDE.md)（這是專案的單一真相來源）。

簡述：

```
[ 手機 ] ─→ Cloudflare Tunnel ─→ [ FastAPI / SQLite / GPU pipeline ]
[ 電視 ] ←─                                  ↓
                                  YouTube + Demucs + WhisperX
                                  + 動態 ASS 字幕
```

## Development Workflow

本專案由 OpenClaw AI Agent 透過 Telegram 接收使用者指令，呼叫 Claude Code CLI 執行開發。
詳見 [`CLAUDE.md` §17](CLAUDE.md#17-工作流程openclaw--claude-code-整合)。

## 連結與密碼（自用速查）

| 頁面 | 網址 |
|---|---|
| **Player（電視）** | https://ktv.bc-verse.com/r/home/player |
| **Remote（手機點歌）** | https://ktv.bc-verse.com/r/home/remote |
| **Admin 管理頁** | https://ktv.bc-verse.com/admin |

| 密碼 | 預設值 | 用途 / 修改位置 |
|---|---|---|
| 入房密碼 | `home` | 手機進 home 房要輸入。改：Admin 頁 → 房間列表 → **入房密碼** |
| Remote 管理員模式 | `homeadmin` | Remote 右上角頭像**點一下**進入，可拖曳排序、永久刪歌。改：Admin 頁 → 房間列表 → **管理員密碼** |
| Admin 管理頁登入 | `BCktv210` | 進 `/admin` 的密碼（系統管理員）。改：`.env` 的 `ADMIN_PASSWORD` |

- 新建房間的管理員模式預設密碼 = `<房間ID>admin`（例：房間 `party` → `partyadmin`）。
- 三種密碼互相獨立：**入房**（進房間）≠ **管理員模式**（Remote 進階操作）≠ **Admin 頁**（系統後台）。
- 所有密碼與連結也註記在 [`.env`](.env) 檔頂部，方便在伺服器上直接查。

### 操作要點

- Player 第一次開要**點一下畫面**解鎖音訊（瀏覽器 autoplay policy）。
- 字幕來源可在 Remote「正在播放」頁切換（YouTube / NetEase / QQ / LRCLIB / 純文字 / 關閉），
  系統會在歌曲處理完後**背景預抓所有來源**，切換即時生效。
- 影片自動限制 ≤1080p 並轉碼，避免 Tunnel 卡頓；播當前歌時背景預載下一首。

## Domain

`https://ktv.bc-verse.com`

## License

私人專案，未開源。

## Stack

- **Backend**: FastAPI, SQLAlchemy 2.0, SQLite, asyncio
- **Frontend**: Next.js 15, Tailwind, shadcn/ui, libass-wasm, hls.js
- **Pipeline**: yt-dlp, Demucs, WhisperX, FFmpeg
- **Deploy**: Docker Compose, Cloudflare Tunnel, systemd
- **GPU**: GTX 1650 (4GB), CUDA serialized

## Quick Start

```bash
# 1. 複製並填入環境變數
cp .env.example .env
# 編輯 .env，填入 CF_TUNNEL_UUID 和 ADMIN_COOKIE_SECRET

# 2. 啟動 backend（需在 backend/ 目錄）
cd backend
uv sync
uv run uvicorn src.main:app --host 0.0.0.0 --port 8000

# 3. 啟動 frontend（另一個 terminal）
cd frontend
pnpm install
pnpm dev

# 4. 開啟瀏覽器
# Player: http://localhost:3000/r/home/player
# Remote: http://localhost:3000/r/home/remote
```

詳細部署步驟見 [`docs/SETUP.md`](docs/SETUP.md)。API 文件見 [`docs/API.md`](docs/API.md)。
