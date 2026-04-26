import {
  test,
  expect,
  attachConsoleErrorWatcher,
  loginViaUi,
} from "../../fixtures/auth";
import { loginAsAdminApi, createProject } from "../../fixtures/api";

/**
 * Regression: server layout fetch race close the freshly-added tab.
 *
 * production で観測された現象:
 *   ユーザが + → Terminal をクリックすると Terminal タブが一瞬出るが、
 *   直後に消える。
 *
 * 原因:
 *   `WorkbenchPage` の "Adopt server layout" Effect が、ユーザの
 *   `+` クリック直後に **遅れて返ってきた古い serverLayout** を
 *   `dispatch({type: 'replace', ...})` で上書きしていた。
 *
 *   E2E のデフォルト経路では「新規プロジェクト = serverLayout 404 →
 *   Effect が早期 return」なので race は発火せず、bug が見過ごされた。
 *
 * 本 spec の再現手順:
 *   1. 既存 layout を 1 度 PUT して server に固定する
 *   2. `GET /workbench/layouts/{projectId}` を意図的に 1.2s 遅延させる
 *   3. Workbench を開く → 早めに + → Terminal をクリック
 *   4. 遅延 GET が返ってくる → race 発火 → 修正前は Terminal タブが消えていた
 *   5. 1.5s 後にも Terminal タブが残っていることを assert
 */
test("[axis7][regression] + でタブ追加直後に server layout が遅延到着しても消えない", async ({
  page,
}) => {
  const watcher = attachConsoleErrorWatcher(page);

  const api = await loginAsAdminApi();
  const unique = Date.now();
  const project = await createProject(api, { name: `race-${unique}` });

  // ── 1. server に既定 layout (Tasks のみ) を PUT して固定 ───
  const seedTree = {
    kind: "tabs" as const,
    id: "g-seed",
    activeTabId: "p-seed",
    tabs: [{ id: "p-seed", paneType: "tasks" as const, paneConfig: {} }],
  };
  const putRes = await api.ctx.put(
    `/api/v1/workbench/layouts/${project.id}`,
    {
      data: {
        tree: seedTree,
        schema_version: 1,
        client_id: "e2e-seed",
      },
      headers: {
        Authorization: `Bearer ${api.accessToken}`,
        "Content-Type": "application/json",
      },
      timeout: 30_000,
    },
  );
  if (!putRes.ok()) {
    throw new Error(
      `seed layout PUT failed: ${putRes.status()} ${await putRes.text()}`,
    );
  }

  // ── 2. layout GET を意図的に遅延させる ────────────────
  await page.route(
    new RegExp(`/api/v1/workbench/layouts/${project.id}(?:[?].*)?$`),
    async (route) => {
      // ブラウザ側の Workbench Effect chain が確実に local 編集を
      // 走らせ終えてから server snapshot が adopt 経路に乗るよう、
      // 1.2s 待ってから本物のレスポンスを通す。
      await new Promise((r) => setTimeout(r, 1_200));
      await route.continue();
    },
  );

  // ── 3. login → workbench を開く → + → Terminal を即クリック ──
  await loginViaUi(page);
  await page
    .locator(`a[href="/projects/${project.id}"]`)
    .first()
    .click();
  await page.waitForURL(new RegExp(`/projects/${project.id}(?:[/?].*)?$`), {
    timeout: 10_000,
  });

  // localStorage 由来で Tasks タブが先に表示される
  await expect(
    page.getByRole("button", { name: "Tasks" }).first(),
  ).toBeVisible({ timeout: 10_000 });

  // GET layout がまだ返っていない (1.2s 遅延中) のを利用して + をクリック
  const addButton = page.getByRole("button", { name: "Add tab", exact: true });
  await expect(addButton).toBeVisible({ timeout: 5_000 });
  await addButton.click();
  await page.getByRole("menu", { name: "Add tab type" }).waitFor({
    state: "visible",
    timeout: 5_000,
  });
  await page
    .getByRole("menuitem", { name: "Terminal", exact: true })
    .click();

  // 直後: Terminal タブが現れる
  await expect(
    page.getByRole("button", { name: "Terminal" }).first(),
  ).toBeVisible({ timeout: 3_000 });

  // ── 4. 遅延 GET が返ってくるのを待つ + race window を超える ──
  await page.waitForTimeout(2_500);

  // ── 5. axis 7: Terminal タブが消えていない (修正されていれば残る) ──
  await expect(
    page.getByRole("button", { name: "Terminal" }).first(),
    "race fix が無効: server layout 遅延到着で Terminal タブが消えた",
  ).toBeVisible({ timeout: 1_000 });

  expect(
    watcher.errors,
    `想定外の console エラー:\n${watcher.errors.join("\n")}`,
  ).toEqual([]);

  await api.ctx.delete(`/api/v1/projects/${project.id}`, {
    headers: { Authorization: `Bearer ${api.accessToken}` },
  });
  watcher.dispose();
});
