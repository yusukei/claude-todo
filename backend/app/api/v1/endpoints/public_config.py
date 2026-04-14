"""Public (unauthenticated) configuration endpoint.

Returns non-sensitive runtime configuration that the SPA needs before
it can authenticate.  Currently this includes the Sentry DSN so that
the frontend can self-configure error tracking without a build-time
environment variable.

The DSN host is derived from ``settings.BASE_URL`` (or
``settings.FRONTEND_URL`` as fallback) — never from client-supplied
``Host`` / ``X-Forwarded-*`` headers.  This prevents Host-header
injection attacks where an attacker could redirect SDK events to an
arbitrary domain.

Finding the right project: the first ``enabled`` ErrorProject ordered
by creation date is used.  This is deterministic (MongoDB order is
not guaranteed without an explicit sort) and correct for the typical
single-project deployment.  Multi-project deployments where a specific
project should own frontend errors can add a ``is_frontend_default``
marker in the future.
"""

from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import urlparse

from fastapi import APIRouter
from fastapi.responses import ORJSONResponse

from ....core.config import settings

router = APIRouter(tags=["config"])


@router.get("/public-config")
async def public_config() -> ORJSONResponse:
    """Return public runtime config for the SPA.

    ``sentry_dsn`` is ``null`` when no active ErrorProject exists —
    the SPA treats this as "error tracking not configured" and boots
    normally without Sentry.

    The public_key embedded in the DSN is intentionally public: it is
    designed to be shipped to browsers (write-only; gives no read
    access to stored events).
    """
    from ....models.error_tracker import ErrorProject

    # Build the DSN host from operator-configured settings, not from
    # any client-supplied header.  BASE_URL is the canonical external
    # origin of the backend; FRONTEND_URL is used as a fallback for
    # single-origin deployments where both share the same host.
    base_url = (settings.BASE_URL or settings.FRONTEND_URL).rstrip("/")
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    now = datetime.now(UTC)
    dsn: str | None = None

    # Order by created_at so the result is deterministic across restarts.
    async for ep in ErrorProject.find(ErrorProject.enabled == True).sort("+created_at"):  # noqa: E712
        active_keys = ep.active_public_keys(now)
        if not active_keys:
            continue
        public_key = active_keys[0]
        project_id = ep.project_id
        # DSN format: {scheme}://{public_key}@{host}/{project_id}
        # Sentry SDK derives the envelope URL as {scheme}://{host}/api/{project_id}/envelope/
        dsn = origin.replace("://", f"://{public_key}@", 1) + f"/{project_id}"
        break

    return ORJSONResponse({"sentry_dsn": dsn})


__all__ = ["router"]
