# Setup Guide

> 路徑中的 `<REPO_DIR>`/`<HOME>`/`<user>`/`ktv.example.com` 請換成你自己的值。

> 這份檔案記錄所有需要使用者手動操作的步驟，按時間順序追加。
> Claude 不會跳過此檔案——任何需要使用者操作的事都會在這裡新增章節。

---

## 一次性環境準備（M0 階段）

### 1. GitHub Repo（M0-T1）

詳見 PROGRESS.md「⚠️ User Action Required」區塊。

### 2. 確認伺服器基本工具

請在 Telegram 告訴 OpenClaw 以下哪些已安裝：

```bash
python3 --version    # 需 ≥ 3.12
node --version       # 需 ≥ 20
git --version
docker --version
nvidia-smi           # 看到 GTX 1660 Super 即可
cloudflared --version
```

任何未安裝的，Claude 在 M0-T5 會嘗試自動安裝。

### 3. NVIDIA Driver / CUDA / cuDNN（M0-T5，自動）

Claude 會跑 `scripts/gpu-setup-check.sh`，這支腳本會：

1. 檢查 `nvidia-smi` 是否可用
2. 不可用則安裝 `nvidia-driver-535` 或對應版本
3. 安裝 CUDA 12.x + cuDNN
4. 在 ERRORS.md 記錄安裝過程

如果腳本遇到需要重開機的步驟，會在 PROGRESS.md 標記 ⚠️ 並通知你重開伺服器。

### 4. Cloudflare Tunnel（M0-T6）

#### 4.1 確認你有 Cloudflare 帳號和 `example.com` 域名

如果還沒在 Cloudflare 管理 `example.com`：
1. 登入 https://dash.cloudflare.com
2. Add Site → 輸入 `example.com`
3. 把網域註冊商的 nameserver 改成 Cloudflare 提供的
4. 等 DNS 生效（最多 24 小時）

#### 4.2 安裝 cloudflared

```bash
# Ubuntu
curl -L https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt update
sudo apt install cloudflared
```

#### 4.3 登入 Cloudflare

```bash
cloudflared tunnel login
```

會開瀏覽器要你選擇域名授權。完成後 `~/.cloudflared/cert.pem` 會被建立。

#### 4.4 建立 Tunnel

```bash
cloudflared tunnel create ktv
```

記下輸出的 Tunnel UUID（類似 `abc123-def456-ghi789`），並把它寫進 `.env`：

```
CF_TUNNEL_UUID=abc123-def456-ghi789
```

#### 4.5 設定 DNS

```bash
cloudflared tunnel route dns ktv ktv.example.com
```

#### 4.6 設定檔

`/etc/cloudflared/config.yml`（要 sudo 建立）：

```yaml
tunnel: <填入 UUID>
credentials-file: /home/<your-user>/.cloudflared/<UUID>.json

ingress:
  - hostname: ktv.example.com
    service: http://localhost:8000
  - service: http_status:404
```

#### 4.7 安裝為 systemd 服務（選做，方便開機自啟）

```bash
sudo cloudflared service install
sudo systemctl start cloudflared
sudo systemctl enable cloudflared
```

#### 4.8 測試

先用任意服務測試（之後會被 KTV 替換）：

```bash
python3 -m http.server 8000
```

開另一個終端：

```bash
curl https://ktv.example.com
```

看到 Python 的目錄列表即代表 Tunnel 通了。

---

## 生產部署（M5 完成後適用）

### 5. Systemd 服務安裝

#### 5.1 Backend

```bash
sudo cp <REPO_DIR>/deploy/ktv-backend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ktv-backend
sudo systemctl start ktv-backend
sudo systemctl status ktv-backend
```

確認服務正常：
```bash
curl http://localhost:8000/health
# → {"status":"ok","app":"ktv-backend","version":"0.1.0"}
```

#### 5.2 Frontend（可選，也可直接用 pnpm dev）

```bash
# 先 build
cd <REPO_DIR>/frontend
pnpm build

# 安裝服務
sudo cp <REPO_DIR>/deploy/ktv-frontend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ktv-frontend
sudo systemctl start ktv-frontend
```

> 注意：`ktv-frontend.service` 的 ExecStartPre 會在每次重啟時執行 `pnpm build`，首次啟動較慢。
> 若要加快，可把 build 單獨做好後改用 `pnpm start` 跳過 Pre。

#### 5.3 Cloudflare Tunnel

```bash
# 複製設定檔（已有 tunnel UUID）
sudo cp <REPO_DIR>/deploy/cloudflared.yml /etc/cloudflared/config.yml

# 啟動服務
sudo systemctl enable cloudflared
sudo systemctl start cloudflared

# 測試穿透
curl https://ktv.example.com/health
```

### 6. 備份設定

#### 6.1 手動備份

```bash
bash <REPO_DIR>/scripts/backup.sh
```

備份位置：`<REPO_DIR>-backups/ktv-backup-YYYYMMDD_HHMMSS.tar.gz`
備份內容：SQLite DB、`.env`、`cloudflared.yml`、最近 7 天的 log

#### 6.2 自動備份（每天凌晨 2:00）

```bash
crontab -e
```

加入：
```
0 2 * * * <REPO_DIR>/scripts/backup.sh >> /data/ktv/logs/backup.log 2>&1
```

### 7. 資料目錄初始化

第一次部署時，確認資料目錄存在：

```bash
sudo mkdir -p /data/ktv/{cache,logs,tmp}
sudo chown -R <user>:<user> /data/ktv
```

### 8. 系統健康確認清單

部署後逐項確認：

```bash
# 1. Backend 回應
curl https://ktv.example.com/health

# 2. 房間列表
curl https://ktv.example.com/api/rooms

# 3. 前端頁面
curl -s https://ktv.example.com/ | head -5

# 4. GPU 狀態（不連顯示器時 nvidia-smi 可能會有非零退出碼，是正常的）
nvidia-smi

# 5. 服務狀態
sudo systemctl status ktv-backend cloudflared

# 6. Disk 空間
df -h /data

# 7. Backend log（最近 50 行）
journalctl -u ktv-backend -n 50 --no-pager
```

---

## 發布前的最終設定（M6 階段）

(M6 達成時補充)

---

## 日常維運

### 重啟服務

```bash
sudo systemctl restart ktv-backend
sudo systemctl restart ktv-frontend
sudo systemctl restart cloudflared
```

### 查看 log

```bash
journalctl -u ktv-backend -f
tail -f /home/<user>/home-ktv/data/logs/app.log
```

### 備份

```bash
bash /home/<user>/home-ktv/scripts/backup.sh
```

備份位置：`/home/<user>/home-ktv-backups/YYYYMMDD/`
