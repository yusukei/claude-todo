import { test, expect, attachConsoleErrorWatcher, loginViaUi } from "../../fixtures/auth";
import { loginAsAdminApi, createProject, createTask } from "../../fixtures/api";

/**
 * Smoke: API でプロジェクト+タスクを seed → UI で見える → reload しても残る.
 *
 * 検証する軸:
 *   - axis 5 Reachable:  /projects 一覧にカードが描画される
 *   - axis 6 Operable:   カードを開くとタスクボードが表示される
 *   - axis 7 Persistent: reload してもタスクが消えない (Mongo 永続化)
 */
test("[axis5][axis6][axis7] seed されたプロジェクトとタスクが UI に出る・reload で残る", async ({
  page,
}) => {
  const watcher = attachConsoleErrorWatcher(page);

  // ── seed (API 経由のみ) ──────────────────────────────
  const api = await loginAsAdminApi();
  const unique = Date.now();
  const projectName = `e2e-smoke-${unique}`;
  const taskTitle = `e2e-task-${unique}`;
  const project = await createProject(api, {
    name: projectName,
    description: "smoke 用",
  });
  const task = await createTask(api, project.id, {
    title: taskTitle,
    description: "must survive reload",
    priority: "medium",
  });

  // ── login + 一覧確認 (axis 5) ────────────────────────
  // プロジェクト名はサイドバー + カードの両方に出るので href ベースで一意特定する。
  await loginViaUi(page);
  const projectLink = page
    .locator(`a[href="/projects/${project.id}"]`)
    .first();
  await expect(projectLink).toBeVisible({ timeout: 10_000 });

  // ── プロジェクトを開く (axis 6) ─────────────────────
  await projectLink.click();
  await page.waitForURL(new RegExp(`/projects/${project.id}(?:[/?].*)?$`), {
    timeout: 10_000,
  });
  await expect(
    page.getByText(taskTitle, { exact: true }).first(),
  ).toBeVisible({ timeout: 10_000 });

  // ── reload しても task が残る (axis 7) ───────────────
  await page.reload();
  await expect(
    page.getByText(taskTitle, { exact: true }).first(),
  ).toBeVisible({ timeout: 10_000 });

  // axis 6 強化: console エラーが出ていない (browser noise はフィルタ済)
  expect(
    watcher.errors,
    `想定外の console エラー:\n${watcher.errors.join("\n")}`,
  ).toEqual([]);

  // 自前掃除 (tmpfs だが他 spec への汚染を避ける)
  await api.ctx.delete(`/api/v1/projects/${project.id}`, {
    headers: { Authorization: `Bearer ${api.accessToken}` },
  });
  void task;

  watcher.dispose();
});
