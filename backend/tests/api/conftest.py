"""Shared test fixtures and environment defaults for ``tests/api``.

Placeholder settings env vars are injected via an autouse fixture (not a
module-level ``os.environ.setdefault``) so they apply only for the duration of
each test in this package and are reverted afterward. A module-level mutation
would leak into the global pytest process environment and defeat
``tests/db/test_repositories.py``'s ``skipif(not os.environ.get('DATABASE_URL'))``
guard, causing it to attempt a real connection instead of skipping when no
database is configured.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _settings_env_placeholders(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide safe placeholders so ``app.settings.get_settings()`` can be
    constructed during unguarded API test runs (no PostgreSQL/Redis/S3 is
    reachable). Scoped to this fixture's test via ``monkeypatch``, so it never
    leaks into other test modules/packages.
    """
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/test")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("S3_BUCKET", "test-bucket")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "test")
    monkeypatch.setenv("ENVIRONMENT", "development")
