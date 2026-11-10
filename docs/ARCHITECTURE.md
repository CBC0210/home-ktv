# 架構 Architecture — 響窩 Echonest / Home KTV

> 給部署者與貢獻者的系統導覽；以本文與實際程式碼為準。

## 總覽

```
[手機 Remote]──┐                       ┌─ FastAPI (REST + WebSocket)   backend/src/
[電視 Player]──┼── HTTP/WS ──────────→ ├─ SQLite (WAL) + SQLAlchemy    DATA_DIR/ktv.db
[Admin 後台]───┘   （同一台伺服器）      ├─ asyncio pipeline workers
                                       ├─ 媒體永久快取                 DATA_DIR/media/<id>/
                                       └─ Demucs / WhisperX (CUDA，序列化)
```

- **Player**（`/r/<room>/player`）：電視瀏覽器。播 MV（`<video>` 靜音）+ 雙音軌
  `<audio>`（伴奏/人聲）經 Web Audio GainNode 即時混音；libass-wasm 渲染逐句卡拉 OK
  字幕。待機畫面顯示房間 QR code。
- **Remote**（`/r/<room>/remote`）：手機 PWA。搜尋/貼連結點歌、隊列管理、播放控制、
  人聲音量、字幕校正、收藏/歷史/排行榜、表情反應。
- **Admin**（`/admin`）：房間與密碼、快取/磁碟、錯誤日誌、預裝歌單批次預載、系統狀態。

前後端各自獨立行程（Next.js :3000 / FastAPI :8000）。零設定模式下前端自動連
「同主機:8000」；要走單一網域反向代理時 build 時設 `NEXT_PUBLIC_API_URL`。

## 歌曲 ID 與媒體佈局

`songs.id` 即影片 ID（YouTube 11 碼；Bilibili `BV…`/`av…`），同時是快取目錄名：

```
DATA_DIR/media/<id>/
  video.mp4            # ≤1080p
  vocals.wav           # Demucs 分離的人聲
  no_vocals.wav        # 伴奏
  lyrics.ass           # 作用中的卡拉 OK 字幕
  lyrics_<source>.ass  # 各來源預抓快取（歌詞來源秒切）
  lyrics.txt           # 純文字歌詞
```

## 處理 Pipeline（`ktv_pipeline/pipeline_orchestrator.py`）

```
點歌 → 查快取（命中→秒播）
  ↓ 未命中
① yt-dlp 下載（CPU）→ ② Demucs 人聲分離（GPU）→ ③ 歌詞抓取（網路）
  → ④ WhisperX 對齊（GPU，僅需要時）→ ⑤ LRC→ASS → ready → WS 通知全房間
```

- **GPU 序列化**：Demucs 與 WhisperX 共用一把 `asyncio.Lock`，同時只跑一個 GPU 任務
 （4GB VRAM 也能跑；`ENABLE_GPU=false` 全走 CPU）。
- **冪等**：每階段先檢查產物存在即跳過；重跑安全。
- **狀態保護**：pipeline 永不覆寫 `playing/done/skipped`（播放流程擁有這些狀態）。
- **失敗分級**：temp（重試+退避）/ perm（跳過並標記）；單曲總時限 `SONG_TOTAL_TIMEOUT_SEC`。

### 歌詞來源鏈與防錯配

依序：影片原生字幕 → AMLL TTML（逐字）→ NetEase → QQ → LRCLIB → 純文字
（Mojim/KKBOX/Genius）。每個候選都經**標題+歌手+時長**綜合計分驗證
（`_score_candidate`，門檻不過寧可無字幕），所有來源預抓快取，Remote 可秒切。

## 隊列與公平輪唱（`ktv_pipeline/queue_manager.py`）

`apply_fair_order()` 把輪唱結果**實體化回隊列 position**：同一人的歌自動錯開、
手動拖曳過的歌（`manually_moved`）釘住不動、正在唱的人算入「最近唱過」窗口。
每次隊列變動即重排並廣播 → 手機隊列與電視「下一首」顯示的就是實際播放順序。

## 即時同步（WebSocket，`api/ws.py`）

單一 `/ws` 端點，三種角色：`player`（電視，免 token）/ `remote`（guest JWT）/ `admin`。
Server 推播 `queue.updated / song.started / song.ended / playback.state / …`；
Remote 送 `playback.* / queue.* / lyrics.* / reaction.send`。完整訊息表見
[`API.md`](API.md)。

可靠性設計：25s 應用層 ping + 75s 無訊息判定半開連線重連（Cloudflare Tunnel 閒置
斷線對策）；auth 失敗以 close code 4001 告知，前端自動以記住的暱稱+房間密碼靜默重
新加入；TV 重連時後端補發正在播放的快照。

## 認證

- 訪客：房間密碼（bcrypt）→ 暱稱 → guest JWT（60 天），存 localStorage。
- 房間管理模式：系統 `ADMIN_PASSWORD` 或另設的房間管理密碼 → 重簽 `is_admin` JWT；
  歷史預設 `<room_id>admin` 已停用。
- 系統 Admin：`ADMIN_PASSWORD`（`/admin`）。
- 首次啟動自動建立預設房間 `home`（`DEFAULT_ROOM_PASSWORD` 可設密碼）。

## 韌性（resilience）

- 重啟恢復：卡在中間狀態的隊列項重置為 pending、已 ready 的直接升級（不重跑）。
- `player.error` 自動跳下一首；`player.ended` 掉包由重連補送 + TV 端 6 秒 fallback。
- 閒置房間（30 分鐘無連線）自動清隊列回待機。
- 磁碟/GPU/服務監控：`scripts/watchdog.py` + `/admin` 系統狀態頁。
- yt-dlp 過舊會被影片站封鎖（Bilibili 回 412）：`scripts/update-ytdlp.sh` 一鍵升級。

## 目錄速覽

```
backend/src/
  main.py                  # FastAPI app、lifespan（migration/seed/recovery）
  api/                     # rooms/queue/songs/guests/auth/admin/ws/streaming
  ktv_pipeline/
    config.py              # Settings（根目錄 .env）；CUDA lib 路徑自動解析
    queue_manager.py       # 隊列 + 公平輪唱
    ws_manager.py          # 連線管理與廣播
    pipeline_orchestrator.py
    pipeline/              # ytdlp / demucs / lyrics / whisperx / lrc_to_ass
frontend/
  app/r/[roomId]/{player,remote}/  # 兩個入口
  components/{player,remote}/
  lib/{api,ws,endpoint,stores}.ts
deploy/                    # Dockerfile、systemd user 樣板、cloudflared/nginx 範例
scripts/                   # backup / watchdog / update-ytdlp / cleanup
```
