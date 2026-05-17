# 響窩 Echonest — Home KTV

> 自架的家庭 KTV：手機掃 QR code 點歌，電視瀏覽器播放。
> 重運算（YouTube/Bilibili 下載、人聲分離、歌詞對齊）全在你自己的伺服器完成，
> 處理過的歌**永久快取**，下次秒開。

由 [CBC](https://github.com/CBC0210) 製作 · [github.com/CBC0210/home-ktv](https://github.com/CBC0210/home-ktv)

---

## 這是什麼

- 📺 **Player（電視）**：原 MV 全螢幕 + 動態 KTV 字幕（逐句、無黃色填色、繁體、日韓原文＋羅馬拼音）。
- 📱 **Remote（手機）**：搜尋點歌、隊列拖曳/插播、播放控制、人聲混音、收藏/歷史/推薦、曲庫瀏覽、表情反應。
- 🛠️ **Admin（`/admin`）**：房間/密碼管理、緩存與磁碟、錯誤日誌、**預裝歌單批次預載**、系統狀態。
- 🎚️ 自動人聲分離（Demucs）做伴奏；多來源時間軸歌詞（AMLL/NetEase/QQ/LRCLIB）+ WhisperX 對齊，找不到退純文字。
- 🔁 公平輪唱（同一人不連播）、自動播放、閒置房間自動清理。
- 🎬 YouTube + **Bilibili**（貼連結即可），單曲問題回報→下次改用原始音訊。

完整規格與設計決策見 [`CLAUDE.md`](CLAUDE.md)（專案單一真相來源）。

## 不需要 Cloudflare — 區域網就能跑

預設**零設定走區域網**：後端與前端跑在同一台機器，手機和電視連同一個 Wi-Fi 即可。
電視打開 Player，畫面上的 QR code 就是手機點歌頁，掃了就能用。

Cloudflare Tunnel 只有在**要從外網/不同網路存取**時才需要，屬**可選**（見最後一節）。

## 需求

| | 最低 |
|---|---|
| Python | 3.12+（用 [`uv`](https://docs.astral.sh/uv/)） |
| Node | 20+（用 [`pnpm`](https://pnpm.io/)） |
| FFmpeg | 必須（轉碼/HLS/loudnorm） |
| GPU | 選用但強烈建議（Demucs/WhisperX）。CUDA 卡 4GB+；無 GPU 會很慢但能跑 |
| 磁碟 | 媒體永久快取，建議 ≥ 20GB |

## Quick Start（區域網，零設定）

```bash
# 1. 環境變數（最少只要改 ADMIN_PASSWORD / ADMIN_COOKIE_SECRET）
cp .env.example .env
$EDITOR .env

# 2. 後端 — 監聽 0.0.0.0 讓同網段的手機連得到
cd backend
uv sync
uv run uvicorn src.main:app --host 0.0.0.0 --port 8000

# 3. 前端（另一個 terminal）
cd frontend
pnpm install
pnpm dev            # 或 pnpm build && pnpm start

# 4. 在電視瀏覽器打開（把 IP 換成這台機器的區域網 IP）
#    Player：http://<本機IP>:3000/r/home/player
#    手機掃畫面上的 QR code 即進入點歌頁
#    Admin ：http://<本機IP>:3000/admin
```

前端若**沒設定** `NEXT_PUBLIC_API_URL`，會自動連同主機的 `:8000` 後端（區域網模式）。
跑在單一網域的反向代理（Cloudflare/Nginx）後面時，把它設成那個對外網址即可（見下）。

## 密碼（都可改，預設僅供開箱）

| 用途 | 預設 | 怎麼改 |
|---|---|---|
| 入房密碼（手機進 `home` 房） | `home` | Admin 頁 → 房間 → 入房密碼 |
| Remote 管理員模式（拖曳排序/刪歌） | `homeadmin` | Admin 頁 → 房間 → 管理員密碼 |
| Admin 後台登入 | `.env` 的 `ADMIN_PASSWORD`（範例值 `admin`） | 改 `.env` 後重啟後端 |

- 新房間的管理員模式預設密碼 = `<房間ID>admin`。
- 三者獨立：入房 ≠ Remote 管理員模式 ≠ Admin 後台。
- **公開部署前務必改掉 `ADMIN_PASSWORD` 與 `ADMIN_COOKIE_SECRET`。**

## 操作要點

- Player 首次播放要**點一下畫面**解鎖音訊（瀏覽器 autoplay 限制）。
- 字幕來源可在 Remote「正在播放」頁即時切換；系統處理完會背景預抓所有來源。
- 影片自動限 ≤1080p 轉碼，播當前歌時預載下一首。
- 字幕對不上：管理員用「字幕延遲」微調；音訊爆音/不同步用「回報問題」→ 下次改原始音訊。

## Stack

- **Backend**：FastAPI · SQLAlchemy 2.0 · SQLite · asyncio
- **Frontend**：Next.js 15 · Tailwind · libass-wasm · hls.js · PWA
- **Pipeline**：yt-dlp · Demucs · WhisperX · FFmpeg · pykakasi/hangul-romanize
- **Deploy**：systemd（或 Docker Compose）· Cloudflare Tunnel（可選）

## （可選）外網存取：Cloudflare Tunnel

只有要從外網用才需要。把對外網域指到本機，並讓前端知道單一網址：

```bash
# .env
PUBLIC_BASE_URL=https://ktv.example.com
COOKIE_SECURE=true                 # 一律 HTTPS 時建議開
CF_TUNNEL_UUID=<cloudflared 建好的 tunnel UUID>

# frontend：單一網域反代時，告訴前端對外網址（HTTP→ws 自動推導）
echo 'NEXT_PUBLIC_API_URL=https://ktv.example.com' > frontend/.env.production.local
pnpm --dir frontend build
```

cloudflared 把 `/api`、`/ws`、`/songs` 路由到 `:8000`，其餘到前端。
詳細步驟見 [`docs/SETUP.md`](docs/SETUP.md)，協議見 [`docs/API.md`](docs/API.md)。

## License

尚未指定正式授權（作者可日後加入 `LICENSE`）。原始碼公開供自架與學習；
商用或散布前請先聯繫作者。請保留出處。
