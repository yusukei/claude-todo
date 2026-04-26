import { test, expect, attachConsoleErrorWatcher, loginViaUi } from "../../fixtures/auth";

/**
 * Smoke: ログインフォームが見え、admin で入れる.
 *
 * 検証する軸:
 *   - axis 4 Shipped:    nginx 配信の dist が `/` に index.html を返す
 *   - axis 5 Reachable:  /login が描画され email/password/submit が可視
 *   - axis 6 Operable:   submit が成功し /projects に遷移し、ヘッダ「プロジェクト」が見える
 *                        + ページ上で console.error が一切出ていない
 */
test("[axis5][axis6] ログインフォームが見え、admin で入れる", async ({ page }) => {
  const watcher = attachConsoleErrorWatcher(page);

  // axis 5 Reachable
  await page.goto("/login");
  await expect(page.locator("h1", { hasText: "MCP Todo" })).toBeVisible({ timeout: 5_000 });
  await expect(page.locator("#email")).toBeVisible();
  await expect(page.locator("#password")).toBeVisible();
  await expect(page.getByRole("button", { name: "ログイン", exact: true })).toBeEnabled();

  // axis 6 Operable
  await loginViaUi(page);
  await expect(
    page.getByRole("heading", { name: "プロジェクト", exact: true }),
  ).toBeVisible({ timeout: 10_000 });

  // axis 6 強化: console エラーが出ていない
  expect(watcher.errors, watcher.errors.join("\n")).toEqual([]);
  watcher.dispose();
});

test("[axis5][axis8] 不正パスワードはエラーメッセージを表示する", async ({ page }) => {
  await page.goto("/login");
  await page.locator("#email").fill("admin@e2e.local");
  await page.locator("#password").fill("definitely-wrong-password");
  await page.getByRole("button", { name: "ログイン", exact: true }).click();

  // axis 8 Recoverable: ユーザに何が起きたか伝える
  await expect(
    page.getByText("ユーザ名またはパスワードが正しくありません"),
  ).toBeVisible({ timeout: 5_000 });

  // ログイン画面に留まる
  await expect(page).toHaveURL(/\/login(\?.*)?$/);
});
