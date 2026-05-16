# 其他音源整合計畫 — Spotify / Bilibili

> 狀態更新（2026-05-16）：**Bilibili 已實作**（貼連結加歌 + 字幕一併處理，
> 字幕來源欄位對 Bilibili 影片自動顯示「Bilibili 字幕」）。Spotify 維持「不建議當音源、
> 僅可當歌單橋接」之結論，未實作。以下保留原評估記錄。

## 0. 結論先講

| 來源 | 拿得到「可播放音訊」？ | 建議 |
|---|---|---|
| **Bilibili** | ✅ 可以（yt-dlp 原生支援 `bilibili`） | **建議納入**，工程量小，與現有 pipeline 幾乎無縫 |
| **Spotify** | ❌ 拿不到音訊（DRM，ToS 禁止下載） | **不建議當音源**；僅適合當「歌單／metadata 來源」再轉去 YouTube/Bilibili 解析 |

核心限制：本系統的 pipeline 需要**原始音訊檔**才能跑 Demucs 人聲分離 + WhisperX 對齊。
沒有可下載的音訊 = 整條 KTV 流程走不通。Spotify 受 Widevine DRM 保護，技術與
法律上都不能下載音訊；Bilibili 則和 YouTube 一樣可由 yt-dlp 取得音訊。

---

## 1. Bilibili（建議實作）

### 1.1 可行性
- `yt-dlp` 內建 `BiliBili` extractor，支援 `https://www.bilibili.com/video/BVxxxx`。
- 取得影片＋音訊的方式與 YouTube 完全一致（同一個 `ytdlp.py` wrapper）。
- 適合補 YouTube 上沒有、但 B 站有的：華語 cover、live、二創、ACG。

### 1.2 需要的改動（小）
1. **ID／URL 解析**：`extract_youtube_id()` 旁加一個來源判定
   - 新增 `source` 欄位於 `songs`（`youtube`|`bilibili`，預設 `youtube`，向後相容）。
   - `songs.id` 目前 = youtube_id（PK）。Bilibili 用 `bv:<BVID>` 當主鍵前綴避免碰撞。
2. **下載**：`ytdlp.py` 傳入完整 URL 而非裸 ID；yt-dlp 自動選 extractor。B 站部分清晰度需
   `cookies`（與規格 §7.1 既有 cookie 機制相同），`.env` 增 `BILIBILI_COOKIES_PATH`（選用）。
3. **搜尋**：B 站搜尋 yt-dlp 無 `bilisearch` 穩定支援 → 兩個選項
   - (a) 只允許「貼 B 站連結」加歌（最省事，先做這個）。
   - (b) 串 B 站 web search API（非官方，易變，列為後續）。
4. **字幕**：B 站無內嵌逐字字幕 → 直接走既有「NetEase→QQ→…→純文字」歌詞鏈，無需改動。
5. **前端**：搜尋頁「直接貼網址」分頁已存在，擴充為同時接受 B 站 URL；緩存命中標記沿用。

### 1.3 風險
- B 站偶爾改 API／加風控（與 YouTube 的 R2 風險同級），靠 yt-dlp 更新緩解。
- 地區限制：部分影片限大陸 IP；失敗歸類為 `failed_perm`（沿用 §21.3）。

### 1.4 預估工程量
小。約：models 加 `source` 欄 + Alembic migration、`ytdlp.py` 傳 URL、加 BV 解析、
前端貼網址辨識。**1 個 task 量級**。

---

## 2. Spotify（不建議當音源；可當歌單來源）

### 2.1 為什麼不能當音源
- 串流受 **Widevine DRM**；`librespot` 等只能在授權 client 內解密播放，**不產生可存檔音訊**。
- Spotify ToS 明文禁止下載／反混淆；自用範圍仍是違反條款且技術不穩。
- 即使硬錄音（loopback）也拿不到「乾淨原始音訊」→ Demucs 分離品質差，違背系統目的。

### 2.2 唯一合理用法：metadata / 歌單橋接
Spotify Web API（OAuth，合法）能取得：歌單、曲目、演唱者、專輯、熱門度。
可作為**選歌靈感來源**，再把「曲名＋演唱者」丟進現有 YouTube/Bilibili 解析：

```
Spotify 歌單 ──(Web API, 合法 metadata)──► [{title, artist}] ──► 既有 youtube-search ──► pipeline
```

這正是「預裝歌單」已採用的模式（存 query、播放前才解析），所以：
- **不需要新音源管線**，只是多一個「把 Spotify 歌單匯入成預裝歌單條目」的工具。
- 需 `.env`：`SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET`（Client Credentials flow，無需使用者登入即可讀公開歌單）。

### 2.3 預估工程量
若只做「Spotify 歌單 → 預裝歌單 JSON」匯入腳本：很小（一支 script + 一個 admin 按鈕）。
完全不碰播放路徑。

---

## 3. 建議落地順序（日後二期）

1. **Bilibili 貼網址加歌**（最高 C/P，與 pipeline 無縫）。
2. Bilibili 緩存命中標記 + `source` 欄位 migration。
3. （選）Spotify 歌單匯入 → 擴充預裝歌單。
4. （選）Bilibili 搜尋整合。

## 4. 對現有架構的影響評估

- 資料模型：`songs` 加 `source TEXT DEFAULT 'youtube'`（一次 Alembic migration，向後相容）。
- Pipeline：Demucs／WhisperX／LRC→ASS／HLS **完全不動**（它們吃的是音訊檔，不在乎來源）。
- 既有 25 首 + 預裝歌單：不受影響。
- 風險集中在「下載階段」，沿用 §21 的 temp/perm 失敗分類與重試即可。
