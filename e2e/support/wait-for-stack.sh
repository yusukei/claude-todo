#!/usr/bin/env bash
# Health 待ち。
# Traefik 経由でフロントとバックエンドが応答することを確認してから本体テストへ進む。
# どこで詰まったか分かるように、各ステップで明示的にログる (No silent fallbacks)。

set -euo pipefail

BASE="${BASE_URL_E2E:-http://traefik}"
ADMIN_EMAIL="${E2E_ADMIN_EMAIL:?E2E_ADMIN_EMAIL is required}"
ADMIN_PASSWORD="${E2E_ADMIN_PASSWORD:?E2E_ADMIN_PASSWORD is required}"

DEADLINE=$(( $(date +%s) + 180 ))   # 最大 3 分待つ

wait_for() {
  local label="$1" url="$2" expect="$3"
  echo "  [wait] ${label}: ${url}"
  while true; do
    if curl -fsS -o /tmp/last_body --max-time 5 "${url}" >/dev/null 2>&1; then
      if [ -z "${expect}" ] || grep -q "${expect}" /tmp/last_body; then
        echo "  [ok]   ${label}"
        return 0
      fi
    fi
    if [ "$(date +%s)" -ge "${DEADLINE}" ]; then
      echo "  [fail] ${label} did not become ready within deadline" >&2
      echo "  [last body]" >&2
      cat /tmp/last_body >&2 || true
      exit 1
    fi
    sleep 2
  done
}

# 1. Backend health
wait_for "backend /health" "${BASE}/health" ""

# 2. Frontend index.html (Vite ビルド成果物が nginx から配信されているか)
wait_for "frontend /" "${BASE}/" "<div id=\"root\""

# 3. Admin auto-create が完了し、ログインが通ること (=シード完了)
echo "  [wait] admin login probe"
LOGIN_DEADLINE=$(( $(date +%s) + 60 ))
while true; do
  HTTP_CODE=$(curl -s -o /tmp/login_body -w "%{http_code}" \
    -H "Content-Type: application/json" \
    -X POST "${BASE}/api/v1/auth/login" \
    -d "{\"username\":\"${ADMIN_EMAIL}\",\"password\":\"${ADMIN_PASSWORD}\"}" || echo "000")
  if [ "${HTTP_CODE}" = "200" ]; then
    echo "  [ok]   admin login"
    break
  fi
  if [ "$(date +%s)" -ge "${LOGIN_DEADLINE}" ]; then
    echo "  [fail] admin login probe failed (code=${HTTP_CODE})" >&2
    echo "  [body]" >&2
    cat /tmp/login_body >&2 || true
    exit 1
  fi
  sleep 2
done

echo "==> stack ready"
