# Home KTV

> 自用的雲端處理 + 本地播放家庭 KTV 系統。
> 透過手機掃 QR code 點歌，電視瀏覽器播放，所有重運算（YouTube 下載、人聲分離、歌詞對齊）都在伺服器完成。

## Status

🚧 **Phase**: M0 — 專案初始化中

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

## Domain

`https://ktv.bc-verse.com`

## License

私人專案，未開源。

## Stack

- **Backend**: FastAPI, SQLAlchemy 2.0, SQLite, asyncio
- **Frontend**: Next.js 15, Tailwind, shadcn/ui, libass-wasm, hls.js
- **Pipeline**: yt-dlp, Demucs, WhisperX, FFmpeg
- **Deploy**: Docker Compose, Cloudflare Tunnel, systemd
- **GPU**: GTX 1660 Super (6GB), CUDA serialized
