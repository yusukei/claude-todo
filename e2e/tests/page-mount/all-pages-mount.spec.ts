/**
 * Phase 3: 全主要ページが mount するかの診断 spec.
 *
 * 目的:
 *   - axis 5 Reachable: route が登録されており、対応 page component が render される
 *   - axis 6 Operable:  期待された見出し / 主要要素が visible になる + console.error 0
 *
 * ユーザ報告 (2026-04-26): "現在はターミナルが表示できません"。
 * 本 spec で /workspaces/terminal/:agentId の実態を機械的に確認し、
 * 修正すべき箇所を特定する。
 *
 * 落ちた route は「妥協して通す」ことなく FAIL として残し、別タスクで個別修正する。
 */
import {
  test,
  expect,
  attachConsoleErrorWatcher,
  loginViaUi,
} from "../../fixtures/auth";
import { loginAsAdminApi, createProject } from "../../fixtures/api";
import type { APIRequestContext } from "@playwright/test";

// 同一スタック内で seed を共有
test.describe.configure({ mode: "serial" });

interface SeededFixtures {
  apiCtx: APIRequestContext;
  accessToken: string;
  projectId: string;
  agentId: string;
  agentName: string;
}

let seeded: SeededFixtures;

test.beforeAll(async () => {
  const api = await loginAsAdminApi();
  const unique = Date.now();
  const project = await createProject(api, { name: `pagemount-${unique}` });

  // fake agent (実プロセスは無く、is_online=false 状態の DB レコード). TerminalPage が
  // agentId を resolve できる前提。実 agent が繋がっていないので
  // /workspaces/terminal/{agent}/sessions は 409 "Agent offline" を返し、
  // TerminalSessionList は「Failed to load sessions」を表示する想定 (axis 8 fallback)。
  const agentName = `pagemount-agent-${unique}`;
  const agentRes = await api.ctx.post("/api/v1/workspaces/agents", {
    data: { name: agentName },
    headers: {
      Authorization: `Bearer ${api.accessToken}`,
      "Content-Type": "application/json",
    },
    timeout: 30_000,
  });
  if (!agentRes.ok()) {
    throw new Error(
      `[seed] create agent failed: ${agentRes.status()} ${await agentRes.text()}`,
    );
  }
  const agent = (await agentRes.json()) as { id: string };

  seeded = {
    apiCtx: api.ctx,
    accessToken: api.accessToken,
    projectId: project.id,
    agentId: agent.id,
    agentName,
  };
});

test.afterAll(async () => {
  if (!seeded) return;
  await seeded.apiCtx.delete(`/api/v1/projects/${seeded.projectId}`, {
    headers: { Authorization: `Bearer ${seeded.accessToken}` },
  });
  await seeded.apiCtx.delete(`/api/v1/workspaces/agents/${seeded.agentId}`, {
    headers: { Authorization: `Bearer ${seeded.accessToken}` },
  });
});

/**
 * 各 route テストの共通骨格.
 * - admin login (UI)
 * - 対象 route に navigate
 * - assertion を呼び出し側に委ねる
 * - console.error 0 を assert
 */
async function visitAndAssert(
  page: import("@playwright/test").Page,
  route: string,
  assertions: () => Promise<void>,
  extraIgnoredPatterns: RegExp[] = [],
) {
  const watcher = attachConsoleErrorWatcher(page, { extraIgnoredPatterns });
  await loginViaUi(page);
  await page.goto(route);
  await assertions();
  expect(
    watcher.errors,
    `[${route}] 想定外の console エラー:\n${watcher.errors.join("\n")}`,
  ).toEqual([]);
  watcher.dispose();
}

test.describe("[axis5][axis6] 全ページ mount 診断", () => {
  test("/projects — プロジェクト一覧", async ({ page }) => {
    await visitAndAssert(page, "/projects", async () => {
      await expect(
        page.getByRole("heading", { name: "プロジェクト", exact: true }),
      ).toBeVisible({ timeout: 10_000 });
    });
  });

  test("/projects/:id/settings — プロジェクト設定", async ({ page }) => {
    await visitAndAssert(
      page,
      `/projects/${seeded.projectId}/settings`,
      async () => {
        await expect(
          page.getByRole("heading", { name: "プロジェクト設定", exact: true }),
        ).toBeVisible({ timeout: 10_000 });
      },
    );
  });

  test("/knowledge — ナレッジベース", async ({ page }) => {
    await visitAndAssert(page, "/knowledge", async () => {
      await expect(
        page.getByRole("heading", { name: "ナレッジベース", exact: true }),
      ).toBeVisible({ timeout: 10_000 });
    });
  });

  test("/docsites — ドキュメントサイト", async ({ page }) => {
    await visitAndAssert(page, "/docsites", async () => {
      await expect(
        page.getByRole("heading", { name: "ドキュメントサイト", exact: true }),
      ).toBeVisible({ timeout: 10_000 });
    });
  });

  test("/bookmarks — Common project 未設定の axis 8 fallback", async ({
    page,
  }) => {
    // Common project は CLI 経由で作る必要があり E2E スタックでは未設定。
    // この状態で BookmarksPage は明示的なエラー UI を出すべき (axis 8 Recoverable)。
    await visitAndAssert(page, "/bookmarks", async () => {
      await expect(
        page.getByText("Common プロジェクトが未設定です", { exact: true }),
      ).toBeVisible({ timeout: 10_000 });
    });
  });

  test("/workspaces — Agents 管理", async ({ page }) => {
    await visitAndAssert(page, "/workspaces", async () => {
      // sidebar の "Agents" h2 (admin only)
      await expect(
        page.getByRole("heading", { name: "Agents", exact: true }),
      ).toBeVisible({ timeout: 10_000 });
      // main の "バインド済みプロジェクト" h1
      await expect(
        page.getByRole("heading", {
          name: /バインド済みプロジェクト/,
        }),
      ).toBeVisible({ timeout: 10_000 });
    });
  });

  test("/workspaces/terminal/:agentId — TerminalPage の axis 5 mount + axis 8 offline fallback", async ({
    page,
  }) => {
    // 検証する 2 つの軸:
    //   axis 5 Reachable — TerminalPage 自体が mount し、breadcrumb の "Terminal — <name>"
    //                      リンクが visible になる (route が解決された証拠)
    //   axis 8 Recoverable — agent process が繋がっていない時、TerminalSessionList は
    //                       "Failed to load sessions:" を出してユーザに状態を伝える
    //                       (E2E 環境および本番環境で agent offline 時も同じ表示)
    //
    // ユーザ報告「ターミナルが表示できません」の原因はこの axis 8 fallback そのもの:
    // agent process が立ち上がっていないため、API が 409 Agent offline を返し、
    // TerminalSessionList の error 状態が表示される。これは UI バグではなく
    // 「Agent を起動してください」が伝わるべき文言不足の問題なので Phase 4 で改善する。
    await visitAndAssert(
      page,
      `/workspaces/terminal/${seeded.agentId}`,
      async () => {
        // axis 5: ページが mount している (breadcrumb が render された)
        await expect(
          page.getByText(`Terminal — ${seeded.agentName}`, { exact: true }),
        ).toBeVisible({ timeout: 10_000 });

        // axis 8: agent offline の時の fallback UI が出る
        await expect(
          page.getByText(/Failed to load sessions/),
        ).toBeVisible({ timeout: 15_000 });
      },
      // sessions endpoint が 409 を返す関係で `Failed to load resource: 409` が出る。
      // browser noise なので無視。
      [/Failed to load resource: the server responded with a status of 409/],
    );
  });

  test("/settings — アカウント設定", async ({ page }) => {
    await visitAndAssert(page, "/settings", async () => {
      await expect(
        page.getByRole("heading", { name: "アカウント設定", exact: true }),
      ).toBeVisible({ timeout: 10_000 });
    });
  });

  test("/admin — 管理者設定", async ({ page }) => {
    await visitAndAssert(page, "/admin", async () => {
      await expect(
        page.getByRole("heading", { name: "管理者設定", exact: true }),
      ).toBeVisible({ timeout: 10_000 });
    });
  });

  test("/no-such-route — 404 NotFoundPage", async ({ page }) => {
    await visitAndAssert(page, "/no-such-route", async () => {
      await expect(
        page.getByRole("heading", { name: "404", exact: true }),
      ).toBeVisible({ timeout: 10_000 });
    });
  });
});
