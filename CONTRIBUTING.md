# 協作流程

## 開始一項改動

```bash
git switch main && git pull
git switch -c fix/queue-drag        # feat/… fix/… chore/… docs/…
# 改 code、補測試
git push -u origin fix/queue-drag
gh pr create                        # 或到 GitHub 網頁開 PR
```

- `main` 受分支保護：不能直接 push，CI 的 `backend` 與 `frontend` 都通過才能合併。
- 一個 PR 做一件事；比較大的功能先開 issue 或 draft PR 討論方向。
- 合併後刪除分支。用 squash 或 merge 都可以，但同一個 PR 內的 commit 要能讀懂。

## Commit 訊息

```
fix(queue): keep manually moved songs out of fair rotation

- 說明做了什麼、為什麼
```

type 用 `feat`／`fix`／`refactor`／`test`／`docs`／`chore`，scope 寫影響的模組。

## 送 PR 前自己先跑

```bash
cd backend && uv run pytest -q tests ../scripts/test_migrate_demucs_wav_to_opus.py
cd frontend && pnpm build
```

測試不需要 GPU，也不會碰到你機器上的正式資料（`DATA_DIR` 會被隔離）。

## 注意事項

- 不要 commit `.env`、資料庫、媒體檔，或任何寫死自己機器路徑的設定。
- 改了部署方式或環境變數，要同步更新 `docs/SETUP.md` 與 `.env.example`。
- 專案的硬規則（GPU 序列化、權限 helper、刻意共用的資料等）見 [CLAUDE.md](CLAUDE.md)。

## 發版與部署

維護者把 `main` 打上 tag（例如 `v1.1.0`）並發 GitHub Release。各自的正式機依 [docs/SETUP.md](docs/SETUP.md)「更新版本」一節切換到該 tag。
