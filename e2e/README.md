# E2E Test Harness

> 仕様: [docs/architecture/e2e-strategy.md](../docs/architecture/e2e-strategy.md)
> 関連タスク: Phase 1 `69eda84e428d4434b4d2dcd7` / Phase 2 `69edad23491ee7ffd03ed2b5`

## TL;DR

```bash
docker compose -f e2e/docker-compose.e2e.yml --env-file e2e/.env.e2e \
    run --rm --build e2e-runner
```

これだけで:

1. backend / frontend / mongo / redis / traefik を E2E 専用リソースで起動
2. backend が `INIT_ADMIN_EMAIL` を見て admin を自動作成
3. runner コンテナがスタックの health を待つ
4. Playwright が Chromium で smoke + feature テストを実行
5. 成果物 (trace / video / screenshot / html-report / junit) を `e2e/results/` に書き出す
6. exit code = テスト結果

ホスト OS の Node / Playwright バージョン揺らぎに依存しない (Linux / Mac / Windows Docker Desktop で同一動作)。

## なぜこの設計か

詳細は [e2e-strategy.md](../docs/architecture/e2e-strategy.md) 参照。要点:

- **mock 排除** — backend は実 MongoDB / 実 Redis、frontend は production build を nginx 配信。
- **Traefik 経由** — 本番と完全一致した経路で SPA → Backend を辿る (Shipped / Reachable 軸)。
- **No silent fallbacks** — retries=0、console.error は即 FAIL、シードは API 経由のみ。
- **完全隔離** — 本番 `docker compose up -d` と同時実行可能 (network / volume / container 名すべて分離)。

## ディレクトリ

```
e2e/
├── Dockerfile                     # mcr.microsoft.com/playwright ベース runner
├── docker-compose.e2e.yml         # フルスタック + runner
├── playwright.config.ts           # retries=0, trace=on, video=retain-on-failure
├── package.json                   # @playwright/test のみ
├── .env.e2e                       # E2E 専用固定値 (秘密ではない)
├── traefik/
│   ├── traefik.yml                # file provider のみ
│   └── dynamic/routers.yml        # backend / frontend ルート定義
├── support/
│   ├── run.sh                     # runner ENTRYPOINT
│   └── wait-for-stack.sh          # health 待ち
├── fixtures/
│   ├── auth.ts                    # UI ログイン helper + console-error watcher
│   └── api.ts                     # シード用 REST クライアント
├── tests/
│   ├── smoke/                     # 最小到達確認 (axes 4-7)
│   │   ├── health.spec.ts
│   │   ├── login.spec.ts
│   │   └── projects-and-tasks.spec.ts
│   └── feature/                   # 機能ごとの UI 経路保護 (axes 5-7)
│       ├── task-create-via-ui.spec.ts
│       ├── task-status-change.spec.ts
│       └── task-comment.spec.ts
└── results/                       # 実行成果物 (.gitignore)
```

## よくある操作

### 特定 spec だけ流す

```bash
docker compose -f e2e/docker-compose.e2e.yml --env-file e2e/.env.e2e \
    run --rm --build e2e-runner --grep login
```

`--grep "task-status"` のように部分一致でも OK。

### 失敗時の調査

`e2e/results/html-report/index.html` をブラウザで開く (trace, video, screenshot, network log が確認可能)。

### スタックを起動したまま手動で触りたい (debug)

```bash
docker compose -f e2e/docker-compose.e2e.yml --env-file e2e/.env.e2e \
    up -d backend frontend traefik mongo redis
# → http://localhost:8081 を SPA として開ける
docker compose -f e2e/docker-compose.e2e.yml --env-file e2e/.env.e2e down -v
```

### クリーンアップ

```bash
docker compose -f e2e/docker-compose.e2e.yml --env-file e2e/.env.e2e \
    down -v --remove-orphans
```

**重要**: ローカルでスタックを使い回すと Mongo に過去 spec のテストデータが残り、検索インデックス
増加で API が遅くなる。連続実行で謎のタイムアウトが起きたら、まず `down -v` する。CI は毎回新規
ビルドなので影響なし。

## テストを追加するときの規約

1. **軸ラベルを test 名 prefix に**: `test("[axis5][axis6] ...", ...)`
2. **timeout を毎回明示**: `toBeVisible({ timeout: 5_000 })`
3. **シードは API 経由のみ**: `fixtures/api.ts` の helper を使う。DB 直叩き禁止。
4. **`attachConsoleErrorWatcher(page)` を必ず仕込む**: 画面が出ているように見えても console.error が出たら FAIL。
5. **flaky を retry で隠さない**: 原因を直すか `tests/_quarantine/` に移す (現在は未作成)。

詳細は [docs/architecture/e2e-strategy.md §3](../docs/architecture/e2e-strategy.md) を参照。

## Tips: 既知の落とし穴

Phase 2 構築中に踏んだ罠を残しておく。同じ罠を踏まないように。

### TaskCard は二重 `role="button"`

@dnd-kit の `SortableTaskCard` が外側に `<div role="button" aria-roledescription="sortable">` を
被せ、TaskCard 自身も `role="button" aria-label={title}` を持つ。
`getByRole("button", { name: title })` は両方マッチして strict mode 違反になる。

✅ **正解**: `page.getByLabel(title, { exact: true })` で aria-label 限定マッチ。
❌ **罠**: `page.getByRole("button", { name: title })`。

### list 系 API は `{items: [...]}` 形式

backend の list endpoint (e.g. `GET /api/v1/projects/{id}/tasks`) は pagination 対応で
`{items: [...], total, limit, skip}` を返す。生 array を期待して `.find()` すると死ぬ。

✅ **正解**: `fixtures/api.ts` の `listTasks(api, projectId)` を使う (内部で unwrap 済)。
❌ **罠**: `(await res.json()).find(...)`。

### APIRequestContext のデフォルトタイムアウトが短い

`request.newContext()` の `timeout` を未指定だと、Playwright の `actionTimeout` (本リポでは 5s)
が API 呼び出しにも適用される。backend 起動直後の初回 query は indexer ウォームアップで 5s
近くかかることがあり、flaky の温床。

✅ **正解**: `fixtures/api.ts` の helper は全て `timeout: 30_000` 設定済。同じ pattern を踏襲。
❌ **罠**: spec 内で直接 `request.newContext({ baseURL: ... })` を呼ぶ (timeout が短い)。

### TaskDetail comment send button に aria-label が無い

`TaskCommentSection.tsx` の送信ボタンは Send icon のみ。

✅ **正解**: `commentInput.locator("..").getByRole("button")` で textarea の親内の唯一の button を取る。
🚧 **TODO (Phase 3)**: frontend に `aria-label="コメントを送信"` を足してこの workaround を解消。

## CI

`.github/workflows/ci.yml` の `e2e` ジョブが PR で自動実行される。
失敗時は `e2e-results` artifact (retention 7 日) として trace / video / screenshot がアップロードされる。
