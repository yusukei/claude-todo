# Phase C2 既存テスト去就分類

> 作成: D0 (`69ed13dd2835242574cad441`)。Phase C2 統合計画の参照ドキュメント `69ecf44d2835242574cad431` (v2.3) §9.2 に従う。
>
> 既存テスト: **23 ファイル / 178 テスト** (vitest 個別 `it()` 数)。
> 旧 v2.3 §9.2 で「199 件」としていたのは過去 vitest run の合計表示 (新規追加 5 ファイル分含めての話) であり、本 D0-3 enumerate でファイル単位 23 件 / 個別 178 件と確定。

## 5 分類ルール

- **削除予定**: D3 で対象コンポーネントごと削除されるため不要
- **移行予定**: D1-b で adapter 化に伴い props や render 方法が変わる、test は assert 修正で残す
- **不変**: そのまま残る regression watch 用
- **保留**: D3 後に再評価 (実装変化次第で削除/移行/不変が決まる)
- **新規必要**: 現在 0 件、INV カバー用に D1-b で書く

## 23 ファイル enumerate

| # | path | tests | 分類 | アクション |
|---|---|---|---|---|
| 1 | `frontend/src/__tests__/api/client.test.ts` | 4 | 不変 | axios + 401 interceptor 維持 |
| 2 | `frontend/src/__tests__/components/AdminRoute.test.tsx` | 3 | 不変 | route gating 維持 |
| 3 | `frontend/src/__tests__/components/AppInit.test.tsx` | 3 | 不変 | App 初期化維持 |
| 4 | `frontend/src/__tests__/components/ProtectedRoute.test.tsx` | 3 | 不変 | auth gate 維持 |
| 5 | `frontend/src/__tests__/components/TaskBoard.test.tsx` | 10 | **移行予定** | D1-b で adapter wrap、`mode` prop は不要のため既存 props のみで test が通る想定。視覚 regression は手動 |
| 6 | `frontend/src/__tests__/components/TaskCard.test.tsx` | 13 | 不変 | TaskCard 自体は触らない |
| 7 | `frontend/src/__tests__/components/TaskCreateModal.test.tsx` | 7 | 不変 | modal 維持 |
| 8 | `frontend/src/__tests__/components/TaskDetail.test.tsx` | 4 | **移行予定** | D1-b で `displayMode: "slideOver"\|"pane"` prop 追加、test に pane mode ケース追加 |
| 9 | `frontend/src/__tests__/components/TaskList.test.tsx` | 15 | **移行予定** | D1-b で adapter wrap、props で対応、軽微 |
| 10 | `frontend/src/__tests__/components/TaskTimeline.test.tsx` | 5 | **移行予定** | D1-b で adapter wrap、`groupBy` props 既に外部化済のため軽微 |
| 11 | `frontend/src/__tests__/hooks/useGlobalErrorHandler.test.ts` | 7 | 不変 | error handler 維持 |
| 12 | `frontend/src/__tests__/hooks/useSSE.test.ts` | 16 | **保留** | D12 (SSE 1 接続共有) で `useSSE` を `useWorkbenchSSE` 経由に refactor の可能性 → API 変更の場合 test 修正、変更なしなら不変 |
| 13 | `frontend/src/__tests__/pages/AdminPage.test.tsx` | 9 | 不変 | admin 系維持 |
| 14 | `frontend/src/__tests__/pages/LoginPage.test.tsx` | 6 | 不変 | login 維持 |
| 15 | `frontend/src/__tests__/pages/ProjectPage.test.tsx` | 5 | **削除予定** | D3 で `pages/ProjectPage.tsx` 削除に伴い test ファイル全削除 |
| 16 | `frontend/src/__tests__/pages/ProjectsPage.test.tsx` | 4 | 不変 | 一覧ページ自体維持 (card click 動線は D0-2 で要確認、現状 `/projects/:id` 直行) |
| 17 | `frontend/src/__tests__/unit/auth.store.test.ts` | 7 | 不変 | auth store 維持 |
| 18 | `frontend/src/__tests__/unit/dndZones.test.ts` | 9 | 不変 | Workbench DnD zones (PR3.5) 維持 |
| 19 | `frontend/src/__tests__/unit/eventBus.test.tsx` | 5 | 不変 | Workbench event bus (PR3) 維持 |
| 20 | `frontend/src/__tests__/unit/hotkeys.test.ts` | 12 | **移行予定** | D7 撤回で keyboard DnD shortcut なし → `Ctrl+Shift+矢印` 等の追加なし。既存の `Cmd+W` `Cmd+\` `Cmd+1..4` 等は維持。test の調整は最小限 |
| 21 | `frontend/src/__tests__/unit/presets.test.ts` | 3 | 不変 | presets 維持 |
| 22 | `frontend/src/__tests__/unit/timeline.test.ts` | 19 | 不変 | timeline lib 維持 |
| 23 | `frontend/src/__tests__/unit/treeUtilsDnd.test.ts` | 14 | 不変 | tree utils (PR3.5) 維持 |

## 分類サマリ

| 分類 | ファイル数 | テスト数 |
|---|---|---|
| 削除予定 | 1 | 5 |
| 移行予定 | 5 | 46 |
| 不変 | 16 | 111 |
| 保留 | 1 | 16 |
| 新規必要 | (D1-b で追加) | (約 20) |

## 新規必要 test (D1-b で書く、INV カバー)

Plan v2.3 §9.1 INV カタログに沿う:

| INV ID | 不変条件 | 想定 test 数 | 担当 phase |
|---|---|---|---|
| INV-1 | URL ↔ paneConfig bijection | 8+ | D3 (URL contract 実装と同時) |
| INV-2 | `?task=A` ⇒ focused TaskDetailPane.taskId | 3+ | D3 |
| INV-3 | layout schema 制約 (4 group / 8 tab/group) | 既存 + 2+ | D1-b で追加 (treeUtils 既存) |
| INV-4 | DnD ESC キャンセル後 layout 不変 | 既存 + 1 | D1-b で追加 (dndZones 既存) |
| INV-5 | TerminalPane WS が route 切替で切れない | manual D0-2 + integration 1 | D2 / D3 |
| INV-6 | storage event own-origin で無視 | 2 | D3 |
| INV-7 | 未知 query 値 fallback + console.warn | 1+ | D3 |
| INV-8 | localStorage quota exceeded → in-memory + toast | 1 | D1-b (D10 schema bump と同時) |
| INV-9 | schema migration v1 ↔ v2 (key 分離) | 3 | D1-b |
| ~~INV-10~~ | ~~keyboard DnD~~ | **削除 (Q-A 見送り)** | — |
| INV-11 | pane 幅 < 閾値 で Board が list view 自動切替 | 2 | D1-b |
| INV-12 | 複数 TaskDetailPane で focused のみ URL sync | 2 | D3 |
| **INV-13** | slide-over / modal の focus trap | 1 (manual + axe) | D1-b |
| **INV-14** | paneRegistry RBAC | 2 | D1-b |
| **INV-15** | TerminalPane inactive tab で WS 連続 (D11) | 1 | D1-b (D11 実装と同時) |
| **INV-16** | cross-tab `:backup` 退避 race | 1 | D1-b |
| **INV-17** | SSE connection 数 = 1 (D12) | 1 | D1-b |

合計新規: 約 30+ test (D1-b と D3 で分割追加)

## SHA-256 ハッシュ

各テストファイルの SHA-256 ハッシュは `git ls-tree --object-only HEAD frontend/src/__tests__` または `find frontend/src/__tests__ -type f -exec sha256sum {} \;` で取得可能。本 enumerate 時点では path + line count を identifier とし、commit 時に hash を git で trace する方針 (本 file の更新コストを避ける)。

## 完了条件

- 23 ファイル全件分類済 ✅
- 削除/移行/不変/保留/新規必要の 5 分類すべて使われている ✅
- 移行予定 / 削除予定の各 file が D1-b / D3 のどこで触られるか明示済 ✅
