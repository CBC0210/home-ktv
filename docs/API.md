# Home KTV — API & WebSocket 協議

> 完整 API 文件。所有路由均掛在 `https://ktv.example.com`。
> REST API 前綴為 `/api`；WebSocket 端點為 `/ws`；串流端點為 `/songs/{id}/...`。

---

## 目錄

1. [認證方式](#1-認證方式)
2. [REST — Auth](#2-rest--auth)
3. [REST — Rooms](#3-rest--rooms)
4. [REST — Guests](#4-rest--guests)
5. [REST — Songs](#5-rest--songs)
6. [REST — Queue](#6-rest--queue)
7. [REST — Streaming](#7-rest--streaming)
8. [WebSocket 協議](#8-websocket-協議)
9. [資料結構參考](#9-資料結構參考)
10. [錯誤代碼](#10-錯誤代碼)

---

## 1. 認證方式

系統使用 **JWT Bearer Token**，由 `/api/guests/join` 或 `/api/auth/admin/login` 取得。

### REST 呼叫

在 `Authorization` header 或 `Cookie: ktv_session=<token>` 中帶入：

```
Authorization: Bearer <token>
```

### WebSocket

在 query string 帶入 token：

```
wss://ktv.example.com/ws?token=<token>&room_id=<room_id>&role=remote
```

### Token Payload

```json
{
  "sub": "<guest_uuid>",
  "room_id": "home",
  "is_admin": false,
  "exp": 1234567890
}
```

---

## 2. REST — Auth

### `POST /api/auth/admin/login`

以管理員密碼取得管理員 JWT。

**Query Params**
| 參數 | 型別 | 說明 |
|---|---|---|
| `password` | string | 管理員密碼（`.env` 的 `ADMIN_PASSWORD`）|

**Response 200**
```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "guest": {
    "id": "<uuid>",
    "nickname": "__system_admin__",
    "avatar_color": "#7c3aed",
    "is_admin": true
  }
}
```

**Errors**
- `401` — 密碼錯誤

---

## 3. REST — Rooms

### `GET /api/rooms`

列出所有房間（公開，不帶密碼 hash）。

**Response 200** — `RoomOut[]`
```json
[
  {
    "id": "home",
    "name": "Home",
    "is_default": true,
    "created_at": "2026-05-10T00:00:00Z",
    "settings": {},
    "has_password": true
  }
]
```

---

### `POST /api/rooms`

建立新房間。需要管理員 JWT。

**Request Body**
```json
{
  "id": "party",
  "name": "派對房",
  "password": "party123"
}
```

**Response 200** — `RoomOut`

**Errors**
- `403` — 非管理員
- `409` — 房間 ID 已存在

---

### `GET /api/rooms/{room_id}`

取得單一房間資訊。

**Response 200** — `RoomOut`
**Errors** — `404`

---

### `PATCH /api/rooms/{room_id}/password`

變更房間密碼。需管理員。

**Query Params** — `new_password: string`

**Response 200**
```json
{ "status": "ok", "room_id": "home", "has_password": true }
```

---

### `GET /api/rooms/{room_id}/stats`

取得房間播放統計（用於 Remote 的「房間」頁圖表）。

**Response 200**
```json
{
  "room_id": "home",
  "total_songs_played": 42,
  "unique_songs": 28,
  "total_play_duration_sec": 7200,
  "avg_rating": 4.2,
  "top_songs": [
    {
      "song_id": "dQw4w9WgXcQ",
      "title": "Never Gonna Give You Up",
      "artist": "Rick Astley",
      "thumbnail_url": "https://i.ytimg.com/...",
      "play_count": 5,
      "total_duration_sec": 1050
    }
  ],
  "recent_plays": [
    {
      "song_id": "dQw4w9WgXcQ",
      "played_at": "2026-05-11T20:00:00Z",
      "duration_sec": 212,
      "rating": 5
    }
  ]
}
```

---

### `GET /api/rooms/{room_id}/stats/processing`

取得房間歌曲處理狀態分佈。

**Response 200**
```json
{ "pending": 1, "processing": 1, "ready": 8, "failed_perm": 0, "failed_temp": 0 }
```

---

## 4. REST — Guests

### `POST /api/guests/join`

加入房間，建立或恢復訪客身份，取得 JWT。

**Request Body**
```json
{
  "nickname": "小明",
  "room_id": "home",
  "room_password": "home"
}
```

`room_password` 在房間無密碼時可省略。

**Response 200** — 同時設定 `ktv_session` cookie（7 天有效）
```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "guest": {
    "id": "<uuid>",
    "nickname": "小明",
    "avatar_color": "#059669",
    "is_admin": false
  }
}
```

**Errors**
- `403` — 房間密碼錯誤
- `404` — 房間不存在

---

### `GET /api/guests/me`

取得目前登入訪客資訊。需要 JWT。

**Response 200** — `GuestOut`

---

### `GET /api/guests/online/{room_id}`

取得指定房間目前在線的訪客列表（透過 WebSocket 連線判斷）。

**Response 200** — `GuestOut[]`

---

### `GET /api/guests/{guest_id}`

取得特定訪客資訊（公開端點）。

**Response 200** — `GuestOut`

---

## 5. REST — Songs

### `GET /api/songs/search`

搜尋本地已處理過的歌曲。

**Query Params**
| 參數 | 型別 | 預設 | 說明 |
|---|---|---|---|
| `q` | string | `""` | 關鍵字（比對 title / artist） |
| `limit` | int | `20` | 最多回傳幾首 |

**Response 200** — `SongOut[]`（依 `play_count` 降冪）

---

### `GET /api/songs/youtube-search`

透過 yt-dlp 搜尋 YouTube（不下載、不處理）。

**Query Params**
| 參數 | 型別 | 說明 |
|---|---|---|
| `q` | string | 搜尋關鍵字 |
| `limit` | int | 最多結果數（預設 10）|

**Response 200**
```json
[
  {
    "id": "dQw4w9WgXcQ",
    "title": "Never Gonna Give You Up",
    "channel": "Rick Astley",
    "duration_sec": 212,
    "thumbnail_url": "https://i.ytimg.com/...",
    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "cached": false
  }
]
```

**Errors**
- `503` — YouTube 搜尋暫時不可用

---

### `POST /api/songs`

以 YouTube URL 新增歌曲並加入隊列。需要 JWT。

若歌曲已緩存則直接加隊列不重新處理；若是新歌則觸發背景 pipeline。

**Request Body**
```json
{
  "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
  "room_id": "home"
}
```

也可直接傳 11 碼 YouTube ID：`"youtube_url": "dQw4w9WgXcQ"`

**Response 200** — `SongOut`（`status` 初始為 `pending` 或 `ready`）

**Errors**
- `400` — 無效的 YouTube URL/ID
- `404` — 房間不存在

---

### `GET /api/songs/{song_id}`

取得單一歌曲詳細資訊。`song_id` 可為 11 碼 ID 或完整 YouTube URL。

**Response 200** — `SongOut`
**Errors** — `404`

---

### `GET /api/songs/{song_id}/status`

取得歌曲的處理狀態與隊列位置。

**Response 200**
```json
{
  "song_id": "dQw4w9WgXcQ",
  "status": "ready",
  "error_message": null,
  "queue_items": [
    {
      "id": 1,
      "room_id": "home",
      "position": 0,
      "queue_status": "pending"
    }
  ]
}
```

`status` 可能值：`pending` | `downloading` | `separating` | `fetching_lyrics` | `aligning` | `packaging` | `ready` | `failed_temp` | `failed_perm`

---

## 6. REST — Queue

### `GET /api/queue/room/{room_id}`

取得房間的播放隊列（依 position 排序）。

**Response 200** — `QueueItemOut[]`

---

### `POST /api/queue`

將已存在的歌曲加入隊列。需要 JWT。

> 通常建議用 `POST /api/songs` 同時建歌+入隊，這個端點適合已知 song_id 的場景。

**Query Params** — `room_id: string`

**Request Body**
```json
{
  "song_id": "dQw4w9WgXcQ",
  "position": "end"
}
```

`position`：`"end"`（隊尾，套用公平輪唱）或 `"next"`（插播下一首）

**Response 200** — `QueueItemOut`

---

### `PATCH /api/queue/room/{room_id}/reorder`

重新排序隊列。需管理員。

**Request Body** — `[item_id1, item_id2, ...]`（新的順序）

**Response 200**
```json
{ "status": "ok", "ordered_item_ids": [3, 1, 2] }
```

---

### `DELETE /api/queue/{item_id}`

從隊列移除一首歌。點歌本人或管理員均可。

**Response 200** — `{ "ok": true }`

---

### `POST /api/queue/{item_id}/play`

標記某隊列項目為播放中。需管理員。

**Response 200** — `QueueItemOut`

---

### `POST /api/queue/{item_id}/done`

標記某隊列項目為播放完畢。需管理員。

**Response 200** — `{ "ok": true }`

---

## 7. REST — Streaming

所有串流端點不帶 `/api` 前綴，直接在 `/songs/` 下。

### `GET /songs/{song_id}/stream.m3u8`

取得 HLS 播放清單。歌曲 `status` 必須為 `ready`，否則回 `202`。

**Response 200** — `application/vnd.apple.mpegurl`
**Response 202** — 歌曲尚未處理完成

---

### `GET /songs/{song_id}/audio/{filename}`

串流音訊檔案，支援 HTTP Range 請求（`206 Partial Content`）。

`filename` 僅允許：`vocals.wav`、`no_vocals.wav`、`audio.m4a`

**Headers**
```
Range: bytes=0-65535
```

**Response 200/206** — `audio/wav`
**Errors**
- `403` — filename 不在允許清單
- `404` — 檔案不存在

---

### `GET /songs/{song_id}/lyrics.ass`

取得 ASS 格式的卡拉 OK 字幕檔。

**Response 200** — `application/x-ass`
**Errors** — `404`

---

### `PUT /songs/{song_id}/lyrics`

替換歌曲的 ASS 字幕（使用者手動修改字幕時間軸後上傳）。

**Request Body**
```json
{ "ass": "[Script Info]\n..." }
```

**Response 200**
```json
{ "status": "ok", "song_id": "dQw4w9WgXcQ", "bytes": 4096 }
```

---

### `GET /songs/{song_id}/info`

取得歌曲的可用檔案清單與快取目錄。

**Response 200**
```json
{
  "song_id": "dQw4w9WgXcQ",
  "status": "ready",
  "files": {
    "vocals.wav": { "size_bytes": 18432000 },
    "no_vocals.wav": { "size_bytes": 18432000 }
  },
  "lyrics_available": true,
  "cache_dir": "<DATA_DIR>/cache/demucs/dQw4w9WgXcQ"
}
```

---

### `GET /health`

系統健康檢查。

**Response 200**
```json
{ "status": "ok", "app": "ktv-backend", "version": "0.1.0" }
```

---

### `GET /version`

取得詳細版本與 GPU 狀態資訊。

**Response 200**
```json
{
  "version": "0.1.0",
  "python_version": "3.12.x",
  "gpu_status": {
    "available": true,
    "name": "NVIDIA GeForce GTX 1650",
    "memory_total_mb": 4096,
    "driver_version": "580.65.06"
  },
  "db_path": "<DATA_DIR>/ktv.db",
  "data_dir": "/data/ktv"
}
```

---

## 8. WebSocket 協議

### 連線

```
wss://ktv.example.com/ws?token=<jwt>&role=<player|remote|admin>
```

- `token` — 必填，來自 `/api/guests/join` 或 `/api/auth/admin/login`
- `role` — `remote`（手機遙控）、`player`（電視 Player）、`admin`（管理員）
- `room_id` 從 JWT payload 中取得，不需重複傳

**連線失敗關閉代碼**
- `4001` — JWT 無效或過期
- `4004` — 房間不存在

---

### 8.1 Server → Client 推送事件

```typescript
type ServerEvent =
  | { type: 'queue.updated'; queue: QueueItemDict[] }
  | { type: 'song.started'; song: SongDict; queueItem: QueueItemDict }
  | { type: 'song.progress'; positionSec: number }
  | { type: 'song.ended'; queueItemId: number }
  | { type: 'song.processing'; queueItemId: number; stage: string; percent: number }
  | { type: 'lyrics.updated'; songId: string }
  | { type: 'guests.updated'; guests: GuestDict[] }
  | { type: 'playback.state'; state: PlaybackStateDict }
  | { type: 'reaction'; emoji: string; from: string }
  | { type: 'system.error'; message: string }
  | { type: 'system.restarted' }
```

---

### 8.2 Remote → Server 指令

```typescript
type ClientCommand =
  // 隊列操作
  | { type: 'queue.add'; youtubeId: string; position?: 'end' | 'next' }
  | { type: 'queue.remove'; queueItemId: number }
  | { type: 'queue.reorder'; queueItemIds: number[] }

  // 播放控制（轉發給 Player）
  | { type: 'playback.play' }
  | { type: 'playback.pause' }
  | { type: 'playback.skip' }
  | { type: 'playback.replay' }
  | { type: 'playback.seek'; positionSec: number }
  | { type: 'playback.setVolume'; main?: number; vocal?: number }

  // 表情反應
  | { type: 'reaction.send'; emoji: string }

  // 歌詞編輯（直接覆寫 ASS 檔案並通知 Player 重載）
  | { type: 'lyrics.edit'; songId: string; ass: string }
```

---

### 8.3 Player → Server 狀態回報

```typescript
type PlayerStatus =
  | { type: 'player.ready' }
  | { type: 'player.playing'; positionSec: number }
  | { type: 'player.buffering' }
  | { type: 'player.error'; error: string }
```

Player 每秒發送一次 `player.playing`；Server 轉發為 `song.progress` 給所有 Remote 客戶端。

---

### 8.4 連線行為

1. 客戶端連線後，Server 廣播 `guests.updated`（包含新加入的 guest）給整個房間
2. 客戶端斷線後，Server 再廣播一次 `guests.updated`（已移除該 guest）
3. Remote 的播放控制指令由 Server 轉發給同房間的 Player
4. `reaction.send` 廣播給房間所有人

---

## 9. 資料結構參考

### SongOut / SongDict

```typescript
interface Song {
  id: string;                  // YouTube video ID (11 chars)
  title: string;
  artist?: string;
  duration_sec?: number;
  thumbnail_url?: string;
  processed_at?: string;       // ISO 8601
  play_count: number;
  status: 'pending' | 'downloading' | 'separating' | 'fetching_lyrics'
        | 'aligning' | 'packaging' | 'ready' | 'failed_temp' | 'failed_perm';
  error_message?: string;
  lyrics_source?: string;      // 'amll_ttml'|'netease'|'qq'|'syncedlyrics'|'plaintext_only'|'none'
  lyrics_quality?: string;     // 'official_word'|'official_line'|'whisper_align'|'plaintext'|'none'
  has_timing?: boolean;
}
```

### QueueItemOut / QueueItemDict

```typescript
interface QueueItem {
  id: number;
  room_id: string;
  song_id: string;
  guest_id: string;
  added_at: string;            // ISO 8601
  position: number;
  status: 'pending' | 'processing' | 'playing' | 'done' | 'skipped';
  played_at?: string;
  manually_moved: boolean;
  song?: Song;
  guest?: Guest;
}
```

### GuestOut / GuestDict

```typescript
interface Guest {
  id: string;                  // UUID
  nickname: string;
  avatar_color: string;        // hex color
  is_admin: boolean;
}
```

### RoomOut

```typescript
interface Room {
  id: string;
  name?: string;
  is_default: boolean;
  created_at: string;
  settings?: Record<string, any>;
  has_password: boolean;       // true if password is set; hash never exposed
}
```

### PlaybackState

```typescript
interface PlaybackState {
  playing?: boolean;
  buffering?: boolean;
  ready?: boolean;
  positionSec?: number;
}
```

---

## 10. 錯誤代碼

| HTTP 代碼 | 含義 |
|---|---|
| `400` | 請求參數無效（YouTube URL 格式錯誤等）|
| `401` | 未認證或 JWT 無效/過期 |
| `403` | 無權限（非管理員、房間密碼錯誤）|
| `404` | 資源不存在 |
| `409` | 衝突（房間 ID 重複、隊列已有相同歌曲）|
| `202` | 歌曲尚在處理中（串流端點特有）|
| `503` | 外部服務暫時不可用（YouTube 搜尋）|

**標準錯誤回應格式**
```json
{ "detail": "Human-readable error message" }
```

---

*最後更新：2026-05-11 — M5-T3 部署文檔*
