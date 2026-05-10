# Home KTV — Project Specification

> 這份文件是專案的單一真相來源（single source of truth）。任何架構決策、功能取捨、技術選型都以此為準。
> 修改本文件時請保留語氣與結構，新增章節請更新目錄。
>
> **本專案由 OpenClaw AI Agent 透過 Telegram 接收用戶指令，再呼叫 Claude Code CLI 執行開發。Claude 必須先閱讀 §17 工作流程，再進行任何修改。**

---

## 0. 一句話定義

一個自用的、雲端處理本地播放的、由網頁構成的家庭 KTV 系統。透過手機掃 QR code 點歌，電視瀏覽器播放，所有重運算（YouTube 下載、人聲分離、歌詞對齊）都在遠端伺服器完成。

## 0.1 部署環境（已確定）

| 項目 | 值 |
|---|---|
| 網域 | `bc-verse.com`（既有）→ `ktv.bc-verse.com` |
| 伺服器 OS | Ubuntu Server |
| 開發位置 | **直接在伺服器上開發**（不分本地/遠端） |
| GPU | GTX 1660 Super（6GB VRAM） |
| 公網入口 | Cloudflare Tunnel + Cloudflare Access |
| 麥克風 | 系統不處理，由電視/喇叭硬體混音 |
| 音效輸出 | 完全由瀏覽器負責 |
| GitHub repo | private（之後再考慮 public） |
| 機密保護 | `.env` 檔，列入 `.gitignore` |

## 0.2 認證方式（已確定）

- **管理員密碼**：`BCktv210`（明文存在 `.env` 的 `ADMIN_PASSWORD`，第一次進管理頁要輸入此密碼，之後 cookie 記憶）
- **房間密碼**：每個房間可設密碼，預設 `home` 房的密碼是 `home`
- **訪客流程**：進入房間頁 → 提示輸入房間密碼 → 通過後填暱稱 → 進入
- **Cloudflare Access**：先**不啟用**（因為要讓朋友訪客能進）；只在管理員專用的 `/admin/*` 路徑可選擇啟用

---

## 1. 使用情境（User Stories）

**S1（主要場景）**：晚上想唱歌，打開電視瀏覽器進入 `https://ktv.bc-verse.com/r/home`，輸入房間密碼 `home` 進入。畫面顯示房間 QR code 與待機背景影片。手機掃碼進入點歌頁面，搜尋「五月天 倔強」，點下去。系統處理約 30 秒（已有緩存則秒播），電視上開始播放原 MV + 動態 KTV 字幕，伴奏模式（人聲音量 0%）。

**S2（朋友來家裡）**：朋友來訪。每人用自己手機掃同一個 QR code（自帶 token），免輸入房間密碼，填暱稱即進入。每個人都能搜尋點歌，隊列即時同步顯示在所有手機與電視上。

**S3（重複歌曲）**：上週唱過的歌，這次點下去**立即播放**。伺服器永久保留處理結果。

**S4（不滿意對齊）**：某句字幕慢半拍。在手機上開啟編輯模式，微調該句時間戳，伺服器更新緩存的 .ass 檔，下次播放就是修好的版本。

**S5（控制 Player）**：唱到一半電話響了。手機上點暫停，掛電話後繼續。期間可調人聲混音、調主音量、跳轉進度。

**S6（找不到官方歌詞）**：點了首冷門歌，系統找不到時間軸歌詞。Player 上以「無歌詞模式」播放（伴奏 + MV），同時 Remote 端嘗試從多個歌詞網站抓**純文字歌詞**讓使用者邊看邊唱。若連純文字也找不到，Remote 顯示「請自行搜尋」並提供快捷搜尋連結。

**S7（公平輪唱）**：四個人輪流點歌，系統自動避免同一個人連續播兩首（讓每個人都唱到）。但如果有人手動把自己的歌調整到下一首位置，這個調整會被尊重。

---

## 2. 範圍（Scope）

### 2.1 In Scope

- 一個或多個房間的並行 KTV session（多房間僅由管理員建立）
- YouTube 為主要音樂來源（yt-dlp）
- 自動人聲分離產生伴奏（Demucs）
- 自動同步字幕（華語官方歌詞 + WhisperX forced alignment）
- 找不到時間軸歌詞時的純文字歌詞 fallback
- 動態 .ass 字幕渲染（libass-wasm）
- 多人同時連線、即時同步隊列、訪客模式
- 完整的 Remote 控制功能（見 §6）
- 隊列「插入下一首」「手動排序」「同人不連續自動排程」
- 永久歌曲緩存於伺服器，本地僅短期緩存
- 評分與排行榜功能
- 手動歌詞時間戳微調介面
- 房間/管理員密碼保護
- 錯誤記錄並回報給 OpenClaw

### 2.2 Out of Scope

- 對外公開營運、商業化、多租戶
- 使用者註冊、密碼、付費機制（單純的房間密碼除外）
- 行動 App（純 PWA / 響應式網頁）
- 即時音準評分 → 第二期再考慮
- Spotify 直接播放
- 麥克風訊號處理（殘響、迴音消除等）
- 系統內音效混音（交給瀏覽器/硬體）
- 開機自啟動 Chromium kiosk（手動開瀏覽器即可）

### 2.3 Non-Goals

- **不追求商業 KTV 機器的完美音質**——伴奏品質取決於 Demucs，能用即可
- **不追求歌詞 100% 正確**——目標 85-95% 正確，剩下用手動編輯補
- **不追求秒級首播**——首次處理新歌可接受 30 秒到 5 分鐘等待

---

## 3. 系統架構

### 3.1 部署拓樸

```
[ 使用者裝置 ]                                [ Ubuntu 伺服器 ]
  電視/筆電瀏覽器 ──┐                        ┌─ FastAPI (ASGI)
                    │                        ├─ SQLite + WAL
  手機瀏覽器 ───────┼──→ Cloudflare Tunnel ─→├─ asyncio 任務隊列
                    │                        ├─ /data/media/（永久儲存）
  其他手機 ────────┘                        └─ Demucs / WhisperX (CUDA)
                                                GTX 1660 Super, 6GB VRAM

[ Telegram ] ─→ [ OpenClaw ] ─→ [ Claude Code CLI ] ─→ 修改專案 + commit + push
                     ↓
              SOUL.md / HEARTBEAT.md
              （跨 session 記憶）
```

### 3.2 主要元件

| 元件 | 技術 | 職責 |
|---|---|---|
| API Gateway | FastAPI | REST + WebSocket，所有用戶端入口 |
| 資料層 | SQLite + SQLAlchemy 2.0 | 房間、隊列、歌曲緩存、使用者偏好、統計 |
| 任務佇列 | asyncio.Queue + Background Task | 媒體處理 pipeline |
| Pipeline Workers | Python 子模組 | yt-dlp / Demucs / 歌詞抓取 / WhisperX |
| 媒體儲存 | 本機 `/data/media/` | 永久保存處理結果 |
| 串流 | FastAPI StaticFiles + HLS 切片 | 把媒體串給瀏覽器 |
| Player Web | Next.js + TypeScript | 大螢幕顯示頁 |
| Remote Web | Next.js + TypeScript | 手機遙控頁 |
| Admin Web | Next.js（同 app 不同路由） | 管理員專用，建房間、清緩存等 |
| 公網入口 | Cloudflare Tunnel | 免開 port、自動 SSL |

### 3.3 GPU 約束（GTX 1660 Super, 6GB）

這張卡夠用但要謹慎安排：

- **Demucs htdemucs_ft**：FP16 模式可在 6GB 跑，一首 4 分鐘約 15-30 秒
- **WhisperX large-v3**：6GB 邊緣，可能要降到 medium 或 small
- **同時跑兩個任務**：會 OOM，必須序列化處理
- **建議**：所有 GPU 任務透過單一 worker queue 串接，一次只跑一個

**使用者狀態未確認**：NVIDIA driver、CUDA、cuDNN 是否已安裝。
- M1-T0 開機檢查：Claude 第一個 task 自動偵測，沒裝的話自動安裝（會在 SETUP.md 留下執行記錄）

詳見 §7 Pipeline。

### 3.4 Pipeline 流程

```
使用者點歌 (YouTube URL or 搜尋結果)
  ↓
查緩存 (by youtube_id)
  ├─ 命中 → 直接加入隊列，狀態 = ready
  └─ 未命中 → 加入處理隊列，狀態 = pending
       ↓
    ① yt-dlp 下載影片+音訊（CPU + 網路）
       ↓
    ② Demucs 分離人聲與伴奏（GPU 序列化）
       ↓
    ③ 並行：
       ├─ 先查 AMLL TTML DB → NetEase → QQ → syncedlyrics
       └─ 都找不到 → 退到「純文字歌詞」抓取（不送對齊）
       ↓
    ④ 若有時間軸歌詞 → WhisperX forced alignment（GPU 序列化）
       若只有純文字 → 跳過對齊，標記為 no_timing
       若完全找不到 → 標記為 no_lyrics
       ↓
    ⑤ LRC → ASS 轉換（加上 \k 卡拉OK tag）
       ↓
    ⑥ FFmpeg 切 HLS（影片 + 雙音軌）
       ↓
    ⑦ 寫入緩存資料庫，狀態 = ready
       ↓
    透過 WebSocket 通知所有連線中的 client
```

每階段都更新 progress（0-100），Remote 端能看到「Demucs 處理中 60%」這種訊息。

### 3.5 預載策略

- **「當前歌一開始播」就觸發下兩首的處理**（不是播完才預載）
- 預載順序：當前 + 1、當前 + 2
- 如果 GPU 任務排隊塞車，至少把 yt-dlp 下載先做完（CPU 任務）
- HLS 開頭幾段優先傳給瀏覽器
- **目標**：歌與歌之間的切換 < 2 秒

---

## 4. 資料模型

### 4.1 主要 Table（SQLite）

```sql
-- 處理過的歌曲緩存（永久保存）
CREATE TABLE songs (
  id              TEXT PRIMARY KEY,        -- youtube_id
  title           TEXT NOT NULL,
  artist          TEXT,
  duration_sec    INTEGER,
  thumbnail_url   TEXT,
  processed_at    TIMESTAMP NOT NULL,
  last_played_at  TIMESTAMP,
  play_count      INTEGER DEFAULT 0,
  files JSON,    -- { video, vocal, instrumental, lyrics_lrc, lyrics_ass, lyrics_text, hls_manifest }
  lyrics_source   TEXT,        -- 'amll_ttml'|'netease'|'qq'|'musixmatch'|'lrclib'|'whisper'|'plaintext_only'|'none'
  lyrics_quality  TEXT,        -- 'official_word'|'official_line'|'whisper_align'|'plaintext'|'none'
  has_timing      BOOLEAN,     -- 是否有時間軸字幕
  metadata JSON
);

-- 房間（僅管理員可建）
CREATE TABLE rooms (
  id              TEXT PRIMARY KEY,    -- 'home' 預設、其他自訂
  name            TEXT,
  password_hash   TEXT,            -- bcrypt 雜湊（如果有設密碼）
  is_default      BOOLEAN DEFAULT FALSE,
  created_at      TIMESTAMP NOT NULL,
  created_by      TEXT,                -- admin guest_id
  settings JSON
);

-- 訪客（簡單，無認證）
CREATE TABLE guests (
  id            TEXT PRIMARY KEY,  -- UUID
  nickname      TEXT NOT NULL,
  avatar_color  TEXT,
  is_admin      BOOLEAN DEFAULT FALSE,
  first_seen    TIMESTAMP NOT NULL,
  last_seen     TIMESTAMP NOT NULL
);

-- 隊列
CREATE TABLE queue_items (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  room_id         TEXT NOT NULL,
  song_id         TEXT NOT NULL,
  guest_id        TEXT NOT NULL,
  added_at        TIMESTAMP NOT NULL,
  position        INTEGER NOT NULL,
  status          TEXT NOT NULL,
  played_at       TIMESTAMP,
  manually_moved  BOOLEAN DEFAULT FALSE  -- 被手動排序過，公平輪唱演算法不再動它
);

-- 評分與統計
CREATE TABLE play_history (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  song_id         TEXT NOT NULL,
  guest_id        TEXT NOT NULL,
  room_id         TEXT NOT NULL,
  played_at       TIMESTAMP NOT NULL,
  duration_sec    INTEGER,
  rating          INTEGER,
  reactions JSON
);

-- 收藏夾
CREATE TABLE favorites (
  guest_id    TEXT NOT NULL,
  song_id     TEXT NOT NULL,
  added_at    TIMESTAMP NOT NULL,
  PRIMARY KEY (guest_id, song_id)
);

-- 錯誤日誌（記錄並回報給 OpenClaw）
CREATE TABLE error_log (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  occurred_at   TIMESTAMP NOT NULL,
  category      TEXT,            -- 'pipeline'|'api'|'frontend'|'system'
  severity      TEXT,            -- 'info'|'warning'|'error'|'critical'
  message       TEXT NOT NULL,
  context JSON,                  -- stack trace, song_id, etc.
  resolved_at   TIMESTAMP,
  resolution    TEXT             -- 解決方式說明
);
```

### 4.2 緩存策略

- **預設保留期**：2 年未播放才考慮清理
- 永遠不刪除**收藏中**的歌
- 永遠不刪除**最常播放 Top 200** 的歌
- 磁碟空間低於 10% 才觸發 LRU 清理
- `/admin/cache` 頁面手動管理

### 4.3 隊列排序演算法

**公平輪唱（Fair Rotation）**：

```
新歌加入隊列時：
  if 加入位置是「end」（預設）:
      套用 fair rotation：
          找出在現有隊列中最後一個由「同 guest_id」點的位置 P
          新歌位置 = max(P + N, 隊尾)，N = 連線中人數的一半
      if 該位置上原本有歌（無 manually_moved 標記） → 它往後挪
  if 加入位置是「next」（插播）:
      直接插到 currently_playing + 1
      不參與 fair rotation
  if 使用者拖曳排序某首歌:
      該歌設 manually_moved = TRUE
      之後的 fair rotation 不會再移動它
```

**例子**：A、B、C 三人，A 已點 [A1]。順序加入 [A2, B1, A3, C1]：

不啟用 fair rotation：`[A1, A2, B1, A3, C1]`
啟用 fair rotation：`[A1, B1, A2, C1, A3]`（A 的歌自動間隔）

但若使用者手動把 A3 拖到第 2 位：`[A1, A3*, B1, A2, C1]`，A3 的標記讓它不再被自動調整。

---

## 5. Player Web 頁面

### 5.1 視覺設計總覽

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│              [背景影片區 / 原 MV 全螢幕播放區]                    │
│                                                                 │
│                                                                 │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │                                                         │   │
│   │           動態 KTV 字幕（libass 渲染層）                  │   │
│   │           當前句逐字變色 + 上方下一句預覽                  │   │
│   │                                                         │   │
│   └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────┐                                          ┌──────┐     │
│  │ QR   │  下一首：周杰倫 - 晴天 (小明點的)         │ Logo │     │
│  │ Code │  隊列：5 首待播                          │      │     │
│  └──────┘                                          └──────┘     │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 三種狀態畫面

#### 5.2.1 待機畫面（無播放）
- **背景**：循環播放氛圍影片（夜景、星空、極光等可設定）
- **中央**：大型房間 QR code + 房間名稱 + 連線網址
- **右上角**：時鐘 + 連線中人數列表
- **左下角**：「等待點歌中…」提示
- **底部**：滾動跑馬燈顯示「最近熱門」「您可能想唱」推薦

#### 5.2.2 處理中畫面
- 顯示當前處理進度
- 進度條（下載 → 分離人聲 → 抓歌詞 → 對齊 → 完成）
- 旁邊顯示「您可以先聊個天 / 喝口水」
- 隊列列表浮現

#### 5.2.3 播放中畫面（核心）
- **影片層**：原 YouTube MV 全螢幕播放，靜音
- **字幕層**：libass-wasm 動態 KTV 效果
  - **有時間軸**：當前句逐字變色，上下句預覽
  - **無時間軸（純文字）**：靜態大字顯示完整歌詞，使用者自行對齊
  - **完全沒歌詞**：底部顯示「無歌詞 - 請參考 Remote 自行搜尋」
- **左上角小資訊條**：歌名、演唱者、點歌人暱稱
- **右上角**：靜音/人聲音量/移調指示
- **底部進度條**：自動隱藏
- **小型隊列預覽**：右下角，可縮起

### 5.3 互動

Player 是顯示器，幾乎不接受直接操作。例外：
- 點擊畫面任意處 → 隱藏/顯示資訊條
- ESC → 退出全螢幕
- 雙擊 → 切換靜音

### 5.4 視覺主題（顏色策略）

**Player 預設**：暗色（穩定，不會出問題）。

**主題清單**（Remote 可切換）：
- **預設暗色**：深灰底、字幕白底黑邊、淺紫漸層當前句
- **派對**：彩虹漸層、字幕跳動動畫
- **典雅**：深藍底、字幕霧白、極簡
- **復古**：仿舊式 KTV 機介面、低彩度

**亮色主題不做**——大螢幕 KTV 場景幾乎不需要亮色，避免 libass 在亮背景下的文字可讀性問題。

### 5.5 行動裝置 Player 適配

雖然主要場景是電視，但 Player 頁面要能在手機/平板正常顯示：
- 響應式：手機直立模式時字幕區佔上 1/3
- libass-wasm 在手機上自動降低 renderAhead 數量（節省記憶體）
- 觸控全螢幕請求 + Wake Lock

---

## 6. Remote Web 頁面

### 6.1 整體佈局

底部 Tab Bar 切換四個分頁：**正在播放 / 隊列 / 搜尋 / 房間**

**配色**：暗色為主，跟隨系統偏好（`prefers-color-scheme`）。

### 6.2 「正在播放」頁

- 大張封面（YouTube 縮圖，模糊放大當背景）
- 歌名、演唱者、點歌人
- **進度條**：可拖曳 seek
- **主控按鈕**：⏮️ ⏯️ ⏭️ 🔁
- **音量滑桿**（主音量 + 人聲音量）
- **進階控制**（可摺疊）：移調、速度、字幕設定
- **本首歌動作**：⭐ 收藏 / 🚫 跳過 / 🔁 加回隊列 / ✏️ 編輯歌詞時間
- **歌詞檢視**：當前歌的完整歌詞（時間軸或純文字皆可），高亮當前句
- **表情反應**：點 🔥 / 👏 / 😂 等飄上 Player

### 6.3 「隊列」頁

- 列表顯示：縮圖、歌名、演唱者、點歌人頭像、處理狀態
- **拖曳**改變順序（觸發 manually_moved 標記）
- **左滑**：刪除 / **插播（移到下一首位置）**
- **點擊歌曲**：展開細節
- **頂部**：「清空隊列」「我的隊列」「shuffle」按鈕
- **隊列為空時**：顯示推薦

### 6.4 「搜尋」頁

- 大型搜尋框（自動聚焦、貼上連結自動偵測）
- **頂部 Tab**：YouTube / 我的收藏 / 歷史 / 排行榜 / 直接貼網址
- **搜尋結果**：縮圖、歌名、頻道、時長
  - **緩存命中標記**：綠色「⚡ 立即」
  - **點擊** = 加入隊列尾端
  - **長按**：選單（**插播下一首** / 加入收藏 / 查看細節）
- **本地搜尋**：所有處理過的歌可直接搜尋
- **語音搜尋**（Web Speech API）

### 6.5 「房間」頁

- **連線中的人**列表
- **暱稱修改**
- **本房間 QR code**（含 token，朋友掃了免輸入房間密碼）
- **歡樂統計**：今晚已唱 N 首、最熱門的歌、唱最多的人
- **設定**：字幕樣式、Player 主題、待機影片
- **進階**：強制重整 Player、系統狀態（GPU 使用率、處理隊列）
- **登出/切換房間**
- **管理員專屬**：建立新房間、跳到 /admin、查看錯誤日誌

### 6.6 訪客流程

第一次進入：
1. 顯示房間名稱 + 「請輸入房間密碼」（或從 QR code 帶 token 略過此步）
2. 通過密碼後 → 要求填暱稱
3. 自動分配頭像顏色
4. 寫入 LocalStorage（guest_id + nickname + room_token）
5. 進入主界面

下次再進：直接還原身份。

### 6.7 純文字歌詞 Fallback UI

當歌曲處理完但 `has_timing = false`：
- Remote「正在播放」頁的歌詞區顯示靜態純文字歌詞，可手動捲動
- 提供「來源：Mojim / KKBOX / 五大唱片…」標示
- 完全找不到時，顯示快捷搜尋連結：
  - `[Google] [Mojim] [Genius] [LyricFind]`，皆已預填歌名

---

## 7. 處理 Pipeline 細節

### 7.1 yt-dlp

- 使用 Python lib 模式
- 影片格式偏好：1080p H.264 MP4
- 音訊格式：bestaudio → wav
- 失敗重試：3 次、指數退避
- Cookie 支援（某些影片需要登入）

### 7.2 Demucs（人聲分離）

- 模型：`htdemucs_ft`
- **GPU 模式：FP16，1660 Super 6GB 可跑**
- 必須**序列化**（同一時間只跑一個 Demucs job）
- 輸出：`vocals.wav` + `no_vocals.wav`

### 7.3 歌詞抓取（多源 fallback）

**第一階段 — 時間軸歌詞**：
1. AMLL TTML DB（用 NetEase ID 查 → 最佳華語逐字）
2. NetEase Cloud Music API（線級 LRC，華語覆蓋最好）
3. QQ Music API（QRC 逐字）
4. syncedlyrics（Musixmatch / LRCLIB / Megalobiz）

**第二階段 — 純文字歌詞 fallback**（時間軸全失敗時）：
1. Mojim（魔鏡歌詞網，華語覆蓋最好）
2. KKBOX 公開歌詞頁
3. Genius
4. 直接 Google search 第一個結果頁解析

**第三階段 — 都失敗**：
- 標記 `lyrics_source = 'none'`
- Player 顯示「無歌詞」
- Remote 提供搜尋連結

### 7.4 WhisperX 強制對齊

- 拿到 LRC（線級）→ 對齊到字級
- 中文以**字**為單位
- **GPU 模式**，必須序列化
- 模型：先用 medium 試試 6GB 是否夠，不夠降到 small
- 失敗 fallback：保留線級對齊，字級平均分配

### 7.5 LRC → ASS 轉換

- 預設樣式：黑體粗體、白色填充、深色描邊
- \k 標籤以厘秒為單位
- 雙行顯示：當前句 + 預覽下一句
- 動畫：淡入 100ms、變色 50ms

### 7.6 HLS 切片

- 6 秒一段
- 影片用原 YouTube
- 音訊**雙軌獨立串流**（伴奏 + 人聲），瀏覽器端 Web Audio API 混音
- 字幕**獨立**傳遞給前端

### 7.7 GPU 任務序列化

```python
# 偽碼
gpu_lock = asyncio.Lock()

async def gpu_task(name, fn, *args):
    async with gpu_lock:
        log(f"GPU 開始 {name}")
        result = await fn(*args)
        log(f"GPU 完成 {name}")
        return result

# 使用：
await gpu_task("demucs", run_demucs, audio_path)
await gpu_task("whisperx", run_whisperx, audio_path, lrc)
```

CPU 任務（yt-dlp、ffmpeg、歌詞抓取）不受此限制。

---

## 8. WebSocket 訊息協議

### 8.1 從 Server 推送

```ts
type ServerEvent =
  | { type: 'queue.updated'; queue: QueueItem[] }
  | { type: 'song.started'; song: Song; queueItem: QueueItem }
  | { type: 'song.progress'; positionSec: number }
  | { type: 'song.ended'; queueItemId: number }
  | { type: 'song.processing'; queueItemId: number; stage: string; percent: number }
  | { type: 'guests.updated'; guests: Guest[] }
  | { type: 'playback.state'; state: PlaybackState }
  | { type: 'reaction'; emoji: string; from: GuestId }
  | { type: 'system.error'; message: string }
```

### 8.2 從 Remote 發送

```ts
type ClientCommand =
  | { type: 'queue.add'; youtubeId: string; position?: 'end'|'next' }
  | { type: 'queue.remove'; queueItemId: number }
  | { type: 'queue.reorder'; queueItemIds: number[] }
  | { type: 'playback.play' }
  | { type: 'playback.pause' }
  | { type: 'playback.skip' }
  | { type: 'playback.replay' }
  | { type: 'playback.seek'; positionSec: number }
  | { type: 'playback.setVolume'; main?: number; vocal?: number }
  | { type: 'playback.setPitch'; semitones: number }
  | { type: 'playback.setSpeed'; rate: number }
  | { type: 'reaction.send'; emoji: string }
  | { type: 'lyrics.edit'; songId: string; ass: string }
  | { type: 'guest.updateNickname'; nickname: string }
```

### 8.3 從 Player 發送

```ts
type PlayerStatus =
  | { type: 'player.ready' }
  | { type: 'player.playing'; positionSec: number }
  | { type: 'player.buffering' }
  | { type: 'player.error'; error: string }
```

---

## 9. 評分與排行榜

### 9.1 自動統計

- 每首歌每次播放完計入 `play_history`
- 唱完 ≥ 80% 才算「完成」
- 排行榜：
  - **本月最熱門**
  - **歷史經典**
  - **個人最愛**
  - **新發現**

### 9.2 互動評分

- 唱完跳出「再給星評」（1-5 星，可跳過）
- 表情反應即時飄過 Player 畫面
- 「合唱模式」：多人點同首歌不重複處理，顯示「N 人合唱」

---

## 10. 安全與部署

### 10.1 機密管理

`.env` 結構（**絕對不上 GitHub**）：

```bash
# === 認證 ===
ADMIN_PASSWORD=BCktv210
ADMIN_COOKIE_SECRET=<隨機產生 32 字元，第一次部署時填>

# === 部署 ===
PUBLIC_BASE_URL=https://ktv.bc-verse.com
LOCAL_PORT=8000
DATA_DIR=/data/ktv

# === Cloudflare（Tunnel 帳號相關，由 SETUP.md 引導填入）===
CF_TUNNEL_NAME=ktv
CF_TUNNEL_UUID=<填入>
CF_DOMAIN=bc-verse.com
CF_SUBDOMAIN=ktv

# === GPU ===
ENABLE_GPU=true
WHISPERX_MODEL=medium  # 1660 Super 6GB 預設

# === 第三方 API（如有）===
# YOUTUBE_COOKIES_PATH=/etc/ktv/yt-cookies.txt  # 可選
```

`.gitignore` 必須包含：`.env`, `.env.*`, `!.env.example`, `data/`, `*.db`, `*.db-wal`, `*.db-shm`, `node_modules/`, `__pycache__/`, `.venv/`

### 10.2 Cloudflare 設定（手動步驟，由 SETUP.md 詳列）

- **Tunnel**：`cloudflared tunnel create ktv` → 連到本機 FastAPI port
- **DNS**：`ktv.bc-verse.com` CNAME 到 tunnel
- **Access**：**先不啟用**——朋友訪客需要進入。日後如要保護 `/admin/*` 再加。

### 10.3 內網管理界面

`/admin` 頁面（需輸入 ADMIN_PASSWORD）：
- 緩存管理
- 處理隊列重啟
- 系統狀態監控
- **建立新房間 + 設密碼**
- 邀請朋友（產生臨時房間連結含 token）
- **錯誤日誌檢視 + 標記已解決**

### 10.4 備份

- SQLite 每天自動備份到另一目錄
- 媒體檔案就地，不備份
- 收藏夾、歷史、設定可手動 export JSON

---

## 11. 技術棧確定清單

| 層 | 選型 | 備選 |
|---|---|---|
| 後端框架 | FastAPI | Litestar |
| ORM | SQLAlchemy 2.0 + Alembic | - |
| 任務 | asyncio.Queue + BackgroundTasks | RQ |
| 前端框架 | Next.js 15 (App Router) | SvelteKit |
| 前端狀態 | Zustand + React Query | - |
| UI Lib | Tailwind + shadcn/ui | - |
| Type hints | `Optional[X]` 風格（穩健派） | - |
| 字幕渲染 | JavascriptSubtitlesOctopus | - |
| HLS | hls.js | - |
| 套件管理 | uv (Python) + pnpm (前端) | - |
| 容器 | Docker Compose | - |
| Tunnel | cloudflared | - |
| 錯誤追蹤 | console + 檔案 log + DB 表 | （不接 Sentry） |

---

## 12. 已知風險與決策記錄

- **R1**：WhisperX 對中文 alignment 邊界處理需自寫
- **R2**：YouTube 偶爾改機制讓 yt-dlp 失效，需自動更新機制
- **R3**：1660 Super 6GB 對 WhisperX large 可能不夠，預設 medium
- **R4**：libass-wasm 在某些手機瀏覽器效能差
- **R5**：Cloudflare Tunnel 對 WebSocket 支援良好，但長連線可能斷，需自動重連
- **R6**：純文字歌詞抓取依賴第三方網站 HTML 結構，可能會因網站改版失效
- **R7**：管理員密碼明文存 `.env`——自用範圍可接受，因為伺服器只有用戶能存取

---

## 13. 額外功能（已加入需求）

- ✅ 隊列插播（加入下一首位置）
- ✅ 手動排序（拖曳）
- ✅ 同人不連續自動排程（fair rotation），手動排序的歌不受影響
- ✅ 純文字歌詞 fallback
- ✅ 房間/管理員密碼保護
- ✅ 錯誤記錄與回報

---

## 14. 待二期考慮的功能

- 歌單系統（主題歌單一鍵加入）
- B 站 / 本地上傳作為補充來源
- 派對遊戲（猜歌、接龍）
- 雙語字幕（華語 + 拼音 / 英文）
- 即時音準評分
- 行動裝置作為 Player 的全功能優化
- 開機自啟動 Chromium kiosk

---

## 15. 文件版本

- v0.1 (2026-05-09)：初始版本
- v0.2 (2026-05-09)：環境確定（bc-verse.com、1660 Super）、純文字歌詞 fallback、公平輪唱、隊列插播、Agent 工作流程
- v0.3 (2026-05-09)：所有問題回完，密碼策略、type hint 風格、配色、錯誤管理、OpenClaw 整合方式
- v0.4 (2026-05-09)：新增 §21 Resilience & Timeout 策略，補完 timeout、watchdog、recovery、idempotency

---

## 16. 專案目錄結構

```
home-ktv/
├── CLAUDE.md                    ← 本文件（專案規格）
├── README.md
├── .gitignore
├── .env.example                 ← 範本，可上 git
├── docker-compose.yml
│
├── docs/
│   ├── PROGRESS.md              ← 進度記錄（每個 task 完成後更新）
│   ├── DECISIONS.md             ← 架構決策記錄（ADR）
│   ├── SETUP.md                 ← 用戶手動設定步驟清單
│   ├── ERRORS.md                ← 已知錯誤與解決方式
│   └── API.md                   ← API/WebSocket 協議完整版
│
├── openclaw-skill/
│   └── SKILL.md                 ← 給 OpenClaw 用的 skill，定義 KTV 專案管理流程
│
├── backend/
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── src/ktv/
│   │   ├── __init__.py
│   │   ├── main.py              ← FastAPI app
│   │   ├── config.py
│   │   ├── db/
│   │   │   ├── models.py
│   │   │   ├── schemas.py
│   │   │   └── migrations/
│   │   ├── api/
│   │   │   ├── rooms.py
│   │   │   ├── queue.py
│   │   │   ├── songs.py
│   │   │   ├── auth.py          ← 房間/管理員密碼
│   │   │   └── ws.py
│   │   ├── pipeline/
│   │   │   ├── ytdlp.py
│   │   │   ├── demucs.py
│   │   │   ├── lyrics/
│   │   │   │   ├── amll.py
│   │   │   │   ├── netease.py
│   │   │   │   ├── qq.py
│   │   │   │   ├── plaintext.py
│   │   │   │   └── manager.py
│   │   │   ├── whisperx_align.py
│   │   │   ├── lrc_to_ass.py
│   │   │   └── hls.py
│   │   ├── queue/
│   │   │   ├── fair_rotation.py
│   │   │   └── manager.py
│   │   ├── errors.py            ← 錯誤記錄與回報邏輯
│   │   └── utils/
│   └── tests/
│
├── frontend/
│   ├── package.json
│   ├── pnpm-lock.yaml
│   ├── next.config.js
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx             ← 首頁，導向 home 房間
│   │   ├── r/[roomId]/
│   │   │   ├── player/page.tsx
│   │   │   └── remote/page.tsx
│   │   └── admin/
│   ├── components/
│   │   ├── player/
│   │   ├── remote/
│   │   └── shared/
│   ├── lib/
│   │   ├── ws.ts
│   │   ├── api.ts
│   │   └── stores/
│   └── public/
│
├── data/                        ← gitignored
│   ├── ktv.db
│   └── media/
│       └── <youtube_id>/
│           ├── video.mp4
│           ├── vocal.wav
│           ├── instrumental.wav
│           ├── lyrics.lrc
│           ├── lyrics.ass
│           ├── lyrics.txt
│           └── hls/
│
├── scripts/
│   ├── backup.sh
│   ├── cleanup_cache.py
│   ├── healthcheck.sh
│   └── gpu-setup-check.sh       ← M1-T0 偵測 + 自動安裝 NVIDIA driver/CUDA
│
└── deploy/
    ├── Dockerfile.backend
    ├── Dockerfile.frontend
    ├── nginx.conf
    └── cloudflared.yml
```

---

## 17. 工作流程（OpenClaw + Claude Code 整合）

> **本章節是 OpenClaw 與 Claude Code 協作的真相來源。Claude 必須在每次 session 開始時遵循 §17.7 的 self-check。**

### 17.1 角色分工

| 角色 | 工具 | 職責 |
|---|---|---|
| **使用者** | Telegram | 透過自然語言下指令、確認進度、做使用者驗收 |
| **OpenClaw** | gateway 在伺服器上跑 | 接收 Telegram 訊息 → 規劃 → 呼叫 Claude Code CLI → 回報狀態 |
| **Claude Code** | CLI（被 OpenClaw 呼叫） | 實際寫 code、跑測試、commit、push |
| **PROGRESS.md** | 檔案 | 跨 session 共享記憶（OpenClaw 與 Claude 都讀都寫） |
| **OpenClaw SOUL.md** | 檔案 | OpenClaw 自己的長期記憶與此專案相關設定 |
| **HEARTBEAT.md** | 檔案 | OpenClaw 跑長任務時的 scope 與 budget 限制 |

### 17.2 Session 開始時（Claude 必做）

1. **讀取 `docs/PROGRESS.md`** 了解上次進度
2. **讀取 `docs/DECISIONS.md`** 了解既有架構決策
3. **讀取 `docs/ERRORS.md`** 了解未解決的錯誤
4. **讀取本文件 §16**（目錄結構）和 §11（技術棧）
5. **檢查 git 狀態**：`git status` 看是否有未提交工作
6. **檢查是否有 wip/* 分支需要繼續**
7. **判斷下一個 task**：從 PROGRESS.md 的 "Next Up" 區塊取一個

### 17.3 Task 進行中

1. **每個 task 必須有對應的 git branch**：`feature/M2-T1-fastapi-skeleton`
2. **每個 task 必須有 atomic commit**，格式：

   ```
   [M2-T1] feat(api): add FastAPI skeleton with health check

   - Set up uv project structure
   - Add FastAPI with lifespan
   - Add /health and /version endpoints
   - Add basic Pydantic settings

   Refs: PROGRESS.md M2-T1
   ```

3. **每個 task 必須有測試**，至少：
   - 單元測試覆蓋核心邏輯
   - 整合測試覆蓋 API endpoint
   - **測試通過才能標記完成**

4. **遇到需要使用者手動操作的事**：
   - 立即停下來
   - 在 PROGRESS.md「⚠️ User Action Required」區塊加入步驟
   - 在 `docs/SETUP.md` 詳細記錄步驟（含完整命令）
   - OpenClaw 收到後**透過 Telegram 通知使用者**

5. **遇到錯誤**：
   - 寫入 `error_log` table（如果 DB 已建好）
   - 寫入 `docs/ERRORS.md`
   - 在 commit message 標註 `[error]`
   - **嘗試自動解決**：上網查、改 code、換實作
   - 解決不了 → 標記 blocked，在 PROGRESS.md「Blocked」區塊登記，OpenClaw 通知使用者

### 17.4 Task 完成時

1. **跑全套測試**：`uv run pytest backend/` + `pnpm --filter frontend test`
2. **更新 PROGRESS.md**：把該 task 從 "In Progress" 移到 "Done"
3. **如果有架構決策變更**：寫一條 ADR 進 `docs/DECISIONS.md`
4. **打 git tag**：`v0.M2.T1` 格式
5. **push 到 GitHub** (private repo)
6. **OpenClaw 透過 Telegram 通知使用者**：「M2-T1 完成，✅ 可以驗收」
7. **使用者驗收**有兩種方式（兩種都要）：
   - 在 PROGRESS.md 寫 demo 摘要
   - 啟動服務（如已可啟動）讓使用者親自試
   - 使用者在 Telegram 回「✅」表示通過，OpenClaw 把 task 真正關閉

### 17.5 Rate Limit 或 Session 中斷時

OpenClaw 偵測到 Claude session 中斷時：

1. **任何已寫的 code commit 進 WIP branch**：
   ```
   git checkout -b wip/M2-T1-interrupted
   git add -A
   git commit -m "WIP: M2-T1 interrupted at <step>, see PROGRESS.md"
   git push origin wip/M2-T1-interrupted
   ```

2. **更新 PROGRESS.md** 的 "In Progress" 區塊：
   - 當前 task 卡在哪一步
   - 已完成的子步驟（勾選清單）
   - 待繼續的子步驟
   - 任何需要記住的 context

3. **OpenClaw 等待 rate limit 解除**，然後喚起新的 Claude session 接續

4. **絕對不能讓 task 在「程式不可運行」的狀態下中斷**——寧可 commit 一個明顯標記 TODO 的 stub。

### 17.6 PROGRESS.md 格式

```markdown
# Project Progress

## Status: [M2 — API 骨架]

Last updated: 2026-05-09 22:35
Current Claude session ID: abc123
OpenClaw heartbeat: alive (2026-05-09 22:34)

---

## Done

- [x] M0: 環境準備 (commit a1b2c3d, tag v0.M0, 2026-05-09)
   - ✅ User checkpoint: 已確認伺服器 ready
- [x] M1-T1: 專案 scaffolding (commit b2c3d4e, tag v0.M1.T1, 2026-05-09)
- [x] M1-T2: yt-dlp wrapper (commit d4e5f6g, tag v0.M1.T2, 2026-05-09)
   - ✅ User checkpoint: 已驗證下載功能

---

## In Progress

### M2-T1: FastAPI skeleton
Started: 2026-05-09 21:00
Branch: feature/M2-T1-fastapi-skeleton

Sub-tasks:
- [x] uv project init
- [x] FastAPI app with lifespan
- [x] /health endpoint
- [ ] /version endpoint  ← 中斷在此
- [ ] Pydantic settings module
- [ ] Test: TestClient for /health
- [ ] Test: TestClient for /version

Context for next session:
- Decision: using `uvicorn[standard]` for WS support later
- TODO: BaseSettings 要從 .env 讀取 PUBLIC_BASE_URL

---

## Next Up

- [ ] M2-T2: SQLite + SQLAlchemy 模型定義
- [ ] M2-T3: WebSocket basic gateway

---

## ⚠️ User Action Required

(無)

---

## Blocked

(無)

---

## Recent Errors (見 docs/ERRORS.md 完整)

- 2026-05-09 21:15: yt-dlp DRM 影片下載失敗 → 改用 cookie 模式 → 已解決
```

### 17.7 Claude session-start self-check

```
□ 我有讀過 PROGRESS.md 嗎？
□ 我知道現在的 In Progress task 是什麼嗎？
□ 我有 pull 最新 main 嗎？
□ 我有檢查是否有 wip/* branch 需要繼續嗎？
□ 我有看「⚠️ User Action Required」清單嗎？
□ 我有看 ERRORS.md 嗎？
□ 我有確認 GPU、磁碟、cloudflared 等服務狀態嗎？
□ 我了解這個 task 完成時要怎麼通知 OpenClaw 嗎？
```

通過 checklist 才能開始寫 code。

### 17.8 OpenClaw SKILL.md（給 OpenClaw 自己看）

`openclaw-skill/SKILL.md` 內容（M0 階段建立）會包含：
- 此專案的所在路徑
- 如何呼叫 Claude Code CLI
- 如何讀寫 PROGRESS.md
- Telegram 訊息模板（task 完成、需要驗收、錯誤通知）
- 如何處理 rate limit

這個 SKILL.md 由本專案維護，等於是「告訴 OpenClaw 怎麼管這個專案」的說明書。

---

## 18. 開發里程碑

### M0：專案初始化
- M0-T1: 建立 GitHub repo（**需要使用者操作**）
- M0-T2: 初始化專案目錄、`.gitignore`、`.env.example`
- M0-T3: 建立 `docs/PROGRESS.md`、`DECISIONS.md`、`SETUP.md`、`ERRORS.md` 初版
- M0-T4: 寫 `openclaw-skill/SKILL.md`，讓 OpenClaw 接管
- M0-T5: GPU 環境檢查與安裝（`scripts/gpu-setup-check.sh`）
- M0-T6: Cloudflare Tunnel 預先建立（**需要使用者操作**）
   ✅ 使用者驗收：M0 完成意味著 Telegram → OpenClaw → Claude Code 流程能跑通

### M1：CLI Pipeline（第 1 週）
- M1-T1: 後端專案 scaffolding（uv + FastAPI 空殼）
- M1-T2: yt-dlp wrapper + 測試
- M1-T3: Demucs wrapper + 測試（GPU 序列化）
- M1-T4: 歌詞抓取 manager + 各 source（時間軸 4 個 + 純文字 4 個）
- M1-T5: WhisperX forced alignment + 測試
- M1-T6: LRC → ASS 轉換 + 測試
- M1-T7: 整合 CLI `ktv-process <url>` ✅ 使用者驗收

### M2：API 骨架（第 2 週）
- M2-T1: FastAPI skeleton + 測試
- M2-T2: SQLite 模型 + Alembic
- M2-T3: 認證系統（房間/管理員密碼）
- M2-T4: WebSocket gateway + 訊息協議實作
- M2-T5: 隊列管理 + 公平輪唱演算法 + 測試
- M2-T6: 歌曲緩存 API + 整合 M1 pipeline
- M2-T7: HLS 串流 endpoint
- M2-T8: 整合測試：能 API 點歌、處理、播放 ✅ 使用者驗收

### M3：Player 網頁（第 3 週）
- M3-T1: Next.js scaffolding
- M3-T2: 待機畫面 + QR code
- M3-T3: hls.js 整合
- M3-T4: libass-wasm 字幕層
- M3-T5: WebSocket 接收與狀態同步
- M3-T6: 主題系統（暗色為主，多套切換）
- M3-T7: 完整端到端測試 ✅ 使用者驗收

### M4：Remote 網頁（第 4 週）
- M4-T1: Next.js Remote scaffolding + PWA
- M4-T2: 訪客身份系統 + 房間密碼流程
- M4-T3: 「正在播放」頁完整功能
- M4-T4: 「隊列」頁含拖曳、插播
- M4-T5: 「搜尋」頁 + YouTube 搜尋
- M4-T6: 「房間」頁 + 統計
- M4-T7: 純文字歌詞 UI ✅ 使用者驗收

### M5：多人 + 評分 + 管理（第 5 週）
- M5-T1: 訪客在線顯示
- M5-T2: 表情反應系統
- M5-T3: 評分系統 + play_history
- M5-T4: 排行榜頁
- M5-T5: 管理員頁 + 房間建立 + 錯誤日誌檢視
- M5-T6: 歌詞編輯器 ✅ 使用者驗收

### M6：部署（第 6 週）
- M6-T1: Dockerfile + Compose
- M6-T2: Cloudflare Tunnel 配置（**需要使用者操作**）
- M6-T3: systemd 服務 / 自啟動腳本
- M6-T4: 備份腳本
- M6-T5: 系統健康檢查
- M6-T6: 端到端測試 ✅ 使用者驗收

---

## 19. 待決定的問題（已全部處理）

| # | 問題 | 決定 |
|---|---|---|
| 1 | 域名 | `ktv.bc-verse.com` |
| 2 | GPU | GTX 1660 Super 6GB，所有 GPU 任務序列化，WhisperX 預設 medium |
| 3 | 使用者規模 | 不限制 |
| 4 | 找不到歌詞 | 純文字 fallback，再不行讓使用者自查 |
| 5 | Player 啟動 | 手動開瀏覽器（不做 kiosk） |
| 6 | 音效輸出 | 瀏覽器負責 |
| 7 | 麥克風 | 不在系統內處理 |
| 8 | 預載策略 | 當前歌一播就預載下兩首 |
| 9 | 多房間 | 預設 home 房（密碼 `home`），管理員可建多房間 |
| 10 | 行動 Player | 響應式適配但非主要場景 |
| 11 | GitHub repo | private |
| 12 | 認證 | ADMIN_PASSWORD=`BCktv210`，房間密碼 |
| 13 | Cloudflare 帳號 | 使用者已有，由 SETUP.md 引導 |
| 14 | GPU driver | 由 M0-T5 自動偵測 + 安裝 |
| 15 | OpenClaw 整合 | Telegram → OpenClaw → Claude Code CLI，PROGRESS.md 是長期記憶 |
| 16 | 進度確認 | 雙軌：PROGRESS.md demo + 啟動服務驗收 |
| 17 | Type hints | `Optional[X]` 穩健派 |
| 18 | CSS | Tailwind |
| 19 | 配色 | Player 暗色，Remote 跟隨系統 |
| 20 | 錯誤上報 | DB log + 檔案 log + 回報 OpenClaw + 解決後標記 |
| 21 | 開發位置 | 直接在 Ubuntu 伺服器上 |
| 22 | OpenClaw 能力 | 已知（shell、檔案、瀏覽器、cron、Telegram、跨 session 記憶） |

---

## 20. 下一步（給使用者的）

當你準備開始時，請依照以下順序：

1. 在伺服器上建立空目錄 `/home/<user>/home-ktv`
2. 把這份 CLAUDE.md 放進去
3. 在 GitHub 建立 private repo `home-ktv`，**不要** Initialize with README
4. 透過 Telegram 告訴 OpenClaw：「開始 home-ktv 專案的 M0」
5. OpenClaw 會喚起 Claude Code，從 M0-T1 開始

**啟動前的環境檢查（你可以先做也可以讓 Claude 做）**：
- 伺服器 Python 3.12+：`python3 --version`
- 伺服器 Node.js 20+：`node --version`
- GPU 是否可見：`nvidia-smi`（可能要先裝 driver）
- Docker：`docker --version`
- Git：`git --version`
- Cloudflared：`cloudflared --version`（沒裝沒關係，M0 會處理）

---

## 21. Resilience、Timeout 與恢復策略

> 這一章是專門處理「事情出錯時怎麼辦」的章節。涵蓋 timeout、watchdog、idempotency、recovery、rate limit 退避、git 競爭、磁碟空間等。

### 21.1 設計原則

1. **永遠假設會出錯**——網路斷、磁碟滿、GPU 當、Claude 被切，都會發生
2. **Idempotent first**——所有 pipeline 階段都能重跑而不破壞狀態
3. **Heartbeat 證明活著**——靜默 = 死亡，必須定期發訊號
4. **Watchdog 補刀**——獨立巡邏程式檢查 staleness 並修復
5. **永遠優雅失敗**——壞的歌跳過，不要拖死整個系統
6. **狀態優先於記憶**——所有重要狀態寫入 DB，記憶體歸零也能恢復

### 21.2 Timeout 配置（自用模式：寬鬆）

#### 21.2.1 Pipeline 階段 timeout

| 階段 | Timeout | 重試次數 | 失敗分類 |
|---|---|---|---|
| yt-dlp 下載 | 10 分鐘 | 3 次（指數退避） | temp/perm 自動判斷 |
| Demucs 分離 | 15 分鐘 | 1 次 | temp |
| 歌詞抓取（每個源） | 30 秒 | 1 次 | 跳到下個源 |
| WhisperX 對齊 | 10 分鐘 | 1 次 | temp |
| LRC→ASS 轉換 | 30 秒 | 2 次 | perm（程式 bug） |
| HLS 切片 | 5 分鐘 | 2 次 | temp |
| **單首歌總計** | **15 分鐘**（硬上限） | - | 超過視為 failed_perm 並跳到下一首 |

#### 21.2.2 Task 開發 timeout（給 OpenClaw 監控）

| 訊號 | 觸發條件 | OpenClaw 動作 |
|---|---|---|
| **Stale heartbeat** | PROGRESS.md 1 小時未更新 | 喚起新 Claude session 接管 |
| **Task 超時** | 同 task ID In Progress > 4 小時 | Telegram 警示 + 自動嘗試重啟 |
| **Task 嚴重超時** | 同 task ID > 24 小時 | 標記 stuck，Telegram 通知，等待使用者指示 |

#### 21.2.3 HTTP / 網路 timeout

| 對象 | Connect | Read | 重試 |
|---|---|---|---|
| YouTube (yt-dlp) | 10s | 60s | 3 次 |
| 歌詞 API | 5s | 15s | 1 次（直接跳下個源）|
| Cloudflare Tunnel WS | 自動重連 | - | 無限指數退避 |
| 內部 FastAPI 對 worker | 5s | 30s | 0（呼叫端自行處理）|

#### 21.2.4 用戶端 timeout

- **Player WebSocket**：30 秒沒收到 server ping → 自動重連
- **Remote WebSocket**：同上
- **Player 影片緩衝**：HLS 30 秒沒新分片 → 顯示重試畫面

### 21.3 失敗分類（Two-Tier）

每個失敗都標記為 **temp**（暫時性）或 **perm**（永久性）：

#### Temp（自動退避重試）
- 網路錯誤（timeout、連線拒絕、5xx）
- GPU OOM 或 CUDA 錯誤
- 磁碟暫時 IO 錯誤
- yt-dlp 因 rate limit 失敗
- 處理過程中收到 SIGTERM（重啟）

**處理**：寫入 `error_log`，狀態回到 `pending`，加入重試隊列，**指數退避**：30s → 2min → 10min → 30min → 1hr → 維持 1hr 一輪。**無限重試**，但越來越慢。

#### Perm（標記失敗、跳過）
- 影片不存在 / 私人 / 被刪
- 影片地區封鎖
- yt-dlp 4xx（明確的 not available）
- 解析後檔案損毀（零位元組）
- 超過單首歌總 timeout（15 分鐘）

**處理**：寫入 `error_log`，狀態 → `failed_perm`，從處理隊列移除，在 Remote 顯示「無法處理」。使用者可手動「重試」按鈕強制重試。

#### 失敗後 UI 行為

```
正在播放 [周杰倫 - 晴天]
下一首 → [失敗的歌]：⚠ 處理失敗，跳過。原因：影片地區封鎖
下下首 → [陳奕迅 - 浮誇]：✓ 準備中
```

點失敗的歌可以看詳細錯誤、點重試、或刪除。

### 21.4 State Machine

歌曲處理狀態（`songs.status` + `queue_items.status`）：

```
queued ─→ pending ─→ downloading ─→ separating ─→ fetching_lyrics
                                                      ↓
   ready ←─ packaging ←─ aligning ←──────────────────┘
     ↓
  playing ─→ done
     ↓                       ↑
  skipped                    │
                             │
  失敗時：── failed_temp ─────┘ (回到 pending 重試)
        └── failed_perm        (停留，使用者決定)
        └── interrupted        (server 重啟，啟動時恢復)
        └── stale              (watchdog 偵測超時)
```

**重要**：每個狀態變更都寫 DB（不只記憶體）。

### 21.5 Heartbeat 機制

#### 21.5.1 Claude → PROGRESS.md heartbeat

Claude 在執行 task 期間，**每 5 分鐘必須更新 PROGRESS.md**（即使只是更新 timestamp）。格式：

```markdown
### M2-T1: FastAPI skeleton
Started: 2026-05-09 21:00
Last heartbeat: 2026-05-09 21:35  ← 必須在 5 分鐘內
Branch: feature/M2-T1-fastapi-skeleton
```

如果 Claude 跑長指令（例如 `pnpm install` 5 分鐘），在跑前先寫一條 heartbeat，註明預計多久，例如：

```markdown
Last heartbeat: 2026-05-09 21:30 (running pnpm install, ETA 5min, expected next heartbeat 21:36)
```

#### 21.5.2 OpenClaw watchdog（每 10 分鐘 cron）

OpenClaw 跑這段邏輯：

```
每 10 分鐘：
  讀 PROGRESS.md
  if In Progress 且 Last heartbeat > 60 分鐘前:
      → STALE，喚起新 Claude session
  if In Progress 且 Last heartbeat > 4 小時前:
      → STUCK，Telegram 警示
  if In Progress 且 Last heartbeat > 24 小時前:
      → ABANDON，Telegram 通知，停止自動重試
```

#### 21.5.3 Pipeline → DB heartbeat

每個 pipeline 階段在跑時，每 30 秒更新 `queue_items.last_heartbeat`。

```python
async def with_heartbeat(queue_item_id, fn, *args):
    async def beat():
        while True:
            await asyncio.sleep(30)
            db.update_heartbeat(queue_item_id, now())
    
    beat_task = asyncio.create_task(beat())
    try:
        return await fn(*args)
    finally:
        beat_task.cancel()
```

Watchdog cron 看 `last_heartbeat > 階段 timeout`，視為超時。

### 21.6 Idempotency

每個 pipeline 階段必須是 idempotent 的——重跑不會壞事。

#### 階段設計

```python
async def stage_demucs(song_id):
    output_path = f"/data/media/{song_id}/no_vocals.wav"
    if file_exists(output_path) and is_valid_audio(output_path):
        log.info(f"Demucs already done for {song_id}, skipping")
        return output_path
    # 否則重跑
    return await run_demucs(...)
```

每個階段都這樣寫——先檢查產物是否存在且有效，存在就跳過。

#### 例外：HLS 切片

HLS 分片很多，要嚴格驗證所有分片完整。如果有任何分片缺失，整個 HLS 重切。

### 21.7 重啟恢復策略

#### 21.7.1 Server 啟動腳本

```python
# backend/src/ktv/recovery.py
async def on_startup():
    # 1. 把所有 processing 狀態歌曲重置為 pending
    db.execute("""
        UPDATE songs SET status = 'pending'
        WHERE status IN ('downloading', 'separating', 'fetching_lyrics', 'aligning', 'packaging')
    """)
    db.execute("""
        UPDATE queue_items SET status = 'pending'
        WHERE status = 'processing'
    """)
    
    # 2. 寫入 error_log
    db.log_event('system_restart', f'Recovered {N} interrupted songs')
    
    # 3. 通知連線中的 client（如果有 client 還在）
    await broadcast({'type': 'system.restarted'})
    
    # 4. 啟動 pipeline worker
    asyncio.create_task(pipeline_worker())
```

**為什麼選 pending 重跑而非看檔案**：自用範圍每首歌處理時間 < 15 分鐘，重跑成本可接受。看檔案邏輯複雜（怎麼定義「完整」？分片少一個算不算？），不值得。

#### 21.7.2 systemd 服務

```ini
# /etc/systemd/system/ktv-backend.service
[Unit]
Description=Home KTV Backend
After=network.target nvidia-persistenced.service

[Service]
Type=simple
User=ktv
WorkingDirectory=/home/ktv/home-ktv/backend
ExecStart=/home/ktv/.local/bin/uv run python -m ktv.main
Restart=on-failure
RestartSec=10s
StartLimitBurst=5
StartLimitIntervalSec=300

[Install]
WantedBy=multi-user.target
```

**StartLimitBurst=5**：5 分鐘內重啟超過 5 次就停手，避免無限崩潰循環。

### 21.8 Rate Limit 退避（無限重試）

#### 21.8.1 Claude rate limit

OpenClaw 偵測到 Claude session 因 rate limit 中斷時：

```
重試延遲序列（無限重試，越來越慢）：
  第 1 次：5 分鐘後重試
  第 2 次：15 分鐘後
  第 3 次：30 分鐘後
  第 4 次：1 小時後
  第 5 次：3 小時後
  第 6+ 次：每 6 小時嘗試一次（直到成功）

每次重試前 Telegram 簡短通知：「Claude 限額重試 第 N 次」
```

OpenClaw 用 MiniMax API（不是 Anthropic）所以它自己不受影響，永遠在線監控。

#### 21.8.2 第三方 API rate limit

YouTube/NetEase/QQ 等被擋時：
- 標記為 temp 失敗
- 延遲 5 分鐘起，指數退避（最大 1 小時/次）
- 不影響其他歌的處理

### 21.9 磁碟空間 Guard

```python
async def check_disk_space():
    free_gb = shutil.disk_usage("/data").free / (1024**3)
    total_gb = shutil.disk_usage("/data").total / (1024**3)
    free_pct = (free_gb / total_gb) * 100
    
    if free_pct < 5:
        # 緊急：拒絕新 task + 觸發 LRU 清理
        global accept_new_tasks
        accept_new_tasks = False
        await emergency_cleanup()
        await alert_openclaw("CRITICAL: disk < 5%")
    elif free_pct < 10:
        # 警告：開始 LRU 清理但仍接收新 task
        await lru_cleanup()
        await alert_openclaw("WARNING: disk < 10%")
    elif free_pct < 20:
        # 通知 OpenClaw 一聲
        await alert_openclaw("INFO: disk < 20%")
```

每小時跑一次。

### 21.10 Git 競爭防護

避免兩個 Claude session 同時改 main：

```bash
# 每次 Claude session 開始時跑
flock -n /tmp/home-ktv.lock -c "echo 'lock acquired'"
# 如果 lock 拿不到，等 30 秒重試，3 次後放棄並通知 OpenClaw
```

或更簡單的方式：在 PROGRESS.md 頂部寫「Active session: <id>」，新 session 看到別人的 ID 就先 confirm（讀 timestamp，超過 1 小時才搶）。

### 21.11 Watchdog Cron Job

`scripts/watchdog.py`，每 10 分鐘跑一次：

```python
def watchdog():
    # 1. 檢查 stale pipeline tasks
    stale = db.query("""
        SELECT id FROM queue_items 
        WHERE status = 'processing' 
        AND last_heartbeat < datetime('now', '-15 minutes')
    """)
    for item in stale:
        db.update(item.id, status='pending')
        log.warning(f"Reset stale item {item.id}")
    
    # 2. 檢查 stuck songs
    stuck = db.query("""
        SELECT id FROM songs
        WHERE status IN ('downloading', 'separating', 'aligning')
        AND processed_at < datetime('now', '-15 minutes')
    """)
    # 同樣處理
    
    # 3. 檢查磁碟
    check_disk_space()
    
    # 4. 檢查 GPU 是否存活
    if not gpu_responsive():
        alert_openclaw("GPU not responding")
    
    # 5. 看是否有 zombie processes
    cleanup_zombies()
```

systemd timer 跑：

```ini
# /etc/systemd/system/ktv-watchdog.timer
[Unit]
Description=KTV Watchdog Timer

[Timer]
OnBootSec=2min
OnUnitActiveSec=10min

[Install]
WantedBy=timers.target
```

### 21.12 OpenClaw 永遠在線（MiniMax 加持）

OpenClaw 使用 MiniMax API 不受 Anthropic rate limit 影響。它的角色：

- **永遠監控**：cron 每 10 分鐘檢查 PROGRESS.md
- **永遠回應**：使用者 Telegram 訊息隨時處理
- **永遠通知**：Claude 出問題時立刻 Telegram 你
- **唯一不能做的**：寫 code（必須喚起 Claude 來做）

如果 MiniMax 也掛了（極少數情況），fallback：
- OpenClaw 進「靜默模式」，仍跑 cron 但不主動發訊息
- 使用者透過 SSH 直接看 PROGRESS.md
- 等 MiniMax 恢復

### 21.13 各種「災難情境」對照表

| 災難 | 偵測 | 處理 | 通知 |
|---|---|---|---|
| 單首歌處理 timeout（15min）| pipeline 內 timeout | 標記 failed_perm，跳下一首 | Remote 顯示警告 |
| Demucs OOM | catch CUDA error | 標記 failed_temp，30s 後重試 | error_log |
| yt-dlp 影片下架 | yt-dlp 4xx | 標記 failed_perm | error_log + Remote |
| 歌詞所有源都失敗 | manager 回 None | 走純文字 fallback；失敗則 lyrics_source=none | 無需通知 |
| Claude 卡 1 小時 | watchdog stale heartbeat | OpenClaw 喚起新 session 接手 | Telegram |
| Claude 卡 24 小時 | watchdog 嚴重 stale | 標記 abandoned，停自動重試 | Telegram 緊急 |
| Claude 跑長指令被 rate limit 切 | OpenClaw 偵測到 session 結束 | 嘗試 detach 跑中的指令；下次 session 檢查產物 | Telegram |
| Claude session 同時兩個 | git lock + PROGRESS.md ACTIVE 標記 | 後者等前者，30s 後判定棄權 | error_log |
| Server 突然重啟 | systemd 啟動 | recovery.on_startup() 重設 processing 為 pending | error_log + 連線中 client |
| 磁碟 < 5% | watchdog | 拒絕新 task + LRU 清理 | Telegram |
| 磁碟滿 100% | DB 寫入失敗 | 系統凍結，讀模式 | Telegram 緊急 |
| GPU driver 崩潰 | nvidia-smi 失敗 | 重新載入 driver；失敗則回 CPU 模式 | Telegram |
| Cloudflare Tunnel 斷 | systemd 監控 | 自動重啟 cloudflared | error_log |
| WebSocket 大量斷 | 連續多個 disconnect | 重啟 WS server 程序 | error_log |
| MiniMax API 掛 | OpenClaw 自身錯誤 | 進靜默模式，繼續 cron | 等恢復 |
| Anthropic API 掛 | Claude 完全無法用 | OpenClaw 等待 + 每小時嘗試 | Telegram |
| 連續 rate limit 5+ 次 | OpenClaw 計數 | 改成 6 小時/次嘗試 | Telegram 摘要 |

### 21.14 監控儀表板（M5 額外）

`/admin/health` 頁面顯示：

- 磁碟使用率（圖表）
- GPU VRAM 使用、溫度
- 當前 pipeline 進度
- 過去 24 小時錯誤次數（按類別）
- Claude session 狀態（最後 heartbeat）
- OpenClaw cron 最後執行
- 連線中 client 數量

### 21.15 Resilience 測試（M6 一定要做）

「故意搞壞」測試清單：

- [ ] 處理一首歌時 `kill -9` backend，重啟後該歌應自動恢復處理
- [ ] 處理時拔網路線 30 秒，網路回來後 yt-dlp 應重試
- [ ] 故意填爆磁碟，系統應拒絕新 task 並通知
- [ ] 故意把一個 song_id 改成不存在的 YouTube ID，應 failed_perm 並跳過
- [ ] 同時點 5 首歌，GPU 應序列化處理而非並行
- [ ] Claude 寫程式時 `pkill claude`，OpenClaw 應 1 小時內偵測並重啟
- [ ] 把 PROGRESS.md heartbeat timestamp 手動改成 2 小時前，watchdog 應觸發

寫成自動化測試或手動 checklist。

