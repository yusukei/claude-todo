# Playwright runner image.
#
# 公式の Playwright イメージを使うことで、ブラウザバイナリ・OS 依存パッケージ・
# Node バージョンを Playwright のリリースに固定する。
# ホスト OS や手元の Node 環境に依存せず、CI / Linux / Windows / macOS Docker Desktop
# どこでも同一挙動になることを保証する。

FROM mcr.microsoft.com/playwright:v1.49.0-noble

WORKDIR /e2e

# 依存だけ先にインストール (キャッシュを効かせる)
COPY package.json package-lock.json* ./
RUN npm ci || npm install

# テスト本体・設定をコピー
COPY tsconfig.json playwright.config.ts ./
COPY support/ ./support/
COPY fixtures/ ./fixtures/
COPY tests/ ./tests/

# Windows 上で書き出された .sh ファイルが CRLF だと bash が `\r: command not found`
# を出してそもそも動かない。コピー直後に LF へ正規化する (No silent fallbacks の精神:
# 環境差を黙って吸収するのではなく、コンテナ境界で確実に直す)。
RUN sed -i 's/\r$//' /e2e/support/run.sh /e2e/support/wait-for-stack.sh && \
    chmod +x /e2e/support/run.sh /e2e/support/wait-for-stack.sh

# 実行時にスタックの health 待ち → playwright test の流れを内側で完結させる。
ENTRYPOINT ["/bin/bash", "-eu", "-o", "pipefail", "/e2e/support/run.sh"]
