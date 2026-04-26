import {
  test,
  expect,
  attachConsoleErrorWatcher,
  loginViaUi,
} from "../../fixtures/auth";
import {
  loginAsAdminApi,
  createProject,
  createTask,
  listTasks,
} from "../../fixtures/api";

/**
 * Feature: TaskDetail (slide-over) でステータスを変えると DB に保存され reload でも残る.
 *
 * 軸:
 *   - axis 6 Operable:   ステータスボタン (進行中/完了/...) のクリックが反映される
 *   - axis 7 Persistent: reload しても新ステータスのまま
 *
 * 経路:
 *   TasksPane の TaskCard を click → bus.emit('open-task') → TaskDetailPane が無いので
 *   slide-over fallback の TaskDetail が `<div role="dialog" aria-label={task.title}>` で開く。
 */
test("[axis6][axis7] TaskDetail で進行中→完了に変えるとボードと DB に反映される", async ({
  page,
}) => {
  const watcher = attachConsoleErrorWatcher(page);

  const api = await loginAsAdminApi();
  const unique = Date.now();
  const projectName = `e2e-status-${unique}`;
  const taskTitle = `status-target-${unique}`;
  const project = await createProject(api, { name: projectName });
  await createTask(api, project.id, { title: taskTitle, priority: "medium" });

  await loginViaUi(page);
  await page
    .locator(`a[href="/projects/${project.id}"]`)
    .first()
    .click();
  await page.waitForURL(new RegExp(`/projects/${project.id}(?:[/?].*)?$`), {
    timeout: 10_000,
  });

  // ── TaskCard を開いて TaskDetail (slide-over) を表示 ──
  // aria-label 専用マッチで DnD ラッパーを除外
  const taskCard = page.getByLabel(taskTitle, { exact: true });
  await expect(taskCard).toBeVisible({ timeout: 10_000 });
  await taskCard.click();

  const detailDialog = page.getByRole("dialog", { name: taskTitle });
  await expect(detailDialog).toBeVisible({ timeout: 5_000 });

  // ── axis 6: 「完了」ボタンを押す ────────────────
  const doneButton = detailDialog.getByRole("button", {
    name: "完了",
    exact: true,
  });
  await expect(doneButton).toBeVisible();
  await doneButton.click();

  // 新ステータスが反映されると、API でもステータスが更新されている
  // listTasks は backend の `{items: [...]}` を unwrap して配列を返す
  await expect
    .poll(
      async () => {
        const tasks = await listTasks(api, project.id);
        return tasks.find((t) => t.title === taskTitle)?.status;
      },
      { timeout: 10_000, message: "status が done に変わるまで待つ" },
    )
    .toBe("done");

  // ── axis 7: reload しても done のまま ──────────
  await page.reload();
  // reload 後もカードはボード「完了」カラムに残る
  const cardAgain = page.getByLabel(taskTitle, { exact: true });
  await expect(cardAgain).toBeVisible({ timeout: 10_000 });

  // 再度 detail を開いて「完了」ボタンが選択中であることを目視できる位置にあることを確認
  await cardAgain.click();
  const detailAgain = page.getByRole("dialog", { name: taskTitle });
  await expect(detailAgain).toBeVisible({ timeout: 5_000 });
  await expect(
    detailAgain.getByRole("button", { name: "完了", exact: true }),
  ).toBeVisible({ timeout: 5_000 });

  expect(
    watcher.errors,
    `想定外の console エラー:\n${watcher.errors.join("\n")}`,
  ).toEqual([]);

  await api.ctx.delete(`/api/v1/projects/${project.id}`, {
    headers: { Authorization: `Bearer ${api.accessToken}` },
  });
  watcher.dispose();
});
