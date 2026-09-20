"""Async database engine and session factory.

The engine is built lazily via :func:`get_engine` so importing this module does
not require a reachable PostgreSQL: pure-domain unit tests elsewhere in the
project import ``app.settings`` (and therefore ``app.db.session`` transitively
through some call paths) without a live database being available.

Pool configuration (``pool_size=10``, ``max_overflow=5``, ``pool_pre_ping=True``)
matches the addendum §4.3 / §5 spec: bounded concurrency, server-side
validation, recycling.

Use :func:`get_session` as an async context manager::

    async with get_session() as session:
        ...
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.settings import get_settings

__all__ = ["get_engine", "get_session", "get_session_factory", "reset_engine"]


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _build_engine() -> AsyncEngine:
    """Create the async engine from the live :func:`get_settings` instance."""
    database_url = os.environ.get("DATABASE_URL")
    if database_url is None:
        database_url = str(get_settings().database_url)
    if not database_url.startswith("postgresql+asyncpg"):
        # Alembic and the API both expect the async driver; normalise in case
        # an operator passes ``postgresql://`` via configuration.
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return create_async_engine(
        database_url,
        pool_size=10,
        max_overflow=5,
        pool_pre_ping=True,
    )


def get_engine() -> AsyncEngine:
    """Return the process-wide :class:`AsyncEngine`, building it on first use."""
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide session factory, building it on first use."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


def reset_engine() -> None:
    """Dispose the cached engine; primarily for tests that swap configuration."""
    global _engine, _session_factory
    if _engine is not None:
        _engine.sync_engine.dispose(close=True)
    _engine = None
    _session_factory = None


from contextlib import asynccontextmanager  # noqa: E402  (placed after globals on purpose)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Async context manager yielding an :class:`AsyncSession`.

    Commits on a clean exit and rolls back on any exception, re-raising the
    original error after the rollback. The session is always closed.
    """
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        await session.commit()
    except BaseException:
        await session.rollback()
        raise
    finally:
        await session.close()
