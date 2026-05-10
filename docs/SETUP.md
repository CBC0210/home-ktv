# Setup Guide

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

#### 4.1 確認你有 Cloudflare 帳號和 `bc-verse.com` 域名

如果還沒在 Cloudflare 管理 `bc-verse.com`：
1. 登入 https://dash.cloudflare.com
2. Add Site → 輸入 `bc-verse.com`
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
cloudflared tunnel route dns ktv ktv.bc-verse.com
```

#### 4.6 設定檔

`/etc/cloudflared/config.yml`（要 sudo 建立）：

```yaml
tunnel: <填入 UUID>
credentials-file: /home/<your-user>/.cloudflared/<UUID>.json

ingress:
  - hostname: ktv.bc-verse.com
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
curl https://ktv.bc-verse.com
```

看到 Python 的目錄列表即代表 Tunnel 通了。

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
