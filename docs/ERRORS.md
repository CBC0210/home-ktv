# Error Log

> 內部開發記錄（AI-agent 工作流長期記憶）— 部署與使用不需閱讀本檔。

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

### 2026-05-10 — CUDA Toolkit 安裝被 SIGKILL 中斷

- **發生於**: M0-T5 / gpu-setup-check.sh / apt install nvidia-cuda-toolkit
- **嚴重程度**: warning
- **症狀**:
  ```
  Killed
  E: Sub-process /usr/bin/dpkg returned an error code (1)
  ```
  `apt install nvidia-cuda-toolkit` 跑到一半被 SIGKILL（記憶體不足或 OOM killer），導致 `nvcc` 未安裝完成。
- **可能原因**: 系統記憶體不足，OOM killer 殺掉 dpkg；或上一次安裝只安裝了部分套件
- **解決方式**: 重新執行時 `nvcc` 已存在（`/usr/bin/nvcc`，CUDA 12.0），上次安裝實際已成功，只是未正常退出。`gpu-setup-check.sh` 確認 ✅ 通過。
- **狀態**: ✅ 已解決（2026-05-10）

### 2026-05-10 — GPU 規格與 CLAUDE.md 不符

- **發生於**: M0-T5 / gpu-setup-check.sh
- **嚴重程度**: warning（不影響開發，但影響模型選型）
- **症狀**:
  ```
  NVIDIA GeForce GTX 1650, 580.65.06, 4096 MiB
  ```
  實際 GPU 是 GTX 1650（4GB VRAM），而 CLAUDE.md §3.3 記載的是「GTX 1660 Super（6GB VRAM）」。
- **影響**:
  - Demucs `htdemucs_ft` FP16 在 4GB 更緊張，需實測（建議 M1-T3 先測試）
  - WhisperX：預設從 `small` 開始而非 `medium`（4GB 更謹慎）
  - 如果 Demucs FP16 OOM，可試 `htdemucs`（較輕量）
- **解決方式**: 已更新 `.env.example` 的 `WHISPERX_MODEL` 備注；M1-T3 + M1-T5 實作時要做 VRAM 壓力測試
- **狀態**: ✅ 已記錄，不阻塞開發（M1-T3 時再確認）

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
