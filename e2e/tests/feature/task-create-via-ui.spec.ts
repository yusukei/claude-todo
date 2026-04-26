import {
  test,
  expect,
  attachConsoleErrorWatcher,
  loginViaUi,
} from "../../fixtures/auth";
import { loginAsAdminApi, createProject, listTasks } from "../../fixtures/api";

/**
 * Feature: TaskCreateModal で UI からタスクを作る.
 *
 * 軸:
 *   - axis 5 Reachable:  「タスク追加」ボタン (aria-label) が見える、modal が dialog で開く
 *   - axis 6 Operable:   タイトル入力 → 「作成」で API が呼ばれ、カードがボードに出る
 *   - axis 7 Persistent: reload しても残る (実 Mongo に保存されている)
 *
 * セレクタ注意点:
 *   TaskCard は @dnd-kit の SortableTaskCard でラップされており、ラッパー側にも role="button"
 *   が付く。`getByRole('button', { name })` は両方マッチして strict mode 違反になるので、
 *   aria-label 専用の `getByLabel()` で内側の TaskCard を一意に取る。
 */
test("[axis5][axis6][axis7] TaskCreateModal で UI から作ったタスクがボードに出る・reload で残る", async ({
  page,
}) => {
  const watcher = attachConsoleErrorWatcher(page);

  const api = await loginAsAdminApi();
  const unique = Date.now();
  const projectName = `e2e-tcreate-${unique}`;
  const taskTitle = `ui-created-task-${unique}`;
  const project = await createProject(api, { name: projectName });

  await loginViaUi(page);
  await page
    .locator(`a[href="/projects/${project.id}"]`)
    .first()
    .click();
  await page.waitForURL(new RegExp(`/projects/${project.id}(?:[/?].*)?$`), {
    timeout: 10_000,
  });

  // axis 5: 「タスク追加」ボタン (aria-label="タスク追加") が見える
  const addButton = page.getByRole("button", {
    name: "タスク追加",
    exact: true,
  });
  await expect(addButton).toBeVisible({ timeout: 10_000 });

  // axis 5: modal を開く
  await addButton.click();
  const dialog = page.getByRole("dialog", { name: "タスクを作成" });
  await expect(dialog).toBeVisible({ timeout: 5_000 });

  // axis 6: タイトル入れて submit
  await dialog.getByPlaceholder("タスクのタイトル").fill(taskTitle);
  await dialog.getByRole("button", { name: "作成", exact: true }).click();

  // axis 6: modal が閉じ、新カードがボードに出る
  await expect(dialog).toBeHidden({ timeout: 5_000 });
  // aria-label 限定マッチで TaskCard を取る (DnD ラッパーは aria-label を持たない)
  const taskCard = page.getByLabel(taskTitle, { exact: true });
  await expect(taskCard).toBeVisible({ timeout: 10_000 });

  // axis 7: reload で残る
  await page.reload();
  await expect(
    page.getByLabel(taskTitle, { exact: true }),
  ).toBeVisible({ timeout: 10_000 });

  // 真に DB に到達したことの cross-check (UI 上の card と API list の両方で確認)
  const tasks = await listTasks(api, project.id);
  expect(tasks.find((t) => t.title === taskTitle)).toBeTruthy();

  expect(
    watcher.errors,
    `想定外の console エラー:\n${watcher.errors.join("\n")}`,
  ).toEqual([]);

  await api.ctx.delete(`/api/v1/projects/${project.id}`, {
    headers: { Authorization: `Bearer ${api.accessToken}` },
  });
  watcher.dispose();
});
