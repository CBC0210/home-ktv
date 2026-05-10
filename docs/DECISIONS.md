# Architecture Decision Records (ADR)

> 重大架構決策記錄。每個 ADR 一條，按時間順序排列。
> Claude 在做出影響架構的決定時必須新增一條 ADR。

格式範例：

```
## ADR-XXX: 決策標題
- Date: YYYY-MM-DD
- Status: proposed | accepted | superseded by ADR-YYY
- Context: 為什麼要做這個決定？背景？
- Decision: 決定了什麼？
- Consequences: 好處、壞處、影響？
```

---

## ADR-001: 採用 SQLite 而非 PostgreSQL
- Date: 2026-05-09
- Status: accepted
- Context: 專案是自用單機系統，使用者規模理論上不限制但實際很小。
- Decision: 用 SQLite + WAL mode，不引入 PostgreSQL。
- Consequences:
  - ✅ 部署簡單，沒有額外服務
  - ✅ 備份單檔，操作直觀
  - ⚠️ 並行寫入有限制（WAL 緩解但非無限），自用範圍 OK
  - ⚠️ 跨機分散式不可能（但本專案單機，無需）

## ADR-002: GPU 任務序列化
- Date: 2026-05-09
- Status: accepted
- Context: GTX 1660 Super 6GB，Demucs + WhisperX 同時跑會 OOM。
- Decision: 用單一 `asyncio.Lock` 保護所有 GPU 任務，序列化執行。
- Consequences:
  - ✅ 不會 OOM
  - ⚠️ 多人快速點歌時會排隊等待
  - ⚠️ 未來升級 GPU 後此鎖可去除

## ADR-003: 雙音軌 HLS + 瀏覽器混音
- Date: 2026-05-09
- Status: accepted
- Context: 需要使用者即時調整人聲音量。
- Decision: 後端串兩條音軌（伴奏 + 人聲），瀏覽器用 Web Audio API 混音。
- Consequences:
  - ✅ 即時調整無延遲
  - ✅ 不用每次重切 HLS
  - ⚠️ 兩倍音訊頻寬（自用網路無壓力）

## ADR-004: 管理員密碼明文存 .env
- Date: 2026-05-09
- Status: accepted
- Context: 自用範圍，伺服器只有用戶能存取。
- Decision: ADMIN_PASSWORD 明文寫在 `.env`，房間密碼用 bcrypt hash 存 DB。
- Consequences:
  - ✅ 簡單
  - ⚠️ 伺服器若被入侵 .env 暴露，但範圍止於 KTV 系統本身
  - 未來若上線公開可改成 Argon2 hash + .env 只存 hash

## ADR-005: 時間軸歌詞 fallback 鏈
- Date: 2026-05-09
- Status: accepted
- Context: 華語歌詞 LRCLIB 覆蓋差，需要更好的源。
- Decision: 順序為 AMLL TTML → NetEase → QQ → syncedlyrics（含 Musixmatch/LRCLIB/Megalobiz）→ 純文字（Mojim/KKBOX/Genius）→ 完全失敗。
- Consequences:
  - ✅ 華語覆蓋率大幅提升
  - ⚠️ 部分 API 是 reverse-engineered，可能因平台改版失效
  - ⚠️ 純文字依賴 HTML 解析，更脆弱

## ADR-006: 開發直接在伺服器進行
- Date: 2026-05-09
- Status: accepted
- Context: 使用者偏好直接在 Ubuntu 伺服器上開發，無需本機/遠端分離。
- Decision: 不做本機開發環境，所有 task 在伺服器執行。Docker 可用但非強制。
- Consequences:
  - ✅ 環境一致，免同步
  - ✅ GPU 任務可直接驗證
  - ⚠️ 開發機沒有 GUI 時，前端調試靠瀏覽器 devtools
  - ⚠️ 若伺服器掛掉，開發環境也沒了（但有 git 備份）

## ADR-007: 不使用 Sentry，自製錯誤追蹤
- Date: 2026-05-09
- Status: accepted
- Context: 自用範圍不需要外部錯誤追蹤服務。
- Decision: 錯誤寫入 SQLite `error_log` table + 檔案 log + 透過 OpenClaw 通知。
- Consequences:
  - ✅ 不需付費
  - ✅ 隱私（不上傳到第三方）
  - ⚠️ 錯誤分析功能簡陋，但自用足夠

## ADR-008: 失敗分等級（temp / perm）
- Date: 2026-05-09
- Status: accepted
- Context: 自動處理 pipeline 會遇到各種失敗，需要決定哪些自動重試、哪些放棄。
- Decision: 兩級分類——temp（網路、OOM、暫時性問題，無限指數退避）；perm（影片下架、解析失敗，標記後跳過）。
- Consequences:
  - ✅ 不會卡死整個隊列
  - ✅ 暫時性問題自動恢復
  - ⚠️ 分類錯誤會導致永遠重試或誤跳過，需要 logging 監控

## ADR-009: 重啟恢復用 pending 重跑而非看檔案
- Date: 2026-05-09
- Status: accepted
- Context: server 重啟時，DB 裡可能有 status=processing 的歌曲，要決定怎麼恢復。
- Decision: 全部重置為 pending 重跑。不檢查實體檔案是否完整。
- Consequences:
  - ✅ 邏輯簡單可預測
  - ✅ idempotent 設計讓重跑無副作用（已有檔案會跳過該階段）
  - ⚠️ 偶爾會浪費幾分鐘重跑已完成的階段
  - ⚠️ 接受此成本因為自用範圍

## ADR-010: Rate limit 無限重試 + 退避
- Date: 2026-05-09
- Status: accepted
- Context: Claude session 因 Anthropic rate limit 中斷，需要重試策略。
- Decision: 無限重試，但使用退避序列：5min → 15min → 30min → 1hr → 3hr → 6hr/次。
- Consequences:
  - ✅ 不會永久放棄
  - ✅ 不會造成 API spam
  - ⚠️ 若使用者付費等級不夠用，可能停滯數天
  - ⚠️ OpenClaw 用 MiniMax，自身不受 Anthropic 限額影響，可永遠監控

## ADR-011: Heartbeat 機制
- Date: 2026-05-09
- Status: accepted
- Context: 需要區分「Claude 還在運作」和「Claude 卡死了」。
- Decision: 三層 heartbeat——Claude 每 5 分鐘更新 PROGRESS.md；pipeline 每 30 秒更新 queue_items.last_heartbeat；OpenClaw 每 10 分鐘巡邏。
- Consequences:
  - ✅ 1 小時內可偵測 Claude session 死亡
  - ✅ 15 分鐘內可偵測 pipeline stage 卡住
  - ⚠️ 增加少量寫入，自用範圍可忽略

## ADR-012: 單首歌總 timeout 15 分鐘
- Date: 2026-05-09
- Status: accepted
- Context: 寬鬆模式下單首歌可接受時長。
- Decision: 一首歌從 yt-dlp 開始到 ready 為止總計不超過 15 分鐘，否則標記 failed_perm。
- Consequences:
  - ✅ 不會因為一首怪歌卡死整個系統
  - ⚠️ 4K 長 MV 可能會失敗（但通常 KTV 不需要 4K）
  - 使用者可手動點「重試」覆蓋此限制
