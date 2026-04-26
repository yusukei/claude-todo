# E2E Test Strategy

> 関連タスク: `69eda84e428d4434b4d2dcd7` (Phase 1: 基盤)
>
> 関連仕様: [CLAUDE.md "Definition of Correctly Working" (8軸定義)](../../CLAUDE.md), [No silent fallbacks](../../CLAUDE.md), [multi-worker-sidecar](./multi-worker-sidecar.md)

## 1. 目的と背景

### 1.1 解決する問題

現状、以下の二系統のテストが存在する:

- **Backend pytest** (1100+ テスト) — `mongomock-motor` + `fakeredis` を使う **mock モード** がデフォルト。
  実 MongoDB / Redis に対する `TEST_MODE=real` も実装されているが、CI では走っていない。
- **Frontend vitest** (178 テスト / 23 ファイル) — MSW で REST API を完全にモック化。
  ブラウザ DOM もしないため、レイアウト崩れ / 未マウント / route 切替後の状態保持などは検出できない。

これらは **個別コンポーネントの正しさ** は担保しているが、**スタック全体を貫通した正しさ** は保証していない。
結果として CLAUDE.md の 8 軸定義のうち以下が機械的検証から漏れている:

| Axis | 名前 | 現状の検証 | 漏れの典型例 |
|---|---|---|---|
| 4 | Shipped | 不十分 | dist にバンドルされていない CSS / chunk 落ち |
| 5 | Reachable | 無し | route が登録されておらずボタンを押しても 404 |
| 6 | Operable | 無し | 押しても画面が真っ白 / API が 422 を返してフロントが silent に握り潰す |
| 7 | Persistent | 無し | reload で task が消える / SSE が切れたまま再接続しない |
| 8 | Recoverable | 無し | network drop で「読み込み中...」のまま固まる |

E2E ハーネスはこの **5 つの軸を機械的に守らせる装置** である。

### 1.2 設計原則

1. **mock 排除** — backend は実 MongoDB / 実 Redis、frontend は MSW を bypass。
   モックは axis 6-8 を素通りさせる原因なので E2E では一切使わない。
2. **本番と同じ経路** — Traefik → frontend (nginx + 本番ビルド済 dist) → backend を経由。
   `vite dev` を E2E で使ってはいけない (`Shipped` 軸が空洞化する)。
3. **コンテナ完結** — テストランナー自体もコンテナの中で走る。ホスト OS の Node / Playwright バージョン揺らぎを排除。
4. **No silent fallbacks** — テスト失敗は即 FAIL。リトライ・条件付き skip・ベストエフォート assert は禁止。
   `page.on("pageerror")` / `page.on("console")` で `console.error` を監視し、画面が緑でもエラーが出たら FAIL。
5. **シードは API 経由のみ** — DB に直接 INSERT しない。
   ビジネスルールを通過しないと作れない状態 (例: needs_detail フラグの伝播) を E2E で再現できなくなり、現実と乖離するため。
6. **隔離** — 本番 compose と同時起動可能。コンテナ名・ネットワーク・ボリュームすべて `*-e2e` で分離。

## 2. 構成

### 2.1 ディレクトリ

```
e2e/
├── README.md                # 実行手順 + 哲学
├── Dockerfile               # Playwright runner image
├── docker-compose.e2e.yml   # フルスタック + runner
├── playwright.config.ts     # workers=1, retries=0, trace=on, video=retain-on-failure
├── package.json             # @playwright/test
├── tsconfig.json
├── .gitignore
├── .env.e2e                 # 固定値 (機密ではない、リポジトリに含める)
├── fixtures/
│   ├── auth.ts              # admin login storageState
│   └── api.ts               # シード用 REST クライアント
├── tests/
│   └── smoke/
│       ├── login.spec.ts             # axis 5-6
│       ├── project-task-crud.spec.ts # axis 5-6
│       └── task-persists-reload.spec.ts # axis 7
├── results/                 # 実行成果物 (.gitignore)
│   ├── html-report/
│   ├── traces/
│   ├── videos/
│   └── screenshots/
└── support/
    └── wait-for-stack.sh    # runner 内部で health 待ち
```

### 2.2 コンテナトポロジ

`e2e/docker-compose.e2e.yml` は本番 `docker-compose.yml` を再現するが、**完全に独立したリソース** で動く。

| サービス | 本番 compose | E2E compose | 備考 |
|---|---|---|---|
| traefik | `todo-traefik` | `todo-traefik-e2e` | ポート 8081 (本番 8080 と衝突回避) |
| backend (API) | `todo-backend` | `todo-backend-e2e` | `WEB_CONCURRENCY=1` (E2E は単純化) |
| backend-indexer | `todo-backend-indexer` | `todo-backend-indexer-e2e` | sidecar も再現 |
| frontend | `todo-frontend` | `todo-frontend-e2e` | 本番 Dockerfile 流用 (nginx + dist) |
| mongo | `todo-mongo` | `todo-mongo-e2e` | tmpfs (高速・破棄前提) |
| redis | `todo-redis` | `todo-redis-e2e` | tmpfs |
| **e2e-runner** | — | `todo-e2e-runner` | Playwright 実行 |

ネットワーク: `todo-e2e-net` (本番 `todo-network` と分離)
ボリューム: `*-e2e` 接尾辞 (本番と分離)

### 2.3 フロー

```
docker compose -f e2e/docker-compose.e2e.yml run --rm --build e2e-runner
  │
  ├─ build images (e2e-runner, backend, frontend) — 初回のみ実体ビルド
  │
  ├─ start mongo-e2e, redis-e2e          [healthcheck wait]
  │
  ├─ start backend-e2e, backend-indexer-e2e, frontend-e2e, traefik-e2e
  │   └─ backend が INIT_ADMIN_EMAIL/PASSWORD を見て admin 作成 (lifespan 内)
  │   └─ healthcheck: GET http://localhost:8000/health で 200
  │
  ├─ e2e-runner: support/wait-for-stack.sh
  │   ├─ curl -fsS http://traefik-e2e/health  (backend reachable via traefik)
  │   ├─ curl -fsS http://traefik-e2e/        (frontend reachable via traefik)
  │   └─ POST /api/v1/auth/login で admin login が通ることを確認
  │
  ├─ npx playwright test
  │
  └─ exit code = test 結果。artifacts は /results に書かれ、
     ホストの ./e2e/results にバインドマウント済
```

### 2.4 認証シード

backend の `app/main.py` lifespan に既存の自動 admin 作成ロジックがある:

```python
if settings.INIT_ADMIN_EMAIL and settings.INIT_ADMIN_PASSWORD:
    await create_admin_user(...)
```

E2E compose で以下を渡す:

```yaml
environment:
  - INIT_ADMIN_EMAIL=admin@e2e.local
  - INIT_ADMIN_PASSWORD=E2eAdmin!Pass2026
```

これにより別途 init-admin CLI を呼ばずに済む。
パスワードはリポジトリに公開する (本番値ではない、`.env.e2e` に明記)。

## 3. テスト記述規約

### 3.1 軸ラベル必須

各テスト名の prefix に対応 axis を書く:

```ts
test("[axis5][axis6] ログインフォームが見え、admin で入れる", async ({ page }) => {
  ...
});
```

これにより「どの軸を守るためのテストか」が test 名から自明になり、回帰時の意図が失われない。

### 3.2 console エラーは即 FAIL

全 spec で beforeEach に以下を入れる (fixture 化):

```ts
const errors: string[] = [];
page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
page.on("console", (msg) => {
  if (msg.type() === "error") errors.push(`console.error: ${msg.text()}`);
});
test.afterEach(() => {
  expect(errors).toEqual([]);
});
```

「画面は出ているが console に何か出ている」ケースは axis 6 違反として扱う。

### 3.3 timeout は明示

`expect(...).toBeVisible({ timeout: 5000 })` のように毎回明示する。
グローバル timeout に頼ると、本来 100ms で出るべき要素が 30s かけて出ても緑になり、回帰の予兆を見逃す。

### 3.4 シードは API 経由

`fixtures/api.ts` で `/api/v1/auth/login` → token 取得 → 必要 API を叩く helper を提供。
DB 直 INSERT は禁止。

### 3.5 リトライ禁止 (Phase 1)

`playwright.config.ts` で `retries: 0`。
flaky なテストはリトライで隠さず、原因を特定して spec を直すか quarantine フォルダへ移す。

## 4. CI 統合

`.github/workflows/ci.yml` に新規 job を追加:

```yaml
e2e:
  name: E2E (Playwright in container)
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - name: Run E2E
      run: docker compose -f e2e/docker-compose.e2e.yml run --rm --build e2e-runner
    - name: Upload artifacts
      if: always()
      uses: actions/upload-artifact@v4
      with:
        name: e2e-results
        path: e2e/results/
        retention-days: 7
    - name: Tear down
      if: always()
      run: docker compose -f e2e/docker-compose.e2e.yml down -v
```

## 5. 8 軸との対応マッピング (現フェーズ)

| Axis | 検証手段 | 該当 spec |
|---|---|---|
| 4 Shipped | nginx 配信の本番 build を Playwright が `/index.html` で取得 | 全 spec の前提 (stack 起動時) |
| 5 Reachable | route / button / form の `toBeVisible` | `login.spec.ts`, `project-task-crud.spec.ts` |
| 6 Operable | submit → 期待 DOM 変化 + console error 0 | `login.spec.ts`, `project-task-crud.spec.ts` |
| 7 Persistent | task 作成 → reload → 同じ task が見える | `task-persists-reload.spec.ts` |
| 8 Recoverable | (Phase 2 で追加: network drop / 401 リトライ等) | — |

## 6. スコープ外 (Phase 2 以降)

| 項目 | 理由 |
|---|---|
| Visual regression | 画面差分の維持コストが高く、まず軸 5-7 を固める |
| a11y axe 監査 | UI が落ち着いてから |
| MCP プロトコル E2E | 現 `test-mcp-client/` を整理してから別ジョブに |
| カオス試験 (network/redis drop) | axis 8 着手時にまとめて |
| RBAC 細粒度 | admin / user / member の 3 軸テストを Phase 2 で |

## 7. 変更時のチェックリスト

E2E ハーネスを変更する場合:

- [ ] `docker compose -f e2e/docker-compose.e2e.yml run --rm --build e2e-runner` がローカル (Windows Docker Desktop) で緑
- [ ] CI でも緑 (Linux runner)
- [ ] 失敗を意図的に仕込んだとき、`e2e/results/` に trace / video / screenshot が残ることを確認
- [ ] 本番 `docker compose up -d` と同時実行しても衝突しない
- [ ] 仕様書 (本ファイル) と CLAUDE.md の Testing セクションが乖離していないか確認
- [ ] 新規テストは 3.1 の axis ラベル prefix が付いている
