"""arq worker entrypoint.

Defines :class:`WorkerSettings` (the arq configuration) and the
``__main__`` block that starts the worker process. The two job functions
(``run_solver_job``, ``run_export_job``) plus the ``purge_expired_exports``
cron live under :mod:`app.jobs`.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from pathlib import Path
from typing import Any, ClassVar

import redis.asyncio as redis_asyncio
from arq.connections import RedisSettings
from arq.cron import cron

from app.jobs.export_job import run_export_job
from app.jobs.retention import purge_expired_exports
from app.jobs.solver_job import run_solver_job
from app.settings import get_settings

__all__ = ["WorkerSettings"]


async def _on_startup(ctx: dict[str, Any]) -> None:
    """arq ``on_startup`` hook: warm the DB engine, connect Redis, start the heartbeat."""
    settings = get_settings()
    # Warm the SQLAlchemy engine.
    from app.db.session import get_session_factory

    get_session_factory()
    ctx["redis"] = redis_asyncio.from_url(  # type: ignore[no-untyped-call]
        str(settings.redis_url), encoding="utf-8", decode_responses=True
    )
    await ctx["redis"].ping()

    ctx["heartbeat_stop"] = asyncio.Event()

    async def _heartbeat() -> None:
        path = Path(settings.worker_heartbeat_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        while not ctx["heartbeat_stop"].is_set():
            with contextlib.suppress(Exception):
                path.write_text(str(time.time()), encoding="utf-8")
            with contextlib.suppress(Exception):
                await ctx["redis"].set("abb:worker:heartbeat", str(time.time()), ex=60)
            try:
                await asyncio.wait_for(ctx["heartbeat_stop"].wait(), timeout=10.0)
                return
            except TimeoutError:
                continue

    ctx["heartbeat_task"] = asyncio.create_task(_heartbeat())

    # Optional prometheus endpoint for the worker.
    with contextlib.suppress(Exception):
        from prometheus_client import start_http_server

        start_http_server(settings.worker_metrics_port)


async def _on_shutdown(ctx: dict[str, Any]) -> None:
    """arq ``on_shutdown`` hook: stop the heartbeat, close Redis, dispose the engine."""
    stop: asyncio.Event | None = ctx.get("heartbeat_stop")
    if stop is not None:
        stop.set()
    task = ctx.get("heartbeat_task")
    if task is not None:
        task.cancel()
    redis_client = ctx.get("redis")
    if redis_client is not None:
        await redis_client.aclose()
    try:
        from app.db.session import get_engine

        engine = get_engine()
        await engine.dispose()
    except Exception:
        pass


class WorkerSettings:
    """arq worker configuration.

    The class is populated lazily inside ``__main__`` so importing the module
    is safe even without a reachable Redis / database. The attributes are
    read by arq's ``get_kwargs(settings_cls)`` at process startup.
    """

    functions: ClassVar[list[Any]] = [run_solver_job, run_export_job]
    cron_jobs: ClassVar[list[Any]] = [cron(purge_expired_exports, hour=set(range(24)), minute=7)]

    redis_settings: RedisSettings = RedisSettings()  # patched in __main__
    max_tries: int = 3
    retry_jobs: bool = True
    allow_abort_jobs: bool = True
    job_timeout: int = 0  # patched in __main__
    health_check_key: str = "abb:worker:health"
    health_check_interval: int = 10
    max_jobs: int = 1  # patched in __main__
    on_startup = staticmethod(_on_startup)
    on_shutdown = staticmethod(_on_shutdown)


if __name__ == "__main__":
    from arq.worker import run_worker

    settings = get_settings()
    WorkerSettings.redis_settings = RedisSettings.from_dsn(str(settings.redis_url))
    WorkerSettings.job_timeout = settings.solver_max_timeout_seconds + 60
    WorkerSettings.max_jobs = settings.worker_concurrency
    run_worker(WorkerSettings)  # type: ignore[arg-type]
