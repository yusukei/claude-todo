FROM python:3.12-slim AS builder

WORKDIR /app
RUN pip install --no-cache-dir "uv>=0.6,<0.7"
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --frozen 2>/dev/null || uv sync --no-dev

FROM python:3.12-slim
RUN apt-get update && \
    apt-get install -y --no-install-recommends gnupg curl && \
    curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc | gpg --dearmor -o /usr/share/keyrings/mongodb-server-7.0.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg] http://repo.mongodb.org/apt/debian bookworm/mongodb-org/7.0 main" > /etc/apt/sources.list.d/mongodb-org-7.0.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends mongodb-database-tools && \
    apt-get purge -y gnupg curl && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*
RUN groupadd --system app && useradd --system --gid app app
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY app/ ./app/
ENV PATH="/app/.venv/bin:$PATH" TZ=Asia/Tokyo
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
