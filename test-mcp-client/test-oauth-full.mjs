/**
 * MCP OAuth 2.1 完全E2Eテスト
 *
 * ブラウザ操作（ログイン + 同意画面「許可する」クリック）を含む
 * 完全な OAuth フローを自動実行する。
 *
 * フロー:
 *   1. POST /mcp/ → 401 確認
 *   2. well-known discovery
 *   3. Dynamic Client Registration
 *   4. PKCE生成 + Authorization URL構築
 *   5. Playwrightでブラウザ起動 → ログイン → 同意画面 → 「許可する」クリック
 *   6. callbackからauth code取得
 *   7. Token Exchange
 *   8. Bearer トークン付き POST /mcp/ → 200 確認
 *
 * 使用方法:
 *   LOGIN_EMAIL=admin@example.com LOGIN_PASSWORD=yourpass node test-oauth-full.mjs
 */

import { chromium } from "playwright";
import {
  discoverOAuthMetadata,
  registerClient,
  startAuthorization,
  exchangeAuthorization,
} from "@modelcontextprotocol/sdk/client/auth.js";
import http from "node:http";

const SERVER_URL =
  process.env.MCP_SERVER_URL || "https://todo.vtech-studios.com/mcp";
const LOGIN_EMAIL = process.env.LOGIN_EMAIL;
const LOGIN_PASSWORD = process.env.LOGIN_PASSWORD;

if (!LOGIN_EMAIL || !LOGIN_PASSWORD) {
  console.error(
    "Usage: LOGIN_EMAIL=... LOGIN_PASSWORD=... node test-oauth-full.mjs"
  );
  process.exit(1);
}

// Callback サーバー: Claude Desktopと同じように、redirect_uriでcodeを受け取る
function startCallbackServer() {
  return new Promise((resolve) => {
    let codeResolve;
    const codePromise = new Promise((r) => (codeResolve = r));

    const server = http.createServer((req, res) => {
      const url = new URL(req.url, "http://localhost");
      const code = url.searchParams.get("code");
      const state = url.searchParams.get("state");
      const error = url.searchParams.get("error");

      if (error) {
        res.writeHead(200, { "Content-Type": "text/html" });
        res.end(`<h1>Error: ${error}</h1>`);
        codeResolve({ error });
        return;
      }

      if (code) {
        res.writeHead(200, { "Content-Type": "text/html" });
        res.end("<h1>Authorization successful! You can close this window.</h1>");
        codeResolve({ code, state });
        return;
      }

      res.writeHead(404);
      res.end("Not found");
    });

    server.listen(0, "127.0.0.1", () => {
      const port = server.address().port;
      resolve({
        port,
        redirectUri: `http://127.0.0.1:${port}/callback`,
        waitForCode: () => codePromise,
        close: () => server.close(),
      });
    });
  });
}

async function main() {
  console.log("=== MCP OAuth 2.1 Full E2E Test (with browser) ===\n");
  console.log(`Server: ${SERVER_URL}`);
  console.log(`Login:  ${LOGIN_EMAIL}\n`);

  let passed = 0;
  let failed = 0;
  function assert(cond, msg) {
    if (!cond) {
      console.error(`  FAIL: ${msg}`);
      failed++;
      return false;
    }
    console.log(`  PASS: ${msg}`);
    passed++;
    return true;
  }

  // ── Step 1: 401 確認 ──
  console.log("Step 1: POST /mcp/ without auth → 401");
  const res401 = await fetch(SERVER_URL + "/", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json, text/event-stream",
    },
    body: JSON.stringify({
      jsonrpc: "2.0",
      method: "initialize",
      params: {
        protocolVersion: "2025-03-26",
        capabilities: {},
        clientInfo: { name: "e2e", version: "1.0" },
      },
      id: 1,
    }),
  });
  assert(res401.status === 401, `Status ${res401.status} === 401`);

  // ── Step 2: Discovery ──
  console.log("\nStep 2: OAuth Metadata Discovery");
  const metadata = await discoverOAuthMetadata(SERVER_URL);
  assert(metadata != null, "Metadata discovered");
  assert(
    metadata.token_endpoint?.includes("https://"),
    `token_endpoint: ${metadata.token_endpoint}`
  );

  // ── Step 3: Client Registration ──
  console.log("\nStep 3: Dynamic Client Registration");
  const callbackServer = await startCallbackServer();
  console.log(`  Callback server on port ${callbackServer.port}`);

  const clientInfo = await registerClient(SERVER_URL, {
    metadata,
    clientMetadata: {
      redirect_uris: [callbackServer.redirectUri],
      client_name: "E2E Full Test",
      token_endpoint_auth_method: "none",
      grant_types: ["authorization_code", "refresh_token"],
      response_types: ["code"],
    },
  });
  assert(clientInfo.client_id != null, `client_id: ${clientInfo.client_id}`);

  // ── Step 4: Start Authorization ──
  console.log("\nStep 4: Generate Authorization URL");
  const { authorizationUrl, codeVerifier } = await startAuthorization(
    SERVER_URL,
    {
      metadata,
      clientInformation: clientInfo,
      redirectUrl: callbackServer.redirectUri,
    }
  );
  assert(authorizationUrl != null, `Auth URL generated`);
  console.log(`  URL: ${authorizationUrl.toString().substring(0, 100)}...`);

  // ── Step 5: Browser → Login → Consent → Allow ──
  console.log("\nStep 5: Browser automation (login + consent)");
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  // コンソールログとエラーを記録
  page.on("console", (msg) => console.log(`  [console.${msg.type()}] ${msg.text()}`));
  page.on("pageerror", (err) => console.log(`  [pageerror] ${err.message}`));

  try {
    // Navigate to authorization URL
    console.log("  Navigating to authorize URL...");
    await page.goto(authorizationUrl.toString(), {
      waitUntil: "networkidle",
      timeout: 15000,
    });

    const currentUrl = page.url();
    console.log(`  Current URL: ${currentUrl}`);

    // ログインページにリダイレクトされた場合（React SPA なのでJS描画を待つ）
    if (currentUrl.includes("/login")) {
      console.log("  Login page detected (SPA), waiting for form to render...");

      // React SPA の描画を待機
      await page.waitForTimeout(3000);

      // ラベルテキストで input を特定（React コンポーネントの構造に依存しない）
      await page.getByLabel("メールアドレス").fill(LOGIN_EMAIL);
      await page.getByLabel("パスワード").fill(LOGIN_PASSWORD);
      console.log("  Credentials filled, submitting...");
      await page.getByRole("button", { name: "ログイン", exact: true }).click();

      // 同意画面に遷移するまで待機
      await page.waitForURL("**/consent**", { timeout: 15000 });
      console.log(`  After login: ${page.url()}`);
    }

    // 同意画面の確認
    const pageContent = await page.content();
    if (pageContent.includes("許可する")) {
      console.log('  Consent page loaded, clicking "許可する"...');

      // 「許可する」ボタンをクリック
      await page.click('button:has-text("許可する")');

      // callbackへのリダイレクトを待つ
      await page.waitForURL(`http://127.0.0.1:${callbackServer.port}/**`, {
        timeout: 15000,
      });
      console.log(`  Redirected to: ${page.url()}`);
      assert(true, "Consent submitted and redirected to callback");
    } else {
      console.log("  Page content:", pageContent.substring(0, 500));
      assert(false, "Consent page not found");
    }
  } catch (e) {
    // スクリーンショットを撮ってデバッグ
    await page.screenshot({ path: "test-oauth-error.png" });
    console.error(`  Browser error: ${e.message}`);
    console.log(`  Current URL: ${page.url()}`);
    console.log(
      `  Page content: ${(await page.content()).substring(0, 500)}`
    );
    assert(false, `Browser automation failed: ${e.message}`);
  } finally {
    await browser.close();
  }

  // ── Step 6: Get auth code from callback ──
  console.log("\nStep 6: Get auth code from callback");
  const callbackResult = await Promise.race([
    callbackServer.waitForCode(),
    new Promise((_, reject) =>
      setTimeout(() => reject(new Error("Callback timeout")), 5000)
    ),
  ]);

  if (callbackResult.error) {
    assert(false, `Callback returned error: ${callbackResult.error}`);
    callbackServer.close();
    console.log(`\n=== Results: ${passed} passed, ${failed} failed ===`);
    process.exit(1);
  }

  const authCode = callbackResult.code;
  assert(authCode != null, `Auth code received: ${authCode?.substring(0, 30)}...`);
  callbackServer.close();

  // ── Step 7: Token Exchange ──
  console.log("\nStep 7: Token Exchange");
  let tokens;
  try {
    tokens = await exchangeAuthorization(SERVER_URL, {
      metadata,
      clientInformation: clientInfo,
      authorizationCode: authCode,
      codeVerifier,
      redirectUri: callbackServer.redirectUri,
    });
    assert(tokens.access_token != null, `access_token: ${tokens.access_token?.substring(0, 30)}...`);
    assert(tokens.refresh_token != null, `refresh_token present`);
    assert(tokens.token_type?.toLowerCase() === "bearer", `token_type: ${tokens.token_type}`);
  } catch (e) {
    assert(false, `Token exchange failed: ${e.message}`);
    console.log(`\n=== Results: ${passed} passed, ${failed} failed ===`);
    process.exit(1);
  }

  // ── Step 8: Bearer MCP Request ──
  console.log("\nStep 8: POST /mcp/ with Bearer token → 200");
  const mcpRes = await fetch(SERVER_URL + "/", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "application/json, text/event-stream",
      Authorization: `Bearer ${tokens.access_token}`,
    },
    body: JSON.stringify({
      jsonrpc: "2.0",
      method: "initialize",
      params: {
        protocolVersion: "2025-03-26",
        capabilities: {},
        clientInfo: { name: "e2e-bearer", version: "1.0" },
      },
      id: 1,
    }),
  });
  assert(mcpRes.status === 200, `MCP Status: ${mcpRes.status} === 200`);

  if (mcpRes.status === 200) {
    const body = await mcpRes.text();
    assert(body.includes("McpTodo"), "MCP response contains McpTodo");
  }

  // ── Summary ──
  console.log(`\n=== Results: ${passed} passed, ${failed} failed ===`);
  process.exit(failed > 0 ? 1 : 0);
}

main().catch((e) => {
  console.error("Fatal:", e);
  process.exit(1);
});
