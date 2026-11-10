# Ubuntu 正式部署指南

本指南以 systemd user services 為標準部署方式。所有指令均以一般部署帳號執行；只有安裝
系統套件與啟用 linger 需要 `sudo`。Docker Compose 是保留的替代方案，不是本指南主線。

## 1. 系統需求

- Ubuntu 近期 LTS、Git、curl、FFmpeg。
- Python 3.12 與 `uv`。
- Node.js 24 與 `pnpm`。
- Deno（yt-dlp 的 JavaScript runtime）。
- 選用 NVIDIA GPU；沒有 GPU 時在 `.env` 設 `ENABLE_GPU=false`。

安裝一般工具、uv、Deno 與 Node.js 24：

```bash
sudo apt update
sudo apt install -y git curl ffmpeg build-essential sqlite3
curl -LsSf https://astral.sh/uv/install.sh | sh
curl -fsSL https://deno.land/install.sh | sh
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
nvm install 24
corepack enable
corepack prepare pnpm@latest --activate
```

重新登入 shell 後確認：

```bash
uv --version
deno --version
node --version
pnpm --version
ffmpeg -version | head -n 1
```

若使用 NVIDIA GPU，另依 Ubuntu/NVIDIA 官方方式安裝相容的驅動，並先確認 `nvidia-smi` 正常。

## 2. 取得固定版本

正式機建議部署 release tag，不直接追蹤開發分支。將 `<VERSION_TAG>` 換成要部署的版本：

```bash
git clone https://github.com/CBC0210/home-ktv.git
cd home-ktv
git fetch --tags
git checkout <VERSION_TAG>
```

下文假設目前目錄是 repository 根目錄。

## 3. 設定根目錄 `.env`

唯一標準位置是 repository 根目錄的 `.env`：

```bash
cp .env.example .env
sed -i "s/^ADMIN_COOKIE_SECRET=.*/ADMIN_COOKIE_SECRET=$(openssl rand -hex 32)/" .env
$EDITOR .env
```

至少修改：

- `ADMIN_PASSWORD`：Admin 後台與房主進入房間管理模式使用。
- `ADMIN_COOKIE_SECRET`：上面指令已產生隨機值。
- `DATA_DIR`：正式機建議填絕對路徑，例如 `/home/你的帳號/.local/share/home-ktv/data`。

常調整項目是 `ENABLE_GPU`、`ENABLE_WORD_ALIGNMENT`、`WHISPERX_MODEL`、
`DEFAULT_ROOM_PASSWORD` 與 `PUBLIC_BASE_URL`；完整清單與註解見 [`.env.example`](../.env.example)。
建立資料目錄（路徑須與 `.env` 相同）：

```bash
mkdir -p "$HOME/.local/share/home-ktv/data"
```

不要建立 `backend/.env`；程式只為舊部署保留相容讀取。

## 4. 後端與 yt-dlp provider

安裝鎖定的 Python 相依：

```bash
cd backend
uv sync --locked --python 3.12
cd ..
```

安裝 bgutil PO token provider。路徑是程式會自動偵測的預設位置：

```bash
PROVIDER_DIR="$HOME/.local/share/home-ktv/bgutil-ytdlp-pot-provider"
git clone --single-branch --branch 2.0.0 \
  https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git "$PROVIDER_DIR"
test "$(git -C "$PROVIDER_DIR" rev-parse HEAD)" = 2d758ea29ae5c65886bdf56c42ebbdfe17d78bbb
cd "$PROVIDER_DIR/server"
npm ci
npx tsc
cd -
```

程式依序從 `KTV_YTDLP_*_PATH`、`PATH`、`~/.deno`／`~/.nvm` 找 Deno 與 Node。
provider 預設在上述位置；非標準安裝才需要設定 `.env.example` 中三個 `KTV_*` 變數。
驗證處理相依：

```bash
cd backend
uv run python -c 'import yt_dlp_ejs, yt_dlp_plugins.extractor.getpot_bgutil_script; from ktv_pipeline.pipeline.ytdlp import _js_runtimes; assert _js_runtimes(); print("processing dependencies ready")'
cd ..
```

## 5. 建置前端

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm build
cd ..
test -f frontend/.next/standalone/server.js
```

若使用單一外部網域，先建立 `frontend/.env.production.local` 再 build：

```bash
printf 'NEXT_PUBLIC_API_URL=https://ktv.example.com\n' > frontend/.env.production.local
```

## 6. 安裝 systemd user services

安裝器會偵測 repository、uv 與 Node 絕對路徑，渲染 unit 到
`~/.config/systemd/user/`，再 daemon-reload 與 enable。預設前端 port 是 3000：

```bash
bash scripts/install-user-services.sh --frontend-port 3000
sudo loginctl enable-linger "$USER"
systemctl --user start ktv-frontend.service
```

若自動偵測不到工具，可明確指定：

```bash
bash scripts/install-user-services.sh --uv "$HOME/.local/bin/uv" \
  --node "$HOME/.nvm/versions/node/v24.15.0/bin/node" --frontend-port 3000
```

安裝器覆蓋內容不同的既有 unit 前會建立 `.bak-<時間>` 備份。

## 7. 驗證與排錯

```bash
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:3000/
systemctl --user status ktv-backend.service ktv-frontend.service
journalctl --user -u ktv-backend.service -n 100 --no-pager
journalctl --user -u ktv-frontend.service -n 100 --no-pager
```

從同網段裝置開啟 `http://<伺服器IP>:3000/r/home/player`。若 service 找不到 Node、uv、
Deno 或 provider，重新執行安裝器並用 `.env` 的 `KTV_*` 變數指定非標準路徑。

## 8. 更新版本

先確認工作樹沒有未保存修改，再把 `<VERSION_TAG>` 換成新 release tag：

```bash
git fetch --tags
git checkout <VERSION_TAG>
cd backend
uv sync --locked --python 3.12
cd ../frontend
pnpm install --frozen-lockfile
pnpm build
cd ..
bash scripts/install-user-services.sh --frontend-port 3000
systemctl --user restart ktv-backend.service ktv-frontend.service
curl --fail http://127.0.0.1:8000/health
```

## 9. 備份

備份 SQLite 與根目錄 `.env`；媒體 cache 可重新產生，不會打包。路徑應與 `.env` 一致：

```bash
DATA_DIR="$HOME/.local/share/home-ktv/data" \
BACKUP_BASE="$HOME/backups/home-ktv" \
bash scripts/backup.sh
```

先手動驗證產物，再自行加入 cron 或 systemd timer。還原前先停止兩個 KTV user services，並保留
現有資料副本。

## 10. 可選：Cloudflare Tunnel

只有跨網路存取才需要。先依 Cloudflare 官方文件安裝 `cloudflared`、登入並建立 tunnel：

```bash
cloudflared tunnel login
cloudflared tunnel create ktv
cp deploy/cloudflared.example.yml "$HOME/.cloudflared/config.yml"
$EDITOR "$HOME/.cloudflared/config.yml"
cloudflared tunnel --config "$HOME/.cloudflared/config.yml" run ktv
```

範本會把 `/api`、`/ws`、`/songs`、`/health`、`/version` 送到後端 8000，其餘送到前端
3000。啟用前應設定 `PUBLIC_BASE_URL`、`COOKIE_SECURE=true`，重建前端並重啟服務。
