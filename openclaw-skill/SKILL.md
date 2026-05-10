# Home KTV Project Management Skill

> 這份 SKILL.md 教 OpenClaw 如何管理 home-ktv 專案。
> 安裝方式：`cp openclaw-skill/SKILL.md ~/.openclaw/workspace/skills/home-ktv/SKILL.md`
> 之後在 OpenClaw 對話中提到「home-ktv」「KTV 專案」時自動觸發。

---

## What this skill does

協助使用者透過 Telegram 管理一個叫 home-ktv 的家庭 KTV 開發專案。具體任務包括：

- 接收使用者指令（自然語言），轉成具體 task
- 呼叫 Claude Code CLI 執行開發工作
- 監控 Claude 的進度（讀 PROGRESS.md）
- 處理 rate limit、session 中斷
- 把 task 完成、需要驗收、錯誤等狀態透過 Telegram 通知使用者
- 維護 OpenClaw 自己的長期記憶

---

## Project location

```
/home/<user>/home-ktv/
```

主要檔案：
- `CLAUDE.md` — 專案規格（讀過一次就好，內容大）
- `docs/PROGRESS.md` — **每次都讀**，這是專案狀態的真相來源
- `docs/DECISIONS.md` — 架構決策歷史
- `docs/ERRORS.md` — 錯誤記錄
- `docs/SETUP.md` — 使用者手動操作步驟

---

## How to invoke Claude Code CLI

```bash
cd /home/<user>/home-ktv
claude code "<指令>"
```

或如果使用者用 Claude Code 互動模式，可直接：

```bash
cd /home/<user>/home-ktv
claude
```

然後把指令貼進去。

---

## Standard workflows

### Workflow A: 使用者說「繼續」、「開始下一個 task」

1. 讀 `docs/PROGRESS.md`，看 "In Progress" 或 "Next Up"
2. 如果有 In Progress → 告訴 Claude「繼續 M?-T?，狀態見 PROGRESS.md」
3. 如果只有 Next Up → 告訴 Claude「開始 M?-T?，按 CLAUDE.md §17 流程」
4. 等 Claude 回報完成
5. 讀 PROGRESS.md 確認 task 已標記 Done
6. Telegram 通知使用者：「M?-T? 完成，commit 在 <hash>，請驗收。需要我啟動服務測試嗎？」

### Workflow B: 使用者說「驗收 OK」/「✅」

1. 讀 PROGRESS.md，找最近完成的 task
2. 把該 task 的 ✅ User checkpoint 標記補上
3. 自動開始下一個 task（觸發 Workflow A）

### Workflow C: 使用者說「驗收不過」/「有問題：xxx」

1. 在 PROGRESS.md 把該 task 移回 "In Progress"
2. 在 docs/ERRORS.md 新增條目記錄使用者描述的問題
3. 告訴 Claude「使用者驗收不過，問題是 xxx，請修」
4. 走 Workflow A 流程

### Workflow D: Claude session 因 rate limit 中斷

1. 偵測訊號：Claude 回應出現 "rate limit"、"usage limit" 等字串
2. 確認 Claude 已執行 §17.5 步驟（commit 到 wip branch + 更新 PROGRESS.md）
3. 如果沒有 → 自己代為執行：
   ```bash
   cd /home/<user>/home-ktv
   git checkout -b wip/<task>-interrupted-<timestamp>
   git add -A
   git commit -m "WIP: interrupted by rate limit"
   git push origin wip/...
   ```
4. 在 PROGRESS.md "In Progress" 區塊補註「rate limit @ <time>」
5. Telegram 通知使用者：「Claude 達到限額，已保存進度。預計 X 分鐘後重啟。」
6. 設 cron 在 X 分鐘後重新呼叫 Claude，從 wip branch 繼續

### Workflow E: Claude 報告錯誤

1. 讀 docs/ERRORS.md 看錯誤詳情
2. 如果 Claude 已自行解決 → 在 Telegram 簡短通報「已自動解決：<錯誤摘要>」
3. 如果 Claude 標記為阻塞 → Telegram 詳細通報，附上：
   - 錯誤內容
   - 已嘗試的解法
   - 需要使用者做什麼

### Workflow F: 使用者操作完畢

當使用者在 Telegram 回覆「GitHub repo 已建好」、「Cloudflare 設定完成」等：

1. 在 PROGRESS.md 把對應「⚠️ User Action Required」項目標記 ✅
2. 觸發後續被該操作 blocked 的 task

### Workflow G: 排程巡檢（cron 每 10 分鐘）

1. 讀 PROGRESS.md 看是否有 In Progress 但 last heartbeat 超過 1 小時 → 觸發 Workflow H
2. 讀 ERRORS.md 看是否有新的阻塞中錯誤
3. 看磁碟空間（< 10% 通知使用者）
4. 看 GPU 是否還在跑（若有殘留任務）
5. 看 cloudflared / ktv-backend systemd 服務狀態
6. 每天 22:00 發每日進度摘要

### Workflow H: Stale heartbeat 處理

當偵測到 PROGRESS.md heartbeat > 1 小時舊：

1. 確認不是使用者操作中（檢查 git log 是否有新 commit）
2. 嘗試喚起新的 Claude session：
   ```bash
   cd /home/<user>/home-ktv
   claude code "請依照 §17.1 self-check，並接續 PROGRESS.md 中 In Progress 的 task"
   ```
3. 等待 5 分鐘看 PROGRESS.md 是否更新
4. 如果還沒 → 上升到 stuck 警示（4 小時無 heartbeat）→ Telegram 通知
5. 如果 24 小時還沒 → abandoned，停止自動重試，等使用者指示

### Workflow I: Rate limit 退避處理

偵測到 Claude 因 rate limit 中斷：

1. 確認 wip/* branch 有保存進度
2. 計算這個 task 已被 rate limit 切過幾次（從 ERRORS.md 數）
3. 套用退避序列：
   - 第 1 次：5 分鐘後重試
   - 第 2 次：15 分鐘後
   - 第 3 次：30 分鐘後
   - 第 4 次：1 小時後
   - 第 5 次：3 小時後
   - 第 6+ 次：6 小時/次
4. 設 `at` 命令在指定時間後喚起 Claude
5. 每次重試前發 Telegram 簡短通知：「Claude 限額重試 第 N 次，預計 X 後恢復」
6. 重試成功後 reset 計數

### Workflow J: 系統異常處理

從 watchdog 收到 alert（例如「磁碟 < 10%」）：

| Alert | 動作 |
|---|---|
| 磁碟 < 5% | 暫停接收新 pipeline task；觸發 LRU 清理；Telegram 緊急 |
| 磁碟 < 10% | LRU 清理；Telegram 警告 |
| 磁碟 < 20% | Telegram 提醒 |
| GPU 不回應 | Telegram 警告 + 嘗試重啟 nvidia 服務 |
| ktv-backend 重啟 > 5 次/5min | Telegram 緊急（systemd StartLimit 已生效）|
| Cloudflare Tunnel 斷 | 嘗試 systemctl restart cloudflared |
| 連續歌曲 perm 失敗 > 5 首 | Telegram 提醒（可能 yt-dlp 需更新）|

### Workflow K: 使用者要求查狀態

使用者問「現在進度如何」/「狀態」：

回 Telegram：

```
📊 home-ktv 狀態

Milestone: M{m} 進行中（task {t}/{N}）
當前 task: {task name} ({stage})
最後 heartbeat: {min} 分鐘前

今日進度:
- 完成: {n} tasks
- 錯誤: {n} 已解決, {n} 待處理

系統健康:
- 磁碟: {used}/{total} ({pct}%)
- GPU: {available/busy/error}
- Cloudflare Tunnel: {ok/down}

下一步: {next task}
```

---

## Telegram message templates

### Task 完成可驗收

```
✅ M{milestone}-T{task} 完成

{task description}

Commit: `{hash}`
Tag: `v0.M{m}.T{t}`
測試: {N} passed, {M} failed

要我啟動服務讓你試試嗎？或者你有其他想先看的？
```

### 使用者操作需求

```
⚠️ 需要你手動操作

{action description}

詳細步驟：
{steps}

完成後跟我說「{done message}」即可。
```

### Rate limit

```
🦞 我達到 Anthropic 的速率限制了。

當前 task: M{m}-T{t}
進度已保存到 wip branch: {branch}
預計恢復時間: {when}

不用做什麼，到時間我會自動繼續。
```

### 錯誤通報

```
🚨 遇到錯誤需要協助

Task: M{m}-T{t}
錯誤: {error}

已嘗試:
{attempts}

我可以做什麼：
1. {option 1}
2. {option 2}

或者你有其他想法？
```

### 每日進度摘要（cron 22:00）

```
📊 home-ktv 今日進度

完成: {tasks completed today}
進行中: {current task}
下一個: {next task}
本週剩餘: {remaining tasks in current milestone}

ETA 完成本 milestone: {eta}
```

---

## Memory hooks (SOUL.md)

需要在 OpenClaw SOUL.md 加入：

```
## home-ktv project context

This is a long-running personal project for the user. Key things to remember:
- The user goes by [從聊天記錄提取]
- The project domain is ktv.bc-verse.com
- Current milestone: [更新自 PROGRESS.md]
- The user prefers [從互動學習]
- Last user feedback: [最近的訊息]

When invoking Claude Code, always use the workflow in
~/.openclaw/workspace/skills/home-ktv/SKILL.md.
Always read /home/<user>/home-ktv/docs/PROGRESS.md before deciding what to do.
```

---

## Don'ts

- ❌ 不要讓 Claude 在「程式不可運行」的狀態下中斷
- ❌ 不要跳過使用者驗收，不能自己「替使用者點 ✅」
- ❌ 不要修改 CLAUDE.md，只有使用者指示時才改
- ❌ 不要 push 到 `main` 分支沒先測試
- ❌ 不要把 `.env` 內容貼到 Telegram（即使使用者問）
- ❌ 不要在 GitHub commit message 裡寫密碼或 token
- ❌ 不要超過 Telegram 訊息長度限制（4096 字），要分多則

---

## Self-update

如果使用者要求修改流程，更新此 SKILL.md 並 commit：

```bash
cd /home/<user>/home-ktv
git add openclaw-skill/SKILL.md
git commit -m "[skill] update: <change description>"
git push
```
