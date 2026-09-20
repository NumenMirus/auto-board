"""Kubernetes-style exec probe for the worker.

The worker exposes no HTTP API; this module provides two CLI subcommands the
pod's ``readinessProbe`` / ``livenessProbe`` can call:

* ``--ready``: PING Redis + check ``abb:worker:health`` exists, exit 0/1.
* ``--live``: stat the heartbeat file and exit 0 when mtime is < 60 s.

Both modes exit ``0`` on success and ``1`` on any failure so a probe failure
is unambiguous.
"""

from __future__ import annotations

import argparse
import contextlib
import sys
import time
from collections.abc import Sequence
from pathlib import Path

import redis

from app.settings import get_settings

__all__: list[str] = []


def _ready() -> int:
    settings = get_settings()
    client = redis.Redis.from_url(str(settings.redis_url))
    try:
        try:
            if not client.ping():
                return 1
        except Exception:
            return 1
        try:
            return 0 if client.exists("abb:worker:health") else 1
        except Exception:
            return 1
    finally:
        with contextlib.suppress(Exception):
            client.close()


def _live() -> int:
    settings = get_settings()
    path = Path(settings.worker_heartbeat_path)
    if not path.exists():
        return 1
    age = time.time() - path.stat().st_mtime
    if age > 60:
        return 1
    return 0


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Worker probe (Kubernetes exec probes)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--ready", action="store_true", help="Readiness probe")
    group.add_argument("--live", action="store_true", help="Liveness probe")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    if args.ready:
        return _ready()
    if args.live:
        return _live()
    return 1


if __name__ == "__main__":
    sys.exit(main())
