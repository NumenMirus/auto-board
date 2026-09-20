"""Unguarded tests for operational endpoints (no DB needed)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sanic import Sanic


def _make_app() -> Sanic[Any, Any]:
    """Return a fresh Sanic app with the operational endpoints mounted."""
    # The full app requires Redis/DB to come up; for unguarded tests we mount
    # only the operational blueprint which has no I/O besides ``/readyz``
    # (which we don't exercise here). This avoids forcing ``get_settings()``
    # to run during test collection.
    from app.api.operational import bp as operational_bp

    test_app = Sanic(f"test-operational-{uuid.uuid4().hex}")
    test_app.blueprint(operational_bp)
    return test_app


@pytest.fixture
def app() -> Sanic[Any, Any]:
    return _make_app()


def _get(test_app: Sanic[Any, Any], path: str) -> tuple[int, Any]:
    _request, response = test_app.test_client.get(path)
    return response.status, response.json


def test_healthz_returns_ok() -> None:
    test_app = _make_app()
    status, body = _get(test_app, "/healthz")
    assert status == 200
    assert body == {"status": "ok"}


def test_version_returns_keys() -> None:
    test_app = _make_app()
    status, body = _get(test_app, "/version")
    assert status == 200
    for key in ("buildSha", "imageTag", "apiVersion", "schemaVersion"):
        assert key in body, f"missing key {key!r}"
    assert body["apiVersion"] == "v1"
    assert body["schemaVersion"] == "0001_initial"
