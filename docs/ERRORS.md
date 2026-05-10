# Error Log

> 已知錯誤與解決方式。Claude 遇到錯誤時會：
> 1. 寫入 `error_log` table（DB 建好後）
> 2. 在這份檔案新增條目
> 3. 嘗試自動解決
> 4. 解決後標記為「✅ 已解決」並記錄解決方式
> 5. 解決不了則通知 OpenClaw → 透過 Telegram 通知使用者

---

## 格式範本

```
### YYYY-MM-DD HH:MM — 簡短描述

- **發生於**: M2-T3 / api/ws.py / 啟動時
- **嚴重程度**: error / warning / critical
- **症狀**:
  ```
  錯誤訊息或 stack trace
  ```
- **可能原因**: ...
- **解決方式**: ...
- **狀態**: ✅ 已解決 / ⚠️ 進行中 / 🚨 阻塞中
```

---

## 已解決

(尚無)

---

## 進行中

(尚無)

---

## 阻塞中（需要使用者協助）

(尚無)

---

## 已知會發生的錯誤（預知）

### YouTube 下載偶爾失敗
- **症狀**: yt-dlp 回 HTTP 403 或 "Sign in to confirm your age"
- **原因**: YouTube 改機制、IP 被 rate limit、影片需登入
- **解決**: 自動更新 yt-dlp（`pip install -U yt-dlp`）；嚴重時用 cookies.txt
- **分類**: temp（自動重試）；403 連續多次 → perm
- **預防**: M1-T2 設計時要包好錯誤處理

### YouTube 影片下架/私人/地區封鎖
- **症狀**: yt-dlp 回 4xx 明確錯誤（"Video unavailable", "Private video"）
- **分類**: perm（不重試，直接跳過並標記）
- **解決**: 在 Remote 顯示原因，使用者改點別首歌

### WhisperX OOM
- **症狀**: CUDA out of memory
- **原因**: 1660 Super 6GB 跑 large 不夠
- **解決**: 降到 medium 或 small；釋放其他 GPU 任務
- **分類**: temp（重試前先 torch.cuda.empty_cache()）
- **預防**: ADR-002 規定的 GPU 序列化 + WHISPERX_MODEL=medium 預設

### Cloudflare Tunnel 連線斷
- **症狀**: WebSocket 突然斷
- **原因**: Tunnel 重啟、網路抖動
- **解決**: 前端自動重連邏輯 + systemd 重啟 cloudflared
- **預防**: M3-T5 必須包含重連 + 狀態恢復

### 純文字歌詞網站改版
- **症狀**: Mojim/KKBOX 解析回 None
- **原因**: 對方網站 HTML 結構改了
- **解決**: 更新解析器；fallback 到下一個源
- **分類**: 對單一源 perm，但會 fallback 到下個源所以總體 OK
- **預防**: 解析器必須有完整錯誤處理 + log

### 單首歌總 timeout（15 分鐘）
- **症狀**: Pipeline 沒在 15 分鐘內完成
- **原因**: 影片過長、網路慢、處理階段累積延遲
- **分類**: perm（標記後跳過）
- **解決**: 使用者可手動點 Remote 的「重試」按鈕覆蓋此限制

### Claude session rate limit
- **症狀**: Claude 回應出現 "rate limit" 字串
- **解決**: OpenClaw 走 Workflow I 退避重試（無限）
- **預防**: 規劃 task 時注意分塊，避免單一 task 跑很久

### Server 重啟後 processing 狀態殘留
- **症狀**: DB 裡有 status='processing' 但實際無 worker 在跑
- **解決**: ADR-009 的 on_startup 自動將 processing → pending
- **預防**: M2-T7 必須實作此邏輯

### 兩個 Claude session 同時跑
- **症狀**: git push 衝突、PROGRESS.md 互相覆蓋
- **解決**: flock + PROGRESS.md ACTIVE 標記
- **預防**: §17 self-check 要包含「檢查是否有別的 session 進行中」

### 磁碟空間警告
- **5%**: 系統凍結拒絕新 task
- **10%**: 觸發 LRU 清理
- **20%**: Telegram 提醒
- **解決**: 自動 LRU；嚴重時管理員手動清理
- **預防**: watchdog 每小時檢查
