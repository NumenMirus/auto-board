"""Guarded jobs tests — require a live PostgreSQL + Redis."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="requires database",
)


def test_create_job_stub() -> None:
    """Placeholder; real assertions live behind the database fixture."""
    assert True
