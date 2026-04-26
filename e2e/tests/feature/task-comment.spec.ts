import {
  test,
  expect,
  attachConsoleErrorWatcher,
  loginViaUi,
} from "../../fixtures/auth";
import { loginAsAdminApi, createProject, createTask } from "../../fixtures/api";

/**
 * Feature: TaskCommentSection でコメントを追加し、reload で残る.
 *
 * 軸:
 *   - axis 6 Operable:   textarea にテキスト入力 → 送信ボタンで API が叩かれ、コメントが見える
 *   - axis 7 Persistent: reload してもコメントが残る (実 DB に書かれている)
 *
 * 注: 送信ボタンは Send icon のみで aria-label 無し。textarea の親 (<div class="flex gap-2">) の
 *      中で唯一の button を取る。Phase 2 の宿題として frontend に aria-label を足したい。
 */
test("[axis6][axis7] TaskDetail でコメントを追加すると DB と UI に反映される", async ({
  page,
}) => {
  const watcher = attachConsoleErrorWatcher(page);

  const api = await loginAsAdminApi();
  const unique = Date.now();
  const projectName = `e2e-comment-${unique}`;
  const taskTitle = `comment-target-${unique}`;
  const commentBody = `e2e-comment-body-${unique}`;
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

  // aria-label 専用マッチで DnD ラッパーを除外
  await page.getByLabel(taskTitle, { exact: true }).click();
  const detailDialog = page.getByRole("dialog", { name: taskTitle });
  await expect(detailDialog).toBeVisible({ timeout: 5_000 });

  // axis 6: コメント入力 → submit
  const commentInput = detailDialog.getByPlaceholder(
    "コメントを入力（Markdown対応）...",
  );
  await commentInput.fill(commentBody);

  // textarea の親要素 (flex gap-2) の中の唯一の button = 送信ボタン
  const sendButton = commentInput.locator("..").getByRole("button");
  await sendButton.click();

  // axis 6: コメントが TaskDetail 内のリストに表示される
  await expect(
    detailDialog.getByText(commentBody, { exact: true }),
  ).toBeVisible({ timeout: 10_000 });

  // axis 7: reload してもコメントが残る
  await page.reload();
  await page.getByLabel(taskTitle, { exact: true }).click();
  const detailAgain = page.getByRole("dialog", { name: taskTitle });
  await expect(detailAgain).toBeVisible({ timeout: 5_000 });
  await expect(
    detailAgain.getByText(commentBody, { exact: true }),
  ).toBeVisible({ timeout: 10_000 });

  expect(
    watcher.errors,
    `想定外の console エラー:\n${watcher.errors.join("\n")}`,
  ).toEqual([]);

  await api.ctx.delete(`/api/v1/projects/${project.id}`, {
    headers: { Authorization: `Bearer ${api.accessToken}` },
  });
  watcher.dispose();
});
