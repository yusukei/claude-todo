"""Resilient StreamableHTTP app factory.

`fastmcp.server.http.create_streamable_http_app` instantiates
`StreamableHTTPSessionManager` directly with no injection point, so the only
way to plug in our `ResilientSessionManager` was to temporarily monkey-patch
the class binding inside the FastMCP module while calling the factory.

That works in practice because the monkey-patch happens during application
startup (single-threaded lifespan, no live HTTP traffic), but it's still
fragile and the reviewer flagged it as a latent race risk.

This module re-implements the FastMCP factory inline so we can pass our
custom session manager class directly. The body is kept structurally
identical to the upstream function so future FastMCP changes are easy to
diff against.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastmcp.server.http import (
    StreamableHTTPASGIApp,
    create_base_app,
)
from mcp.server.auth.routes import build_resource_metadata_url
from mcp.server.streamable_http import EventStore
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import BaseRoute, Route

from .session_manager import ResilientSessionManager

if TYPE_CHECKING:
    from fastmcp.server.auth import AuthProvider
    from fastmcp.server.http import StarletteWithLifespan
    from fastmcp.server.server import FastMCP


def create_resilient_streamable_http_app(
    server: "FastMCP",
    streamable_http_path: str,
    event_store: EventStore | None = None,
    retry_interval: int | None = None,
    auth: "AuthProvider | None" = None,
    json_response: bool = False,
    stateless_http: bool = False,
    debug: bool = False,
    routes: list[BaseRoute] | None = None,
    middleware: list[Middleware] | None = None,
) -> "StarletteWithLifespan":
    """Drop-in replacement for `fastmcp.server.http.create_streamable_http_app`
    that uses `ResilientSessionManager` for container-restart recovery.

    Mirrors the upstream signature so callers can swap one for the other.
    """
    server_routes: list[BaseRoute] = []
    server_middleware: list[Middleware] = []

    # The only meaningful difference from upstream: instantiate the
    # resilient subclass directly instead of relying on a monkey-patch.
    session_manager = ResilientSessionManager(
        app=server._mcp_server,
        event_store=event_store,
        retry_interval=retry_interval,
        json_response=json_response,
        stateless=stateless_http,
    )

    streamable_http_app = StreamableHTTPASGIApp(session_manager)

    if auth:
        from fastmcp.server.auth.middleware import RequireAuthMiddleware

        auth_middleware = auth.get_middleware()
        auth_routes = auth.get_routes(mcp_path=streamable_http_path)
        server_routes.extend(auth_routes)
        server_middleware.extend(auth_middleware)

        resource_url = auth._get_resource_url(streamable_http_path)
        resource_metadata_url = (
            build_resource_metadata_url(resource_url) if resource_url else None
        )

        http_methods = (
            ["POST", "DELETE"] if stateless_http else ["GET", "POST", "DELETE"]
        )
        server_routes.append(
            Route(
                streamable_http_path,
                endpoint=RequireAuthMiddleware(
                    streamable_http_app,
                    auth.required_scopes,
                    resource_metadata_url,
                ),
                methods=http_methods,
            )
        )
    else:
        http_methods = ["POST", "DELETE"] if stateless_http else None
        server_routes.append(
            Route(
                streamable_http_path,
                endpoint=streamable_http_app,
                methods=http_methods,
            )
        )

    if routes:
        server_routes.extend(routes)
    server_routes.extend(server._get_additional_http_routes())

    if middleware:
        server_middleware.extend(middleware)

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncGenerator[None, None]:
        async with server._lifespan_manager(), session_manager.run():
            yield

    app = create_base_app(
        routes=server_routes,
        middleware=server_middleware,
        debug=debug,
        lifespan=lifespan,
    )
    app.state.fastmcp_server = server
    app.state.path = streamable_http_path
    app.state.transport_type = "streamable-http"

    return app
