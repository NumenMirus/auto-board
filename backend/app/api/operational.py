"""Operational endpoints: health, readiness, version, metrics.

These routes are mounted at the URL root (no ``/api/v1`` prefix) because
external orchestrators (Kubernetes probes, Prometheus) need them there.
"""

from __future__ import annotations

from prometheus_client import generate_latest
from sanic import Blueprint
from sanic.request import Request
from sanic.response import HTTPResponse, json, raw

from app.db.session import get_engine
from app.settings import get_settings

__all__ = ["bp"]


bp = Blueprint("operational")


@bp.get("/healthz")
async def healthz(_: Request) -> HTTPResponse:
    """Always-200 probe (no I/O). Used by Kubernetes liveness."""
    return json({"status": "ok"}, status=200)


@bp.get("/readyz")
async def readyz(_: Request) -> HTTPResponse:
    """Readiness probe — checks DB and Redis. 503 when either is down."""
    import asyncio

    settings = get_settings()

    async def _db_ok() -> bool:
        try:
            engine = get_engine()
            async with engine.connect() as conn:
                await asyncio.wait_for(conn.execute(__import__("sqlalchemy").text("SELECT 1")), timeout=2.0)
            return True
        except Exception:
            return False

    async def _redis_ok() -> bool:
        try:
            import redis.asyncio as redis_asyncio

            client = redis_asyncio.from_url(  # type: ignore[no-untyped-call]
                str(settings.redis_url), encoding="utf-8", decode_responses=True
            )
            try:
                return bool(await asyncio.wait_for(client.ping(), timeout=2.0))
            finally:
                await client.aclose()
        except Exception:
            return False

    database, redis_ok = await asyncio.gather(_db_ok(), _redis_ok())
    body = {"database": database, "redis": redis_ok}
    if database and redis_ok:
        return json(body, status=200)
    return json(body, status=503)


@bp.get("/version")
async def version(_: Request) -> HTTPResponse:
    """Build / schema version metadata — never touches the database."""
    settings = get_settings()
    return json(
        {
            "buildSha": settings.build_sha,
            "imageTag": settings.image_tag,
            "apiVersion": "v1",
            "schemaVersion": "0001_initial",
        },
        status=200,
    )


@bp.get("/metrics")
async def metrics(_: Request) -> HTTPResponse:
    """Prometheus text exposition endpoint."""
    payload = generate_latest()
    return raw(payload, content_type="text/plain; version=0.0.4; charset=utf-8")
