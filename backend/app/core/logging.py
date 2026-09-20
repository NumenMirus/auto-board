"""Structured JSON logging to stdout (addendum §9.1).

Bound context fields: `request_id`, `trace_id`, `project_id`, `job_id`, `revision_id`,
`operation`. A processor strips any accidental secret-shaped key before the event is
serialized, so a stray `**locals()`-style log call can never leak credentials.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any, cast

import structlog
from structlog.typing import FilteringBoundLogger

__all__ = ["bind_context", "clear_context", "configure_logging", "get_logger"]

_CONTEXT_FIELDS = (
    "request_id",
    "trace_id",
    "project_id",
    "job_id",
    "revision_id",
    "operation",
)

_FORBIDDEN_KEYS = frozenset(
    {
        "database_url",
        "redis_url",
        "s3_secret_access_key",
        "s3_access_key_id",
        "authorization",
    }
)


def _strip_secrets(
    _logger: object, _method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    for key in list(event_dict):
        if key.lower() in _FORBIDDEN_KEYS:
            del event_dict[key]
    return event_dict


def configure_logging(
    *,
    log_level: str = "INFO",
    service: str = "autobreadboard-api",
    environment: str = "development",
) -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper(), logging.INFO),
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", key="timestamp"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            _strip_secrets,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper(), logging.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    structlog.contextvars.bind_contextvars(service=service, environment=environment)


def bind_context(**fields: Any) -> None:
    """Bind any subset of the known context fields (unknown keys are ignored)."""

    known = {k: v for k, v in fields.items() if k in _CONTEXT_FIELDS and v is not None}
    if known:
        structlog.contextvars.bind_contextvars(**known)


def clear_context() -> None:
    structlog.contextvars.clear_contextvars()


def get_logger(name: str | None = None) -> FilteringBoundLogger:
    return cast(FilteringBoundLogger, structlog.get_logger(name))
