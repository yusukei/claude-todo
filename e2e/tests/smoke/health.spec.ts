import { test, expect } from "@playwright/test";

/**
 * Smoke: スタックの最小到達確認.
 * Playwright runner からスタック全体への HTTP が通ることを確かめる土台テスト.
 *
 * これが落ちる場合は wait-for-stack.sh が誤検知している (= 起動シーケンスの bug)
 * か、Traefik / nginx 設定がリグレッションしている。
 */
test("[axis4][axis5] /health が 200 で {status:ok}", async ({ request }) => {
  const res = await request.get("/health");
  expect(res.status()).toBe(200);
  const body = await res.json();
  // backend/app/main.py の /health は {"status":"ok"} を返す。形が変わったら spec も更新する。
  expect(body).toMatchObject({ status: "ok" });
});

test("[axis4] / は SPA index.html を返す", async ({ request }) => {
  const res = await request.get("/");
  expect(res.status()).toBe(200);
  const body = await res.text();
  expect(body).toContain('<div id="root"');
});
