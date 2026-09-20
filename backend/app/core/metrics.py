"""Prometheus metric collectors (addendum §9.2).

Metric names and label sets are fixed by the addendum. None of them carry a `project_id`
label — that would be unbounded cardinality on a Prometheus target.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

__all__ = [
    "DATABASE_POOL_CONNECTIONS",
    "EXPORT_JOBS_TOTAL",
    "HTTP_REQUESTS_IN_PROGRESS",
    "HTTP_REQUESTS_TOTAL",
    "HTTP_REQUEST_DURATION_SECONDS",
    "REDIS_ERRORS_TOTAL",
    "SOLVER_ACTIVE_JOBS",
    "SOLVER_DIAGNOSTICS_TOTAL",
    "SOLVER_JOBS_TOTAL",
    "SOLVER_JOB_DURATION_SECONDS",
    "SOLVER_QUEUE_DEPTH",
    "SOLVER_UNROUTED_NETS",
]

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests handled by the API",
    ["method", "path", "status"],
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
)

HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "http_requests_in_progress",
    "HTTP requests currently being handled",
)

SOLVER_JOBS_TOTAL = Counter(
    "solver_jobs_total",
    "Total solver jobs processed",
    ["operation", "status"],
)

SOLVER_JOB_DURATION_SECONDS = Histogram(
    "solver_job_duration_seconds",
    "Solver job wall-clock duration in seconds",
    ["operation"],
)

SOLVER_QUEUE_DEPTH = Gauge(
    "solver_queue_depth",
    "Number of solver jobs currently queued",
)

SOLVER_ACTIVE_JOBS = Gauge(
    "solver_active_jobs",
    "Number of solver jobs currently running",
)

SOLVER_UNROUTED_NETS = Histogram(
    "solver_unrouted_nets",
    "Number of unrouted nets in a completed solver job",
)

SOLVER_DIAGNOSTICS_TOTAL = Counter(
    "solver_diagnostics_total",
    "Total diagnostics emitted by the solver/validator",
    ["severity", "code"],
)

EXPORT_JOBS_TOTAL = Counter(
    "export_jobs_total",
    "Total export jobs processed",
    ["format", "status"],
)

DATABASE_POOL_CONNECTIONS = Gauge(
    "database_pool_connections",
    "Current database connection pool size",
)

REDIS_ERRORS_TOTAL = Counter(
    "redis_errors_total",
    "Total Redis errors observed",
)
