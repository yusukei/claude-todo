# Multi-Worker Operations Runbook

## Default Topology

```
nginx :80
  └─► backend (todo-backend)          WEB_CONCURRENCY=4  ENABLE_API=1  ENABLE_INDEXERS=0  ENABLE_CLIP_QUEUE=0
  └─► frontend (todo-frontend)
backend-indexer (todo-backend-indexer)  WEB_CONCURRENCY=1  ENABLE_API=0  ENABLE_INDEXERS=1  ENABLE_CLIP_QUEUE=1
mongo (todo-mongo)
redis (todo-redis)
backup (todo-backup)
```

- **backend**: Runs HTTP / MCP / WebSocket / chat / agent transport. Multiple uvicorn workers.
- **backend-indexer**: Owns Tantivy index writes and clip queue. Must be single-worker (`WEB_CONCURRENCY=1`).
- Both share the same Docker image (`./backend`), differentiated by env vars.

## Health Checks

```bash
# All services
docker compose ps

# Individual health
docker inspect --format="{{.State.Health.Status}}" todo-backend
docker inspect --format="{{.State.Health.Status}}" todo-backend-indexer

# Backend logs
docker compose logs backend --tail=50
docker compose logs backend-indexer --tail=50
```

## Common Operations

### Normal restart (zero-downtime for API)

```bash
docker compose up -d --build backend backend-indexer
```

Index writes pause during indexer restart but catch up via Redis Stream backlog.

### Scale API workers

Change `WEB_CONCURRENCY` in `.env` or override:

```bash
WEB_CONCURRENCY=8 docker compose up -d backend
```

Do NOT change `WEB_CONCURRENCY` for `backend-indexer` — Tantivy requires single-writer.

### View index consumer lag

```bash
docker compose exec redis redis-cli -a "${REDIS_PASSWORD}" \
  XINFO GROUPS index:tasks
```

Check `lag` field. If consistently growing, the indexer is falling behind.

## Emergency Rollback (Single-Process Mode)

If the sidecar architecture causes issues, roll back to single-process:

```bash
# Step 1: Flip backend to single-process mode
ENABLE_INDEXERS=1 ENABLE_CLIP_QUEUE=1 WEB_CONCURRENCY=1 docker compose up -d backend

# Step 2: Stop the indexer sidecar
docker compose stop backend-indexer
```

Index volumes are mounted on both containers, so no data migration is needed.

### Restore multi-worker mode

```bash
# Uses defaults from docker-compose.yml
docker compose up -d backend backend-indexer
```

## Troubleshooting

### Symptom: Search results stale / not updating

1. Check indexer is running: `docker compose ps backend-indexer`
2. Check indexer logs: `docker compose logs backend-indexer --tail=100`
3. Check Redis Stream lag (see above)
4. If indexer is crashed-looping, check Tantivy lock files in the index volume

### Symptom: Bookmark thumbnails not generating

1. Check clip queue is enabled on indexer: `docker compose exec backend-indexer env | grep ENABLE_CLIP_QUEUE`
2. Check indexer logs for clip errors
3. Verify Playwright/browser deps in the container

### Symptom: API errors after scaling workers

1. Verify `ENABLE_INDEXERS=0` on backend (prevents double-writer)
2. Check Redis connectivity from all workers
3. Check MCP auth cache TTL (`MCP_AUTH_CACHE_TTL_SECONDS`, default 30s)

## Environment Variables Reference

| Variable | backend (default) | backend-indexer | Description |
|---|---|---|---|
| `ENABLE_API` | 1 | 0 | Enable HTTP/MCP/WebSocket endpoints |
| `ENABLE_INDEXERS` | 0 | 1 | Enable Tantivy index consumer |
| `ENABLE_CLIP_QUEUE` | 0 | 1 | Enable bookmark clip worker |
| `WEB_CONCURRENCY` | 4 | 1 | uvicorn worker count |
| `MCP_AUTH_CACHE_TTL_SECONDS` | 30 | - | API key cache TTL (seconds) |

## Design Reference

Full architecture: `docs/architecture/multi-worker-sidecar.md`
