/**
 * MCP OAuth 2.1 E2E テスト
 *
 * TypeScript MCP SDK のクライアント認証関数を使って
 * サーバーの OAuth フローを実際のクライアント視点で検証する。
 *
 * テスト対象: https://todo.vtech-studios.com/mcp
 */

import {
  discoverOAuthProtectedResourceMetadata,
  discoverOAuthMetadata,
  registerClient,
  startAuthorization,
  exchangeAuthorization,
} from "@modelcontextprotocol/sdk/client/auth.js";

const SERVER_URL = "https://todo.vtech-studios.com/mcp";
let passed = 0;
let failed = 0;

function assert(cond, msg) {
  if (!cond) {
    console.error(`  FAIL: ${msg}`);
    failed++;
  } else {
    console.log(`  PASS: ${msg}`);
    passed++;
  }
}

async function main() {
  console.log("=== MCP OAuth E2E Test ===");
  console.log(`Server: ${SERVER_URL}\n`);

  // ── Step 1: Protected Resource Metadata Discovery ──
  console.log("Step 1: Protected Resource Metadata Discovery");
  let prm;
  try {
    prm = await discoverOAuthProtectedResourceMetadata(SERVER_URL);
    assert(prm != null, "PRM discovered");
    assert(prm.resource != null, `resource: ${prm.resource}`);
    assert(
      prm.authorization_servers?.length > 0,
      `authorization_servers: ${prm.authorization_servers}`
    );
    console.log("  PRM:", JSON.stringify(prm, null, 2));
  } catch (e) {
    console.error(`  FAIL: PRM discovery failed: ${e.message}`);
    failed++;
  }

  // ── Step 2: Authorization Server Metadata Discovery ──
  console.log("\nStep 2: Authorization Server Metadata Discovery");
  let metadata;
  try {
    metadata = await discoverOAuthMetadata(SERVER_URL);
    assert(metadata != null, "OAuth metadata discovered");
    assert(
      metadata.authorization_endpoint != null,
      `authorization_endpoint: ${metadata.authorization_endpoint}`
    );
    assert(
      metadata.token_endpoint != null,
      `token_endpoint: ${metadata.token_endpoint}`
    );
    assert(
      metadata.registration_endpoint != null,
      `registration_endpoint: ${metadata.registration_endpoint}`
    );
    console.log("  Metadata:", JSON.stringify(metadata, null, 2));
  } catch (e) {
    console.error(`  FAIL: Metadata discovery failed: ${e.message}`);
    failed++;
    console.log(`\n=== Results: ${passed} passed, ${failed} failed ===`);
    process.exit(failed > 0 ? 1 : 0);
  }

  // ── Step 3: Dynamic Client Registration ──
  console.log("\nStep 3: Dynamic Client Registration");
  const clientMetadata = {
    redirect_uris: ["http://localhost:9999/oauth/callback"],
    client_name: "MCP OAuth E2E Test",
    token_endpoint_auth_method: "none",
    grant_types: ["authorization_code", "refresh_token"],
    response_types: ["code"],
  };

  let clientInfo;
  try {
    clientInfo = await registerClient(SERVER_URL, {
      metadata: metadata,
      clientMetadata,
    });
    assert(clientInfo != null, "Client registered");
    assert(clientInfo.client_id != null, `client_id: ${clientInfo.client_id}`);
    console.log("  Client:", JSON.stringify(clientInfo, null, 2));
  } catch (e) {
    console.error(`  FAIL: Registration failed: ${e.message}`);
    failed++;
    console.log(`\n=== Results: ${passed} passed, ${failed} failed ===`);
    process.exit(failed > 0 ? 1 : 0);
  }

  // ── Step 4: Start Authorization (generate PKCE + URL) ──
  console.log("\nStep 4: Start Authorization");
  let authResult;
  try {
    authResult = await startAuthorization(SERVER_URL, {
      metadata,
      clientInformation: clientInfo,
      redirectUrl: "http://localhost:9999/oauth/callback",
    });
    assert(
      authResult.authorizationUrl != null,
      `authorizationUrl generated`
    );
    assert(
      authResult.codeVerifier != null,
      `codeVerifier: ${authResult.codeVerifier.substring(0, 20)}...`
    );
    console.log("  Auth URL:", authResult.authorizationUrl.toString());

    // Verify the URL components
    const url = new URL(authResult.authorizationUrl);
    assert(
      url.searchParams.get("response_type") === "code",
      "response_type=code"
    );
    assert(
      url.searchParams.get("client_id") === clientInfo.client_id,
      "client_id matches"
    );
    assert(
      url.searchParams.get("code_challenge_method") === "S256",
      "code_challenge_method=S256"
    );
    assert(
      url.searchParams.get("code_challenge") != null,
      "code_challenge present"
    );
    assert(
      url.searchParams.get("redirect_uri") != null,
      `redirect_uri: ${url.searchParams.get("redirect_uri")}`
    );
  } catch (e) {
    console.error(`  FAIL: Authorization start failed: ${e.message}`);
    console.error(e.stack);
    failed++;
  }

  // ── Step 5: Token Exchange (with dummy code - expect failure) ──
  console.log("\nStep 5: Token Exchange (with invalid code - expect error)");
  try {
    await exchangeAuthorization(SERVER_URL, {
      metadata,
      clientInformation: clientInfo,
      authorizationCode: "invalid_code",
      codeVerifier: authResult?.codeVerifier || "dummy",
      redirectUri: "http://localhost:9999/oauth/callback",
    });
    console.error("  FAIL: Should have thrown for invalid code");
    failed++;
  } catch (e) {
    assert(true, `Invalid code correctly rejected: ${e.message.substring(0, 80)}`);
  }

  // ── Step 6: Verify 401 triggers OAuth flow ──
  console.log("\nStep 6: Verify unauthenticated POST /mcp/ returns 401");
  try {
    const res = await fetch(SERVER_URL + "/", {
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
          clientInfo: { name: "test", version: "1.0" },
        },
        id: 1,
      }),
    });
    assert(res.status === 401, `Status: ${res.status} (expected 401)`);
    const wwwAuth = res.headers.get("www-authenticate");
    assert(wwwAuth != null, `WWW-Authenticate header present`);
    assert(wwwAuth.includes("Bearer"), `WWW-Authenticate includes Bearer`);
    console.log("  WWW-Authenticate:", wwwAuth?.substring(0, 100));
  } catch (e) {
    console.error(`  FAIL: ${e.message}`);
    failed++;
  }

  // ── Step 7: X-API-Key passthrough ──
  console.log("\nStep 7: X-API-Key passthrough (should NOT get 401)");
  try {
    const res = await fetch(SERVER_URL + "/", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json, text/event-stream",
        "X-API-Key": "test_dummy_key",
      },
      body: JSON.stringify({
        jsonrpc: "2.0",
        method: "initialize",
        params: {
          protocolVersion: "2025-03-26",
          capabilities: {},
          clientInfo: { name: "test", version: "1.0" },
        },
        id: 1,
      }),
    });
    assert(res.status === 200, `Status: ${res.status} (expected 200, X-API-Key passes auth)`);
  } catch (e) {
    console.error(`  FAIL: ${e.message}`);
    failed++;
  }

  // ── Summary ──
  console.log(`\n=== Results: ${passed} passed, ${failed} failed ===`);
  process.exit(failed > 0 ? 1 : 0);
}

main().catch((e) => {
  console.error("Fatal:", e);
  process.exit(1);
});
