"""Alembic environment configured for AutoBreadboard.

Mirrors the official Alembic async template: an async engine is built from
``app.settings.get_settings().database_url`` (which is postgresql+asyncpg by
construction), and migrations run via ``connection.run_sync(do_run_migrations)``.

Importing ``app.db.models`` here is what registers every model on
``Base.metadata``; ``target_metadata`` therefore reflects the same set of tables
the application uses at runtime.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context
from app.db import models  # noqa: F401  -- registers tables on Base.metadata
from app.db.base import Base
from app.settings import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override the (empty) sqlalchemy.url from alembic.ini with the live settings.
settings = get_settings()
config.set_main_option("sqlalchemy.url", str(settings.database_url))

target_metadata = Base.metadata


def _include_object(_object: object, _name: str, _type: str, _reflected: bool) -> bool:
    """Filter hook: keep autogenerate quiet when we hand-write migrations.

    Returning ``True`` keeps Alembic's autogenerate focused on the tables we
    own; we still author every migration by hand but keep the hook for future
    workflows.
    """
    return True


def run_migrations_offline() -> None:
    """Emit SQL to ``--sql`` output without an active DB connection."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=_include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations against an open sync ``Connection``."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=_include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Build the async engine from the configured URL and run migrations."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
