# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Claude Todo is a task management system with a Claude Code MCP server integration. The MCP server is embedded in the backend (single process):

- **backend/** — Python FastAPI REST API + MCP server (port 8000)
- **frontend/** — React + TypeScript SPA (port 3000)
- **nginx/** — Reverse proxy routing (port 80)

## Commands

### Backend (Python / uv)
```bash
cd backend
uv sync                          # Install dependencies
uv run pytest                    # Run all tests (mock mode, no external deps)
uv run pytest tests/test_auth.py # Run single test file
uv run pytest -k "test_login"    # Run tests matching pattern
uv run pytest --cov              # Run with coverage (70% minimum)
TEST_MODE=real uv run pytest     # Run against real MongoDB/Redis (requires docker-compose.test.yml)
```

### Frontend (Node / npm)
```bash
cd frontend
npm install
npm run dev                      # Dev server (Vite, port 3000)
npm run build                    # tsc + vite build
npm test                         # vitest run
npm run test:watch               # vitest in watch mode
npm run test:coverage            # vitest with coverage
```

### Initial Admin Setup
```bash
cd backend
# Interactive (prompts for email/password)
uv run python -m app.cli init-admin

# With arguments
uv run python -m app.cli init-admin --email admin@example.com --password 'yourpass8+'

# Via env vars (INIT_ADMIN_EMAIL / INIT_ADMIN_PASSWORD in .env)
uv run python -m app.cli init-admin

# Docker
docker compose exec backend uv run python -m app.cli init-admin
```

### Docker Compose (full stack)
```bash
cp .env.example .env             # Configure SECRET_KEY, Google OAuth
docker compose up -d             # Start all services
docker compose down              # Stop
```

## Architecture

### Authentication Flow
- **Admin users**: Email/password with bcrypt → JWT (access 60min + refresh 7 days)
- **Regular users**: Google OAuth → requires pre-registered email in `allowed_emails` collection
- **MCP tools**: `X-API-Key` header → validated directly against `mcp_api_keys` collection (no internal HTTP)

### API Routes
- `/api/v1/auth/` — Login, Google OAuth, token refresh
- `/api/v1/users/`, `/projects/`, `/tasks/`, `/mcp_keys/` — CRUD
- `/api/v1/events?token=<jwt>` — SSE (token in URL because EventSource can't send custom headers)
- `/mcp` — MCP stateful HTTP endpoint (embedded in backend, proxied by nginx)
- `/.well-known/oauth-*` — MCP OAuth discovery metadata (manually registered)

### Backend Patterns
- **ORM**: Beanie documents (MongoDB) with custom `save_updated()` for auto-timestamps
- **Redis**: Pub/sub for SSE events (`todo:events` channel), DB 0 for app, DB 1 for MCP sessions
- **Response**: `ORJSONResponse` as default response class
- **Config**: `pydantic-settings` BaseSettings, reads from env vars / `.env`
- **main.py**: Exits on startup if `SECRET_KEY` or `REFRESH_SECRET_KEY` are default values

### Frontend Patterns
- **State**: Zustand for auth, React Query for server state
- **API**: Axios with interceptors for JWT auto-attach and token refresh
- **Routing**: React Router v6 with `ProtectedRoute` and `AdminRoute` guards
- **Styling**: Tailwind CSS, icons from lucide-react

### MCP Server (embedded in backend)
- **Location**: `backend/app/mcp/` package
- **Framework**: FastMCP 2.3+ with stateful HTTP transport
- **Mounting**: FastMCP app mounted at `/mcp` in backend's `lifespan()`
- **Session persistence**: `RedisEventStore` (Redis DB 1) for SSE session resumption
- **Session recovery**: `ResilientSessionManager` re-creates transports for unknown session IDs after restart
- **Authentication**: `authenticate()` in `mcp/auth.py` validates X-API-Key directly against DB (no internal HTTP)
- **Tools access DB directly**: MCP tools use Beanie models, no intermediate HTTP calls
- **Trailing slash**: `McpTrailingSlashMiddleware` handles `/mcp` → `/mcp/` (307 drops auth headers)
- **Well-known**: Manually registered at root level via `get_well_known_routes()`
- **PROHIBITED**: `stateless_http=True` を使用しないこと。stateful モード + RedisEventStore を維持する

### Database Collections
`users`, `projects` (with embedded `members`), `tasks` (with embedded `comments`), `allowed_emails`, `mcp_api_keys`

### Git
- コミット時に `Co-Authored-By` トレーラーを付与しない

### Testing
- **Backend**: pytest-asyncio with `mongomock-motor` + `fakeredis` (mock mode, default). Set `TEST_MODE=real` for real DB tests.
- **conftest.py**: Session-scoped DB init, function-scoped collection cleanup, pre-built fixtures (`admin_user`, `regular_user`, `admin_token`, `test_project`)
- **Frontend**: Vitest + Testing Library + MSW for API mocking
