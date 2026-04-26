/**
 * 認証関連の Playwright fixtures / helper.
 *
 * 方針:
 *   - 認証 cookie はバックエンドが Set-Cookie で返すので、ブラウザコンテキスト経由で
 *     UI ログインを通す方式と、API ログインで取得した cookie を browser に注入する
 *     方式の 2 通りを提供する。
 *   - Phase 1 では「UI ログインそのものを spec で検証する」ため、汎用 fixture は
 *     `loginViaApi()` の方を多用する想定 (高速かつ安定)。
 *   - パスワード平文をテストコードに書かず env から取る。
 */
import { test as base, type Page, type BrowserContext } from "@playwright/test";

const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL ?? "admin@e2e.local";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "E2eAdmin!Pass2026";

/**
 * UI から admin ログインを実施 (spec 本体で使う).
 *
 * 成功時の保証:
 *   1. URL が /projects に遷移している
 *   2. ProjectsPage の heading が visible
 *   3. AppInit (`/auth/me` bootstrap) が完了している
 *
 * (3) を待たないと直後の `page.goto(...)` で in-flight な /auth/me がアボートされ、
 * AppInit が `console.error('AppInit /auth/me failed: TypeError: Failed to fetch')`
 * を吐く。これは axis 6 違反として正しく検出される類のエラーなので E2E 側で
 * 回避するために heading を待つ。
 */
export async function loginViaUi(page: Page): Promise<void> {
  await page.goto("/login");
  await page.locator("#email").fill(ADMIN_EMAIL);
  await page.locator("#password").fill(ADMIN_PASSWORD);
  await page.getByRole("button", { name: "ログイン", exact: true }).click();
  await page.waitForURL(/\/projects(\?.*)?$|\/projects$/, { timeout: 10_000 });
  await page
    .getByRole("heading", { name: "プロジェクト", exact: true })
    .waitFor({ state: "visible", timeout: 10_000 });
}

/**
 * API ログインで取得した cookie をブラウザコンテキストへ注入する.
 */
export async function loginViaApiAndInject(
  context: BrowserContext,
  baseURL: string,
): Promise<void> {
  const res = await context.request.post("/api/v1/auth/login", {
    data: { username: ADMIN_EMAIL, password: ADMIN_PASSWORD },
    headers: { "Content-Type": "application/json" },
  });
  if (!res.ok()) {
    throw new Error(
      `[fixture] api login failed: ${res.status()} ${await res.text()}`,
    );
  }
  void baseURL;
}

/**
 * 既知の "意味のない" console エラー。
 *
 * これらは「アプリの異常」ではなく、Chromium がネットワーク失敗を勝手に
 * `console.error` として吐く類のもの。アプリのフロー上は正常 (例: 未ログインで
 * /auth/me が 401、optional な layout を読みに行って 404)。
 *
 * 注意: 単に黙らせるとアプリの本物のエラーまで隠す危険があるので、
 *   - "Failed to load resource" + 期待 status code 限定で wildcard
 *   - それ以外の console.error は依然として全件 FAIL 扱い
 *   - 真に壊れている 404/401 (例: API の path 変更) は network assertion で別途検出する想定
 */
const DEFAULT_IGNORED_PATTERNS: RegExp[] = [
  // 未ログイン時の /auth/me bootstrap 401
  /Failed to load resource: the server responded with a status of 401/,
  // 「あれば使う、なければデフォルト」型 optional resource (workbench layout 等) の 404
  /Failed to load resource: the server responded with a status of 404/,
];

type ErrorWatcher = {
  errors: string[];
  dispose: () => void;
};

export interface WatcherOptions {
  /** これらにマッチしたメッセージは無視 (DEFAULT_IGNORED_PATTERNS に追加される). */
  extraIgnoredPatterns?: RegExp[];
}

export function attachConsoleErrorWatcher(
  page: Page,
  opts: WatcherOptions = {},
): ErrorWatcher {
  const ignored = [
    ...DEFAULT_IGNORED_PATTERNS,
    ...(opts.extraIgnoredPatterns ?? []),
  ];
  const errors: string[] = [];
  const isIgnored = (msg: string) => ignored.some((re) => re.test(msg));

  const onPageError = (e: Error) => {
    const msg = `pageerror: ${e.message}`;
    if (!isIgnored(msg)) errors.push(msg);
  };
  const onConsole = (msg: import("@playwright/test").ConsoleMessage) => {
    if (msg.type() !== "error") return;
    const txt = `console.error: ${msg.text()}`;
    if (!isIgnored(txt)) errors.push(txt);
  };
  page.on("pageerror", onPageError);
  page.on("console", onConsole);
  return {
    errors,
    dispose: () => {
      page.off("pageerror", onPageError);
      page.off("console", onConsole);
    },
  };
}

/**
 * 共通 fixture: page にエラーウォッチャを自動装着する.
 */
export const test = base.extend<{
  errorWatcher: ErrorWatcher;
}>({
  errorWatcher: async ({ page }, use) => {
    const w = attachConsoleErrorWatcher(page);
    await use(w);
    w.dispose();
  },
});

export const expect = base.expect;
