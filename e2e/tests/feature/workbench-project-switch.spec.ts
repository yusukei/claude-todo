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
 * 設計 (2026-04-27 redesign):
 *   1. localStorage は user action 時点で同期書き込み (debounce 廃止)。
 *      project 切替の race を構造的に排除。
 *   2. server saver は projectId 単位の独立 queue (Map<projectId, slot>)。
 *      A/B 間で pending が干渉しない。
 *   3. ``useWorkbenchStore`` の unmount cleanup で
 *      ``flushServerForProject(prevProjectId)`` を呼び、前 project の
 *      pending PUT を即時 fire。
 *   4. ``loadLayoutWithMeta`` の ``savedAt`` を
 *      ``state.lastUserActionAt`` 初期値に復元 (I-7 ガード継続)。
 *
 * 本 spec は **A→B→A→B→A の複数ラウンド** で layout 保持を検証する。
 */

test.describe("[refactor-p2-pre] Workbench project switch persistence", () => {
  test("[axis7] A で split → B → A 単発ラウンド: split layout が保持される", async ({
    page,
  }) => {
    const watcher = attachConsoleErrorWatcher(page);
    const api = await loginAsAdminApi();
    const stamp = Date.now();
    const projectA = await createProject(api, { name: `proj-A-${stamp}` });
    const projectB = await createProject(api, { name: `proj-B-${stamp}` });

    await seedLayout(
      api,
      projectA.id,
      makeTabsNode([makePane("tasks"), makePane("terminal")]),
    );
    await seedLayout(api, projectB.id, makeTabsNode([makePane("tasks")]));

    // ── A 初回: split ────────────────────────────────────────
    await openWorkbench(page, projectA.id);
    await expect(tabButtonByTitle(page, "Tasks").first()).toBeVisible();
    await expect(tabButtonByTitle(page, "Terminal").first()).toBeVisible();

    const groupSelector = 'div:has(> div > button[title="Tasks"])';
    await dragTabToEdge(page, "Terminal", groupSelector, "right");
    // localStorage は同期書き込みなので debounce 待ち不要だが、server PUT
    // (500ms debounce) が確実に飛ぶよう余裕を持たせる。
    await page.waitForTimeout(900);
    await expect(page.locator("[data-panel]")).toHaveCount(2);

    // ── B → 数秒待つ → A ────────────────────────────────────
    await openWorkbench(page, projectB.id);
    await expect(tabButtonByTitle(page, "Tasks").first()).toBeVisible();
    await expect(page.locator("[data-panel]")).toHaveCount(0);
    await page.waitForTimeout(2000);

    await openWorkbench(page, projectA.id);
    await expect(tabButtonByTitle(page, "Tasks").first()).toBeVisible();
    await expect(tabButtonByTitle(page, "Terminal").first()).toBeVisible();
    await expect(page.locator("[data-panel]")).toHaveCount(2, {
      timeout: 5_000,
    });

    expect(
      watcher.errors,
      `想定外 console エラー:\n${watcher.errors.join("\n")}`,
    ).toEqual([]);

    await deleteProject(api.ctx, api.accessToken, projectA.id);
    await deleteProject(api.ctx, api.accessToken, projectB.id);
    watcher.dispose();
  });

  test("[axis7] A→B→A→B→A 複数ラウンド: 各 project の layout が独立に保持される", async ({
    page,
  }) => {
    const watcher = attachConsoleErrorWatcher(page);
    const api = await loginAsAdminApi();
    const stamp = Date.now();
    const projectA = await createProject(api, {
      name: `multi-A-${stamp}`,
    });
    const projectB = await createProject(api, {
      name: `multi-B-${stamp}`,
    });

    // A: Tasks + Terminal (split 用), B: Tasks のみ (split しない)
    await seedLayout(
      api,
      projectA.id,
      makeTabsNode([makePane("tasks"), makePane("terminal")]),
    );
    await seedLayout(api, projectB.id, makeTabsNode([makePane("tasks")]));

    // ── A 初回: split → 2 panel ──────────────────────────────
    await openWorkbench(page, projectA.id);
    await expect(tabButtonByTitle(page, "Tasks").first()).toBeVisible();
    await expect(tabButtonByTitle(page, "Terminal").first()).toBeVisible();
    const groupSelector = 'div:has(> div > button[title="Tasks"])';
    await dragTabToEdge(page, "Terminal", groupSelector, "right");
    await page.waitForTimeout(900);
    await expect(page.locator("[data-panel]")).toHaveCount(2);

    // ── 複数ラウンド A→B→A→B→A を高速切替 ─────────────────
    // 各遷移で前 project の最終 layout が確実に保持されることを assert。
    for (let round = 1; round <= 3; round += 1) {
      await openWorkbench(page, projectB.id);
      await expect(
        tabButtonByTitle(page, "Tasks").first(),
        `round ${round}: B の Tasks tab 表示`,
      ).toBeVisible();
      await expect(
        page.locator("[data-panel]"),
        `round ${round}: B は split していない (data-panel = 0)`,
      ).toHaveCount(0);
      // SSE / async events を吸収する余裕を持たせる
      await page.waitForTimeout(1500);

      await openWorkbench(page, projectA.id);
      await expect(
        tabButtonByTitle(page, "Tasks").first(),
        `round ${round}: A の Tasks tab 表示`,
      ).toBeVisible();
      await expect(
        tabButtonByTitle(page, "Terminal").first(),
        `round ${round}: A の Terminal tab 表示`,
      ).toBeVisible();
      // 最重要 assertion: A の split (2 panel) が保持されている
      await expect(
        page.locator("[data-panel]"),
        `round ${round}: A の split layout が保持されている`,
      ).toHaveCount(2, { timeout: 5_000 });
      await page.waitForTimeout(1500);
    }

    expect(
      watcher.errors,
      `想定外 console エラー:\n${watcher.errors.join("\n")}`,
    ).toEqual([]);

    await deleteProject(api.ctx, api.accessToken, projectA.id);
    await deleteProject(api.ctx, api.accessToken, projectB.id);
    watcher.dispose();
  });
});
