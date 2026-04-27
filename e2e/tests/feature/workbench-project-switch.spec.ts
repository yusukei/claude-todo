import {
  test,
  expect,
  attachConsoleErrorWatcher,
} from "../../fixtures/auth";
import { loginAsAdminApi, createProject } from "../../fixtures/api";
import {
  deleteProject,
  dragTabToEdge,
  makePane,
  makeTabsNode,
  openWorkbench,
  seedLayout,
  tabButtonByTitle,
} from "../../fixtures/workbench";

/**
 * [bug:69ef3633] プロジェクト切替後に元 project に戻ると Workbench
 * layout が失われる回帰テスト。
 *
 * 原因:
 *   1. ``makeDebouncedSaver`` / ``makeServerSaver`` の singleton
 *      pending が異なる projectId の save() で上書きされ、前 project の
 *      最終 layout が永続化されない。
 *   2. lazy initializer が ``lastUserActionAt`` を 0 にリセットするため、
 *      ``useInitialServerRefresh`` の stale な server payload で
 *      localStorage の最新 layout が上書きされる (I-7 ガード機能不全)。
 *
 * 修正:
 *   1. saver の ``save(projectId, ...)`` で異なる projectId が来たら
 *      既存 pending を即時 flush する (storage.ts / workbenchLayouts.ts)。
 *   2. localStorage の ``PersistedLayout.savedAt`` を
 *      ``state.lastUserActionAt`` の初期値として復元 (initialState.ts)。
 *
 * 本 spec: A で split → B → A に戻る → A の split が保持されている。
 */

test.describe("[refactor-p2-pre] Workbench project switch persistence", () => {
  test("[axis7] プロジェクト A で split → B → A に戻ると split layout が保持される", async ({
    page,
  }) => {
    const watcher = attachConsoleErrorWatcher(page);
    const api = await loginAsAdminApi();

    // 2 プロジェクトを作成
    const stamp = Date.now();
    const projectA = await createProject(api, { name: `proj-A-${stamp}` });
    const projectB = await createProject(api, { name: `proj-B-${stamp}` });

    // Project A: Tasks + Terminal を 1 group に seed
    await seedLayout(
      api,
      projectA.id,
      makeTabsNode([makePane("tasks"), makePane("terminal")]),
    );
    // Project B: Tasks 1 個だけ
    await seedLayout(api, projectB.id, makeTabsNode([makePane("tasks")]));

    // ── Step 1: A を開いて split する ────────────────────────────
    await openWorkbench(page, projectA.id);
    await expect(tabButtonByTitle(page, "Tasks").first()).toBeVisible();
    await expect(tabButtonByTitle(page, "Terminal").first()).toBeVisible();

    const groupSelector = 'div:has(> div > button[title="Tasks"])';
    await dragTabToEdge(page, "Terminal", groupSelector, "right");
    // debounce + server PUT 完了を待つ (300ms local + 500ms server + 余裕)
    await page.waitForTimeout(900);

    // 2 panel になっていることを確認
    let panels = page.locator("[data-panel]");
    await expect(panels).toHaveCount(2);

    // ── Step 2: 別 project (B) に切り替える ──────────────────────
    await openWorkbench(page, projectB.id);
    await expect(tabButtonByTitle(page, "Tasks").first()).toBeVisible();
    panels = page.locator("[data-panel]");
    // B は単一 group (split なし) → react-resizable-panels の Panel ラッパは
    // 生成されないので data-panel は 0 件 (= split していない証跡)。
    await expect(panels).toHaveCount(0);

    // ── Step 3: 数秒待つ (SSE / async event を吸収) ─────────────
    await page.waitForTimeout(2000);

    // ── Step 4: A に戻る → split layout が復元される ────────────
    await openWorkbench(page, projectA.id);
    await expect(tabButtonByTitle(page, "Tasks").first()).toBeVisible();
    await expect(tabButtonByTitle(page, "Terminal").first()).toBeVisible();

    // A は split で 2 panel あるはず
    panels = page.locator("[data-panel]");
    await expect(panels).toHaveCount(2, { timeout: 5_000 });

    expect(
      watcher.errors,
      `想定外 console エラー:\n${watcher.errors.join("\n")}`,
    ).toEqual([]);

    // ── cleanup ──────────────────────────────────────────────────
    await deleteProject(api.ctx, api.accessToken, projectA.id);
    await deleteProject(api.ctx, api.accessToken, projectB.id);
    watcher.dispose();
  });
});
