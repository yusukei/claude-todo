#!/usr/bin/env bash
# E2E runner エントリポイント。
# コンテナ起動 → スタック health 待ち → playwright test を一気通貫。
# 失敗 / 成功どちらでも /e2e/results に成果物を残す (compose 経由でホストへ反映)。

set -euo pipefail

cd /e2e

echo "==> [1/3] スタック health 待ち"
bash /e2e/support/wait-for-stack.sh

echo "==> [2/3] Playwright 実行"
# 引数があればそのまま forward (例: docker compose run --rm e2e-runner --grep login)
if [ "$#" -gt 0 ]; then
  npx playwright test "$@"
else
  npx playwright test
fi
EXIT=$?

echo "==> [3/3] 完了 (exit=${EXIT}). artifacts: /e2e/results"
exit "${EXIT}"
