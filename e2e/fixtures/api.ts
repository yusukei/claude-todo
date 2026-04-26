/**
 * REST API クライアント (シード用).
 *
 * 設計方針: シードは API 経由のみ (DB 直叩き禁止 — docs/architecture/e2e-strategy.md §1.2 参照)
 * ビジネスルールを通過した状態のみを E2E が再現できるようにする。
 */
import { request, type APIRequestContext } from "@playwright/test";

const BASE_URL = process.env.BASE_URL_E2E ?? "http://traefik";
const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL ?? "admin@e2e.local";
const ADMIN_PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "E2eAdmin!Pass2026";

// API シード呼び出しのタイムアウト. backend が起動直後で初回 query 投入時に index 構築で
// 数秒待たされる、indexer の Tantivy フラッシュが噛み合うなどの遅延に耐えるよう余裕を持たせる.
// 30 秒以上かかる API は本物の異常なのでこの値を超えたら FAIL させて良い.
const API_TIMEOUT_MS = 30_000;

export interface ApiClient {
  ctx: APIRequestContext;
  accessToken: string;
}

/**
 * Admin として REST API にログインし、Bearer 用 access_token を保持した
 * APIRequestContext を返す。
 */
export async function loginAsAdminApi(): Promise<ApiClient> {
  const ctx = await request.newContext({
    baseURL: BASE_URL,
    timeout: API_TIMEOUT_MS,
  });
  const res = await ctx.post("/api/v1/auth/login", {
    data: { username: ADMIN_EMAIL, password: ADMIN_PASSWORD },
    headers: { "Content-Type": "application/json" },
    timeout: API_TIMEOUT_MS,
  });
  if (!res.ok()) {
    throw new Error(
      `[seed] admin login failed: ${res.status()} ${await res.text()}`,
    );
  }
  const body = (await res.json()) as { access_token: string };
  return { ctx, accessToken: body.access_token };
}

export async function createProject(
  api: ApiClient,
  body: { name: string; description?: string; color?: string },
): Promise<{ id: string; name: string }> {
  const res = await api.ctx.post("/api/v1/projects", {
    data: body,
    headers: {
      Authorization: `Bearer ${api.accessToken}`,
      "Content-Type": "application/json",
    },
    timeout: API_TIMEOUT_MS,
  });
  if (!res.ok()) {
    throw new Error(
      `[seed] create project failed: ${res.status()} ${await res.text()}`,
    );
  }
  return (await res.json()) as { id: string; name: string };
}

export async function createTask(
  api: ApiClient,
  projectId: string,
  body: { title: string; description?: string; priority?: string },
): Promise<{ id: string; title: string }> {
  // Tasks router prefix is /projects/{project_id}/tasks (see backend/app/api/v1/endpoints/tasks/__init__.py)
  const res = await api.ctx.post(
    `/api/v1/projects/${projectId}/tasks`,
    {
      data: body,
      headers: {
        Authorization: `Bearer ${api.accessToken}`,
        "Content-Type": "application/json",
      },
      timeout: API_TIMEOUT_MS,
    },
  );
  if (!res.ok()) {
    throw new Error(
      `[seed] create task failed: ${res.status()} ${await res.text()}`,
    );
  }
  return (await res.json()) as { id: string; title: string };
}

/**
 * プロジェクト内の全タスクを取得.
 * backend は `{items: [...], total, limit, skip}` 形式で返すので unwrap して配列を返す.
 */
export async function listTasks(
  api: ApiClient,
  projectId: string,
): Promise<Array<{ id: string; title: string; status: string }>> {
  const res = await api.ctx.get(`/api/v1/projects/${projectId}/tasks`, {
    headers: { Authorization: `Bearer ${api.accessToken}` },
    timeout: API_TIMEOUT_MS,
  });
  if (!res.ok()) {
    throw new Error(
      `[seed] list tasks failed: ${res.status()} ${await res.text()}`,
    );
  }
  const body = (await res.json()) as {
    items: Array<{ id: string; title: string; status: string }>;
  };
  return body.items;
}
