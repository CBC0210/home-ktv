# 響窩 Echonest — Home KTV

> 自架的家庭 KTV：手機掃 QR code 點歌，電視瀏覽器播放。YouTube/Bilibili
> 下載、人聲分離與歌詞對齊都在自己的伺服器完成，處理結果會永久快取。

由 [CBC](https://github.com/CBC0210) 製作 · [GitHub](https://github.com/CBC0210/home-ktv)

## 功能

- Player：原 MV、雙音軌混音、動態 KTV 字幕與房間 QR code。
- Remote：搜尋點歌、隊列與播放控制、收藏、歷史、排行榜與字幕校正。
- Admin：房間與密碼、快取與磁碟、錯誤日誌、預裝歌單與系統狀態。
- Pipeline：yt-dlp、Demucs、WhisperX、FFmpeg，以及多來源歌詞 fallback。

架構導覽見 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)，API 協議見
[`docs/API.md`](docs/API.md)。

## 需求

| 元件 | 版本／說明 |
|---|---|
| Ubuntu | 近期 LTS 版本 |
| Python | 3.12+，使用 `uv` |
| Node.js | 24，使用 `pnpm` |
| FFmpeg、Deno | 必須 |
| GPU | 可選；NVIDIA CUDA 4GB+ VRAM 建議使用 |
| 磁碟 | 媒體永久快取，建議至少 20GB |

## Quick Start（區域網開發）

```bash
git clone https://github.com/CBC0210/home-ktv.git
cd home-ktv
cp .env.example .env
$EDITOR .env

cd backend
uv sync --locked
uv run uvicorn src.main:app --host 0.0.0.0 --port 8000
```

另開終端機：

```bash
cd home-ktv/frontend
pnpm install --frozen-lockfile
pnpm dev
```

電視開啟 `http://<伺服器IP>:3000/r/home/player`，手機掃 QR code；管理頁為
`http://<伺服器IP>:3000/admin`。前端未設定 `NEXT_PUBLIC_API_URL` 時，會自動連到
同主機的 `:8000` 後端。

## 密碼

| 用途 | 設定方式 |
|---|---|
| 入房密碼 | `DEFAULT_ROOM_PASSWORD` 只用於首次建立 `home`；之後由管理頁修改 |
| 房間管理模式 | 用 `ADMIN_PASSWORD`，或由管理頁另設房間管理密碼 |
| Admin 後台 | 根目錄 `.env` 的 `ADMIN_PASSWORD` |

歷史預設 `<room_id>admin` 已停用，既有的同型密碼也會在啟動時清除。公開部署前務必
更換 `ADMIN_PASSWORD` 與 `ADMIN_COOKIE_SECRET`。

## 正式部署

Ubuntu 從零安裝、systemd user services、更新、備份與可選 Cloudflare Tunnel 的唯一指南：
[`docs/SETUP.md`](docs/SETUP.md)。Docker Compose 與相關 Dockerfile 仍保留供自行選用。

## License

[PolyForm Noncommercial 1.0.0](LICENSE.md) — 可自由自架、修改、分享，不得商業使用。
