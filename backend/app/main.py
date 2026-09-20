"""Sanic application entrypoint.

This module wires the HTTP layer (middleware, exception handler, blueprints) to
the application settings and the cached infrastructure handles built during
``before_server_start``. It is the only place that imports Sanic; every other
slice stays framework-agnostic.

The worker (``app.worker``) reuses the same engine / Redis / S3 wiring but
bypasses Sanic entirely.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

import redis.asyncio as redis_asyncio
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from pydantic import ValidationError
from sanic import Blueprint, Sanic
from sanic.blueprints import BlueprintGroup
from sanic.exceptions import NotFound
from sanic.request import Request
from sanic.response import HTTPResponse, json

from app.api import (
    boards as api_boards,
)
from app.api import (
    exports as api_exports,
)
from app.api import (
    jobs as api_jobs,
)
from app.api import (
    layouts as api_layouts,
)
from app.api import (
    operational,
)
from app.api import (
    projects as api_projects,
)
from app.api import (
    validate as api_validate,
)
from app.core.errors import AppError, to_response
from app.core.logging import bind_context, clear_context, configure_logging, get_logger
from app.core.metrics import (
    HTTP_REQUEST_DURATION_SECONDS,
    HTTP_REQUESTS_IN_PROGRESS,
    HTTP_REQUESTS_TOTAL,
)
from app.db.session import get_engine, get_session_factory
from app.domain.boards.registry import BUILTIN_BOARDS
from app.domain.footprints.registry import FOOTPRINTS
from app.domain.index import BoardIndex
from app.domain.models import BreadboardModel
from app.settings import Settings, get_settings

__all__ = ["create_app"]


def _build_index_cache() -> dict[str, BoardIndex]:
    """Pre-populate the index cache with every built-in breadboard.

    ``BoardIndex`` models breadboard-specific structure (electrical groups,
    rail lattice, center-gap row split) that perfboards don't have — those
    are indexed by the trace router's own ``MazeGraph`` instead.
    """
    return {
        board_id: BoardIndex.build(board)
        for board_id, board in BUILTIN_BOARDS.items()
        if isinstance(board, BreadboardModel)
    }


def create_app() -> Sanic[Any, Any]:
    """Build, configure and return the Sanic application instance."""
    settings = get_settings()
    configure_logging(
        log_level=settings.log_level,
        service="autobreadboard-api",
        environment=settings.environment,
    )

    app: Sanic[Any, Any] = Sanic("autobreadboard-api")
    app.config.REQUEST_MAX_SIZE = 8_000_000
    app.config.GRACEFUL_SHUTDOWN_TIMEOUT = 25.0
    app.config.ACCESS_LOG = False
    app.config.MOTD = False

    # ----------------------------------------------------------------------
    # Middleware
    # ----------------------------------------------------------------------

    @app.on_request
    async def _on_request(request: Request) -> None:
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        request.ctx.request_id = request_id
        bind_context(request_id=request_id)
        request.ctx._start_time = time.perf_counter()
        HTTP_REQUESTS_IN_PROGRESS.inc()

    @app.on_response  # type: ignore[untyped-decorator]
    async def _on_response(request: Request, response: HTTPResponse) -> None:
        elapsed = time.perf_counter() - getattr(request.ctx, "_start_time", time.perf_counter())
        method = request.method
        path = request.path
        status_code = str(response.status)
        HTTP_REQUEST_DURATION_SECONDS.labels(method, path).observe(elapsed)
        HTTP_REQUESTS_TOTAL.labels(method, path, status_code).inc()
        HTTP_REQUESTS_IN_PROGRESS.dec()
        # Echo the request id back so clients can correlate logs.
        response.headers["X-Request-Id"] = getattr(request.ctx, "request_id", "")
        # CORS: allow configured origins only; never wildcard.
        origin = request.headers.get("Origin")
        if origin and origin in settings.cors_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
        clear_context()

    # OPTIONS preflight — respond directly for the configured origins.
    @app.middleware("request", priority=1)
    async def _cors_preflight(request: Request) -> HTTPResponse | None:
        if request.method != "OPTIONS":
            return None
        origin = request.headers.get("Origin")
        if not origin or origin not in settings.cors_origins:
            return None
        headers = {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, If-Match, Idempotency-Key, X-Request-Id",
            "Access-Control-Max-Age": "600",
            "Vary": "Origin",
        }
        return HTTPResponse(status=204, headers=headers)

    # ----------------------------------------------------------------------
    # Exception handlers
    # ----------------------------------------------------------------------

    @app.exception(AppError)
    async def _on_app_error(request: Request, exception: AppError) -> HTTPResponse:
        return json(exception.to_response(), status=exception.status)

    @app.exception(ValidationError)
    async def _on_validation_error(request: Request, exception: ValidationError) -> HTTPResponse:
        return json(to_response("VALIDATION_ERROR", str(exception)), status=422)

    @app.exception(NotFound)
    async def _on_not_found(request: Request, exception: NotFound) -> HTTPResponse:
        return json(to_response("NOT_FOUND", "resource not found"), status=404)

    @app.exception(Exception)
    async def _on_unhandled(request: Request, exception: Exception) -> HTTPResponse:
        get_logger().exception("unhandled exception", error=str(exception))
        return json(to_response("INTERNAL", "internal server error"), status=500)

    # ----------------------------------------------------------------------
    # Listeners
    # ----------------------------------------------------------------------

    @app.before_server_start
    async def _before_start(sanic_app: Sanic[Any, Any]) -> None:
        # Warm the SQLAlchemy engine / session factory. This is lazy (no
        # connection attempt), matching `/readyz`'s independent DB check.
        get_session_factory()
        # Redis async client for cancellation flags / progress. `from_url`
        # does not connect until the first command is issued, so this never
        # blocks or raises even when Redis is unreachable.
        redis_client = redis_asyncio.from_url(  # type: ignore[no-untyped-call]
            str(settings.redis_url), encoding="utf-8", decode_responses=True
        )
        sanic_app.ctx.redis = redis_client
        sanic_app.ctx.boards = dict(BUILTIN_BOARDS)
        sanic_app.ctx.footprints = dict(FOOTPRINTS)
        sanic_app.ctx.board_indexes = _build_index_cache()

        # The arq pool used to enqueue solver/export jobs. `create_pool`
        # pings Redis internally and RAISES after its retry budget is
        # exhausted — that must never crash the whole API process at boot.
        # Kubernetes starts pods before their dependencies are necessarily
        # ready (that is exactly what readiness probes are for); the pod
        # must come up, serve `/healthz`, report `/readyz` as not-ready, and
        # self-heal once Redis becomes reachable, without a restart.
        sanic_app.ctx.arq = None

        async def _connect_arq_with_retry() -> None:
            delay = 1.0
            while True:
                try:
                    sanic_app.ctx.arq = await create_pool(RedisSettings.from_dsn(str(settings.redis_url)))
                    get_logger().info("arq pool connected")
                    return
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    get_logger().warning(
                        "arq pool connection failed, retrying", error=str(exc), delay_s=delay
                    )
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 30.0)

        sanic_app.ctx.arq_connect_task = sanic_app.add_task(_connect_arq_with_retry())
        sanic_app.ctx.ready = True

    @app.before_server_stop
    async def _before_stop(sanic_app: Sanic[Any, Any]) -> None:
        sanic_app.ctx.ready = False
        # Give the readiness probe a couple of seconds to flip before
        # open connections start to drain.
        await asyncio.sleep(2)

    @app.after_server_stop
    async def _after_stop(sanic_app: Sanic[Any, Any]) -> None:
        # Cancel the background arq-connect retry loop if it never succeeded.
        connect_task: asyncio.Task[None] | None = getattr(sanic_app.ctx, "arq_connect_task", None)
        if connect_task is not None and not connect_task.done():
            connect_task.cancel()
        # Close redis / arq pool.
        arq_pool: ArqRedis | None = getattr(sanic_app.ctx, "arq", None)
        if arq_pool is not None:
            await arq_pool.aclose()
        redis_client: redis_asyncio.Redis | None = getattr(sanic_app.ctx, "redis", None)
        if redis_client is not None:
            await redis_client.aclose()
        # Dispose the SQLAlchemy engine last so in-flight requests can finish.
        engine = get_engine()
        await engine.dispose()

    # ----------------------------------------------------------------------
    # Blueprints
    # ----------------------------------------------------------------------

    app.blueprint(operational.bp)
    # Each blueprint already declares ``url_prefix="/api/v1"``; pass them
    # through a group so registration stays in one place.
    api_v1_group: BlueprintGroup = Blueprint.group(
        api_boards.bp,
        api_projects.bp,
        api_validate.bp,
        api_jobs.bp,
        api_layouts.bp,
        api_exports.bp,
    )
    app.blueprint(api_v1_group)

    return app


def _run(settings: Settings, app_obj: Sanic[Any, Any]) -> None:
    if settings.environment == "development":
        app_obj.run(
            host=settings.api_host,
            port=settings.api_port,
            auto_reload=True,
            workers=1,
        )
    else:
        app_obj.run(
            host=settings.api_host,
            port=settings.api_port,
            single_process=True,
        )


# Created at module level (not gated behind `if __name__ == "__main__"`) so
# Sanic's auto-reload subprocess — which re-imports this module and looks the
# app up via `Sanic.get_app(name)` — always finds a registered instance
# regardless of how the module was imported. Building the app here has no
# external side effects: listeners run later, at actual server startup.
app = create_app()

if __name__ == "__main__":
    settings = get_settings()
    _run(settings, app)
