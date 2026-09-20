"""SQLAlchemy 2.0 declarative base for AutoBreadboard persistence.

The single ``Base`` declared here is the parent of every ORM model in
``app.db.models`` and is the ``target_metadata`` for Alembic autogenerate.

This module deliberately stays free of any environment-coupled imports so it
can be loaded during collection of pure unit tests that do not have a running
PostgreSQL.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase

__all__ = ["Base"]


class Base(DeclarativeBase):
    """Declarative base for all AutoBreadboard ORM models."""
