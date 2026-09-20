"""Solver job endpoints.

* ``POST /api/v1/projects/{id}/jobs`` creates + enqueues a job (honours
  ``Idempotency-Key`` so a retry returns the same job row with 200 instead of
  creating a second one).
* ``GET /api/v1/jobs/{id}`` returns the current state of a job.
* ``GET /api/v1/jobs/{id}/events`` returns the append-only event log.
* ``GET /api/v1/jobs/{id}/result`` returns the produced layout / score / diagnostics.
* ``POST /api/v1/jobs/{id}/cancel`` sets the Redis cancel flag and tries to abort
  the arq-queued job.

The job row is inserted inside a session block so the commit lands before the
worker could possibly read it; the arq enqueue runs after the session exits.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from arq.jobs import Job
from sanic import Blueprint
from sanic.request import Request
from sanic.response import HTTPResponse, json

from app.core.errors import AppError
from app.core.logging import get_logger
from app.db.models import SolverJob, SolverJobEvent
from app.db.session import get_session
from app.domain.models import SolverOptions
from app.repositories import jobs as jobs_repo
from app.repositories import projects as projects_repo
from app.repositories import revisions as revisions_repo
from app.settings import get_settings

__all__ = ["bp"]


bp = Blueprint("jobs", url_prefix="/api/v1")


_VALID_OPERATIONS: frozenset[str] = frozenset(
    {"place", "route", "solve", "optimize", "validate", "export", "trace-route", "trace-solve"}
)


def _parse_uuid(raw: str) -> UUID:
    try:
        return UUID(raw)
    except (ValueError, TypeError) as exc:
        raise AppError("VALIDATION_ERROR", f"invalid uuid {raw!r}", status=422) from exc


def _isoformat(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _job_to_wire(job: SolverJob) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": str(job.id),
        "projectId": str(job.project_id),
        "operation": job.operation,
        "status": job.status,
        "progressPercent": job.progress_percent,
        "progressPhase": job.progress_phase,
        "createdAt": _isoformat(job.created_at),
        "startedAt": _isoformat(job.started_at),
        "finishedAt": _isoformat(job.finished_at),
    }
    if job.revision_id is not None:
        body["revisionId"] = str(job.revision_id)
    if job.result_layout_id is not None:
        body["resultLayoutId"] = str(job.result_layout_id)
    if job.error_code is not None:
        body["errorCode"] = job.error_code
    if job.error_message is not None:
        body["errorMessage"] = job.error_message
    return body


def _event_to_wire(event: SolverJobEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "at": _isoformat(event.at),
        "phase": event.phase,
        "percent": event.percent,
        "level": event.level,
        "code": event.code,
        "message": event.message,
    }


@bp.post("/projects/<project_id>/jobs")
async def create_job(request: Request, project_id: str) -> HTTPResponse:
    """Create + enqueue a solver job for a project."""
    pid = _parse_uuid(project_id)
    idempotency_key = request.headers.get("Idempotency-Key")

    body: dict[str, Any] = request.json or {}
    operation = body.get("operation")
    if operation not in _VALID_OPERATIONS:
        raise AppError(
            "VALIDATION_ERROR",
            f"operation must be one of {sorted(_VALID_OPERATIONS)}",
            status=422,
        )

    seed = body.get("seed")
    if seed is not None and not isinstance(seed, int):
        raise AppError("VALIDATION_ERROR", "seed must be an integer", status=422)

    raw_options = body.get("options") or {}
    if raw_options and not isinstance(raw_options, dict):
        raise AppError("VALIDATION_ERROR", "options must be an object", status=422)
    try:
        options_obj = SolverOptions.model_validate(raw_options) if raw_options else SolverOptions()
    except Exception as exc:
        raise AppError("VALIDATION_ERROR", str(exc), status=422) from exc
    options_payload = options_obj.model_dump(by_alias=True)

    revision_id_raw = body.get("revisionId")
    revision_id = _parse_uuid(revision_id_raw) if revision_id_raw is not None else None

    queued_job: SolverJob | None = None
    reused = False

    async with get_session() as session:
        project = await projects_repo.get_project(session, pid)
        if project is None:
            raise AppError("NOT_FOUND", f"project {project_id} not found", status=404)

        # Idempotency probe before insert.
        if idempotency_key is not None:
            existing = await jobs_repo.get_job_by_idempotency_key(session, pid, idempotency_key)
            if existing is not None:
                queued_job = existing
                reused = True

        if queued_job is None:
            # Resolve or freeze the revision the worker should read.
            if revision_id is None:
                revision = await revisions_repo.create_revision(
                    session=session, project_id=pid, document=project.document
                )
                revision_id = revision.id
            else:
                rev = await revisions_repo.get_revision(session, revision_id)
                if rev is None or rev.project_id != pid:
                    raise AppError(
                        "NOT_FOUND",
                        f"revision {revision_id} for project {project_id} not found",
                        status=404,
                    )

            queued_job = await jobs_repo.create_job(
                session=session,
                project_id=pid,
                revision_id=revision_id,
                operation=operation,
                seed=seed,
                options=options_payload,
                idempotency_key=idempotency_key,
                requested_by=None,
            )

    assert queued_job is not None
    job_id: UUID = queued_job.id

    # Enqueue AFTER the session commits so the worker can never read a
    # not-yet-existing job row.
    if not reused:
        arq_pool = request.app.ctx.arq
        job_key = f"solve:{pid}:{revision_id}:{operation}:{idempotency_key if idempotency_key else job_id}"
        payload = {
            "jobId": str(job_id),
            "projectId": str(pid),
            "revisionId": str(revision_id) if revision_id is not None else None,
            "operation": operation,
            "seed": seed,
            "options": options_payload,
            "idempotencyKey": idempotency_key,
            "traceparent": request.headers.get("traceparent"),
        }
        try:
            await arq_pool.enqueue_job("run_solver_job", payload, _job_id=job_key)
        except Exception as exc:
            get_logger().warning("arq enqueue failed", job_id=str(job_id), error=str(exc))
        # Persist the queue id alongside the job so the cancel endpoint can target it.
        async with get_session() as session:
            await jobs_repo.update_job_status(
                session=session, job_id=job_id, status="queued", queue_job_id=job_key
            )

    async with get_session() as session:
        refreshed = await jobs_repo.get_job(session, job_id)
    if refreshed is None:  # pragma: no cover — race after create
        raise AppError("NOT_FOUND", f"job {job_id} not found", status=404)

    return json(_job_to_wire(refreshed), status=200 if reused else 202)


@bp.get("/jobs/<job_id>")
async def get_job(_: Request, job_id: str) -> HTTPResponse:
    jid = _parse_uuid(job_id)
    async with get_session() as session:
        job = await jobs_repo.get_job(session, jid)
    if job is None:
        raise AppError("NOT_FOUND", f"job {job_id} not found", status=404)
    return json(_job_to_wire(job), status=200)


@bp.get("/jobs/<job_id>/events")
async def list_events(request: Request, job_id: str) -> HTTPResponse:
    jid = _parse_uuid(job_id)
    raw_after = request.args.get("after")
    after_id: int | None
    if raw_after is None or raw_after == "":
        after_id = None
    else:
        try:
            after_id = int(raw_after)
        except ValueError as exc:
            raise AppError("VALIDATION_ERROR", "after must be an integer", status=422) from exc

    async with get_session() as session:
        events = await jobs_repo.list_job_events(session, jid, after_id)
    return json([_event_to_wire(e) for e in events], status=200)


@bp.get("/jobs/<job_id>/result")
async def get_job_result(_: Request, job_id: str) -> HTTPResponse:
    jid = _parse_uuid(job_id)
    async with get_session() as session:
        job = await jobs_repo.get_job(session, jid)
        if job is None:
            raise AppError("NOT_FOUND", f"job {job_id} not found", status=404)
        if job.status != "succeeded":
            raise AppError(
                "JOB_NOT_READY",
                f"job {job_id} status is {job.status}, not succeeded",
                status=409,
            )
        layout_id = job.result_layout_id
        if layout_id is None:
            raise AppError("JOB_NOT_READY", "job succeeded but produced no layout", status=409)

        from app.repositories.layouts import get_layout

        layout = await get_layout(session, layout_id)
        if layout is None:  # pragma: no cover — race
            raise AppError("NOT_FOUND", f"layout {layout_id} not found", status=404)

    body: dict[str, Any] = {
        "layout": layout.layout,
        "score": layout.score,
        "diagnostics": layout.diagnostics or [],
    }
    if job.trace is not None:
        body["trace"] = job.trace
    return json(body, status=200)


@bp.post("/jobs/<job_id>/cancel")
async def cancel_job(request: Request, job_id: str) -> HTTPResponse:
    jid = _parse_uuid(job_id)
    settings = get_settings()
    redis_client = request.app.ctx.redis
    cancel_key = f"abb:cancel:{jid}"
    ttl = settings.solver_max_timeout_seconds + 60
    await redis_client.set(cancel_key, "1", ex=ttl)

    # Best-effort abort of a still-queued arq job — never let it raise.
    queue_job_id: str | None = None
    async with get_session() as session:
        job = await jobs_repo.get_job(session, jid)
        if job is None:
            raise AppError("NOT_FOUND", f"job {job_id} not found", status=404)
        queue_job_id = job.queue_job_id

    if queue_job_id:
        try:
            await Job(queue_job_id, redis_client).abort()
        except Exception as exc:
            get_logger().debug("arq abort noop", job_id=job_id, error=str(exc))

    async with get_session() as session:
        refreshed = await jobs_repo.get_job(session, jid)
    if refreshed is None:  # pragma: no cover
        raise AppError("NOT_FOUND", f"job {job_id} not found", status=404)
    return json(_job_to_wire(refreshed), status=202)
