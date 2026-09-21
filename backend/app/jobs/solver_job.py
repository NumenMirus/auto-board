"""Solver job — runs the pure ``solve``/``place``/``route``/``optimize``/
``validate`` pipeline for one ``solver_jobs`` row.

Cancellation is driven by the Redis key ``abb:cancel:{job_id}`` (set by the
cancel endpoint); a tiny poller task flips a :class:`threading.Event` so the
CPU-bound solver running in ``asyncio.to_thread`` sees the signal between
local-search / Steiner / rip-up iterations.

Progress is published via the Redis hash ``abb:progress:{job_id}`` (TTL 1h)
and also persisted as ``solver_job_events`` rows. The bridge is a producer /
consumer pair so the sync callback from the solver can drop messages into a
queue and the async writer drains it without crossing loop boundaries.
"""

from __future__ import annotations

import asyncio
import contextlib
import queue
import threading
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from arq.worker import Retry

from app.core.errors import AppError
from app.core.logging import bind_context, get_logger
from app.core.metrics import SOLVER_DIAGNOSTICS_TOTAL, SOLVER_JOBS_TOTAL
from app.db.models import Project, ProjectRevision
from app.db.session import get_session
from app.domain import place as domain_place
from app.domain import route as domain_route
from app.domain import solve as domain_solve
from app.domain import validate as domain_validate
from app.domain.boards.registry import get_board_model
from app.domain.errors import DomainError, SolverCancelled, SolverTimeout
from app.domain.footprints.registry import FOOTPRINTS
from app.domain.index import BoardIndex
from app.domain.models import (
    BreadboardModel,
    Component,
    Layout,
    Net,
    PerfboardModel,
    ProjectDocument,
    SolverOptions,
    TraceLayout,
)
from app.domain.perfboards.registry import PERFBOARD_FOOTPRINTS
from app.domain.traces.solve import place_only as trace_place_only
from app.domain.traces.solve import route_only as trace_route_only
from app.domain.traces.solve import solve as trace_solve
from app.repositories import jobs as jobs_repo
from app.repositories import layouts as layouts_repo
from app.settings import get_settings

__all__ = ["run_solver_job"]


# --------------------------------------------------------------------------
# Bridge: solver thread -> event-loop DB writes
# --------------------------------------------------------------------------


class _ProgressBridge:
    """Sync → async bridge for solver progress callbacks.

    The solver runs in a worker thread; the database / Redis writes must happen
    on the event loop. This bridge keeps a queue of
    ``(phase, percent, level, code, message)`` tuples drained by an async task
    that writes each one out.
    """

    def __init__(self, job_id: UUID, redis_client: Any) -> None:
        self.queue: queue.Queue[tuple[str | None, int | None, str, str | None, str] | None] = queue.Queue()
        self.job_id = job_id
        self.redis_client = redis_client

    def push(
        self,
        phase: str | None,
        percent: int | None,
        level: str,
        code: str | None,
        message: str,
    ) -> None:
        self.queue.put((phase, percent, level, code, message))

    def close(self) -> None:
        """Enqueue the drain sentinel. Non-blocking — callers await the drain
        task itself (via ``asyncio.wait_for``) to know when draining finished.
        A blocking wait here would deadlock: it would stall the single event
        loop thread that ``_drain_progress`` also needs in order to resume and
        process that same sentinel.
        """
        self.queue.put(None)


async def _drain_progress(bridge: _ProgressBridge) -> None:
    loop = asyncio.get_running_loop()
    while True:
        item = await loop.run_in_executor(None, bridge.queue.get)
        if item is None:
            return
        phase, percent, level, code, message = item
        try:
            async with get_session() as session:
                await jobs_repo.append_job_event(
                    session=session,
                    job_id=bridge.job_id,
                    phase=phase,
                    percent=percent,
                    level=level,
                    code=code,
                    message=message,
                )
                if percent is not None:
                    await jobs_repo.update_job_status(
                        session=session,
                        job_id=bridge.job_id,
                        status="running",
                        progress_percent=percent,
                        progress_phase=phase,
                    )
        except Exception as exc:
            get_logger().warning("progress drain failed", job_id=str(bridge.job_id), error=str(exc))
        try:
            mapping = {
                "phase": phase or "",
                "percent": str(percent if percent is not None else 0),
                "level": level,
                "code": code or "",
                "message": message,
                "updated_at": str(time.time()),
            }
            await bridge.redis_client.hset(f"abb:progress:{bridge.job_id}", mapping=mapping)
            await bridge.redis_client.expire(f"abb:progress:{bridge.job_id}", 3600)
        except Exception:
            pass


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


async def run_solver_job(ctx: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any] | None:
    """Execute one ``solver_jobs`` row.

    Idempotent: re-running on an already-terminal job is a no-op. The
    Redis-backed lock ``abb:lock:{project_id}:{revision_id}:{operation}``
    serialises concurrent jobs on the same target; collisions defer the loser
    by 5 seconds via :class:`arq.worker.Retry`.
    """
    settings = get_settings()
    job_id_raw = payload.get("jobId")
    if job_id_raw is None:
        raise AppError("VALIDATION_ERROR", "jobId missing from payload", status=422)
    job_id = UUID(str(job_id_raw))
    bind_context(job_id=str(job_id), operation=payload.get("operation"))

    redis_client = ctx["redis"]

    # 1. Re-read the row; bail early when terminal.
    async with get_session() as session:
        job = await jobs_repo.get_job(session, job_id)
        if job is None:
            get_logger().warning("solver job row missing", job_id=str(job_id))
            return None
        if job.status in {"succeeded", "failed", "cancelled"}:
            return None

    # 2. Acquire the per-(project,revision,operation) lock.
    lock_key = f"abb:lock:{job.project_id}:{job.revision_id}:{job.operation}"
    acquired = await redis_client.set(lock_key, str(job_id), nx=True, px=settings.job_lock_ttl_seconds * 1000)
    if not acquired:
        raise Retry(defer=5)

    # 3. Cancel poller: flips the threading.Event when the redis flag appears.
    cancel_event = threading.Event()
    cancel_key = f"abb:cancel:{job_id}"

    async def _poll_cancel() -> None:
        try:
            while True:
                if await redis_client.exists(cancel_key):
                    cancel_event.set()
                    return
                await asyncio.sleep(0.25)
        except asyncio.CancelledError:
            return
        except Exception:
            return

    poller = asyncio.create_task(_poll_cancel())

    # 4. Progress bridge.
    bridge = _ProgressBridge(job_id, redis_client)
    drain_task = asyncio.create_task(_drain_progress(bridge))

    async def _finish_progress() -> None:
        """Close the bridge and await full drain completion.

        MUST be called before any terminal ``update_job_status`` write (the
        drain loop itself writes ``status="running"`` for every buffered
        progress item; calling it after the terminal write would let a
        late-drained item silently flip a "succeeded" job back to "running").
        Safe to call more than once — a second sentinel on an already-drained
        queue is a harmless no-op and awaiting an already-finished task
        returns immediately.
        """
        bridge.close()
        with contextlib.suppress(TimeoutError, Exception):
            await asyncio.wait_for(drain_task, timeout=5.0)

    # 5. Mark running + emit the initial event.
    async with get_session() as session:
        await jobs_repo.update_job_status(session=session, job_id=job_id, status="running")
        await jobs_repo.append_job_event(
            session=session,
            job_id=job_id,
            phase="queued",
            percent=0,
            level="info",
            code=None,
            message="job started",
        )

    timings: dict[str, float] = {}
    trace_payload: dict[str, Any] | None = None
    # Layout JSON — may be a breadboard Layout dump or a perfboard TraceLayout
    # dump depending on the board kind. Stored as a dict so both pipelines can
    # populate it uniformly; downstream persistence just persists the dict.
    result_layout: dict[str, Any] | None = None
    result_diagnostics: list[dict[str, Any]] = []
    result_score: dict[str, Any] | None = None
    try:
        board, index, components, nets, layout, options = await _resolve_inputs(job)
        op = job.operation

        def _cancel() -> bool:
            return cancel_event.is_set()

        def _progress(phase: str, percent: int) -> None:
            bridge.push(phase, percent, "info", None, f"{phase} {percent}%")

        if op == "export":
            raise DomainError("export is handled by run_export_job, not run_solver_job")

        # Perfboard path: dispatch to the trace pipeline when the board is a
        # PerfboardModel. Every other operation below assumes a breadboard.
        if isinstance(board, PerfboardModel):
            if op not in ("trace-place", "trace-route", "trace-solve"):
                raise DomainError(f"operation {op!r} is not valid for perfboard {board.id!r}")
            perf_result = await _run_perfboard_pipeline(
                op=op,
                board=board,
                components=components,
                nets=nets,
                layout=layout,
                options=options,
                cancel=lambda: cancel_event.is_set(),
                progress=lambda phase, percent: bridge.push(
                    phase, percent, "info", None, f"{phase} {percent}%"
                ),
                timings=timings,
            )
            result_layout = perf_result.layout
            result_score = perf_result.score
            result_diagnostics = perf_result.diagnostics
            trace_payload = perf_result.trace
        else:
            assert index is not None  # every non-perfboard board carries a BoardIndex
            if op == "validate":
                t0 = time.perf_counter()
                diagnostics, score = await asyncio.to_thread(
                    domain_validate.validate_layout,
                    board,
                    index,
                    dict(FOOTPRINTS),
                    components,
                    nets,
                    layout,
                    options,
                )
                timings["validate"] = (time.perf_counter() - t0) * 1000.0
                for d in diagnostics:
                    SOLVER_DIAGNOSTICS_TOTAL.labels(d.severity, d.code).inc()
                result_diagnostics = [d.model_dump(by_alias=True) for d in diagnostics]
                result_score = score.model_dump(by_alias=True)
                trace_payload = {"mode": "validate"}

            elif op == "place":
                t0 = time.perf_counter()
                placement = await asyncio.to_thread(
                    domain_place.place,
                    board,
                    index,
                    dict(FOOTPRINTS),
                    components,
                    nets,
                    options,
                    layout,
                )
                timings["place"] = (time.perf_counter() - t0) * 1000.0
                placed_layout = Layout(
                    version=1,
                    board_id=board.id,
                    placements=list(placement.placements),
                    jumpers=[],
                    manual_electrical_links=[],
                )
                t1 = time.perf_counter()
                diagnostics, score = await asyncio.to_thread(
                    domain_validate.validate_layout,
                    board,
                    index,
                    dict(FOOTPRINTS),
                    components,
                    nets,
                    placed_layout,
                    options,
                )
                timings["verify"] = (time.perf_counter() - t1) * 1000.0
                for d in diagnostics:
                    SOLVER_DIAGNOSTICS_TOTAL.labels(d.severity, d.code).inc()
                result_layout = placed_layout.model_dump(by_alias=True)
                result_diagnostics = [d.model_dump(by_alias=True) for d in diagnostics]
                result_score = score.model_dump(by_alias=True)
                trace_payload = placement.trace.model_dump(by_alias=True)

            elif op == "route":
                t0 = time.perf_counter()
                routing = await asyncio.to_thread(
                    domain_route.route,
                    board,
                    index,
                    dict(FOOTPRINTS),
                    components,
                    nets,
                    layout,
                    options,
                )
                timings["route"] = (time.perf_counter() - t0) * 1000.0
                routed_layout = Layout(
                    version=1,
                    board_id=board.id,
                    placements=list(layout.placements),
                    jumpers=list(routing.jumpers),
                    manual_electrical_links=list(layout.manual_electrical_links),
                )
                t1 = time.perf_counter()
                diagnostics, score = await asyncio.to_thread(
                    domain_validate.validate_layout,
                    board,
                    index,
                    dict(FOOTPRINTS),
                    components,
                    nets,
                    routed_layout,
                    options,
                )
                timings["verify"] = (time.perf_counter() - t1) * 1000.0
                for d in diagnostics:
                    SOLVER_DIAGNOSTICS_TOTAL.labels(d.severity, d.code).inc()
                result_layout = routed_layout.model_dump(by_alias=True)
                result_diagnostics = [d.model_dump(by_alias=True) for d in diagnostics]
                result_score = score.model_dump(by_alias=True)
                trace_payload = routing.trace.model_dump(by_alias=True)

            elif op == "solve":
                t0 = time.perf_counter()
                solved = await asyncio.to_thread(
                    domain_solve.solve,
                    board,
                    index,
                    dict(FOOTPRINTS),
                    components,
                    nets,
                    options,
                    layout,
                    _cancel,
                    _progress,
                )
                timings["solve"] = (time.perf_counter() - t0) * 1000.0
                for d in solved.diagnostics:
                    SOLVER_DIAGNOSTICS_TOTAL.labels(d.severity, d.code).inc()
                result_layout = solved.layout.model_dump(by_alias=True)
                result_diagnostics = [d.model_dump(by_alias=True) for d in solved.diagnostics]
                result_score = solved.score.model_dump(by_alias=True)
                trace_payload = solved.trace.model_dump(by_alias=True) if solved.trace else None

            elif op == "optimize":
                t0 = time.perf_counter()
                optimized = await asyncio.to_thread(
                    domain_solve.optimize,
                    board,
                    index,
                    dict(FOOTPRINTS),
                    components,
                    nets,
                    layout,
                    options,
                    _cancel,
                    _progress,
                )
                timings["optimize"] = (time.perf_counter() - t0) * 1000.0
                for d in optimized.diagnostics:
                    SOLVER_DIAGNOSTICS_TOTAL.labels(d.severity, d.code).inc()
                result_layout = optimized.layout.model_dump(by_alias=True)
                result_diagnostics = [d.model_dump(by_alias=True) for d in optimized.diagnostics]
                result_score = optimized.score.model_dump(by_alias=True)
                trace_payload = optimized.trace.model_dump(by_alias=True) if optimized.trace else None
            else:
                raise DomainError(f"unknown operation {op!r}")

        new_layout_id: UUID | None = None
        if result_layout is not None:
            async with get_session() as session:
                layout_row = await layouts_repo.create_layout(
                    session=session,
                    project_id=job.project_id,
                    revision_id=job.revision_id,
                    source="solver",
                    solver_job_id=job_id,
                    layout=result_layout,
                    score=result_score,
                    diagnostics=result_diagnostics,
                )
                new_layout_id = layout_row.id

        # Drain any buffered progress writes BEFORE the terminal write below —
        # otherwise a late "running" write from the drain loop can race after
        # and silently overwrite "succeeded".
        await _finish_progress()
        async with get_session() as session:
            await jobs_repo.update_job_status(
                session=session,
                job_id=job_id,
                status="succeeded",
                result_layout_id=new_layout_id,
                trace=trace_payload,
                timings=timings,
            )
        SOLVER_JOBS_TOTAL.labels(op, "succeeded").inc()
        return {"layoutId": str(new_layout_id) if new_layout_id else None}

    except SolverCancelled:
        await _finish_progress()
        async with get_session() as session:
            await jobs_repo.update_job_status(
                session=session,
                job_id=job_id,
                status="cancelled",
                error_code="CANCELLED",
                error_message="cancelled by user",
                timings=timings,
            )
        SOLVER_JOBS_TOTAL.labels(job.operation, "cancelled").inc()
        return None
    except SolverTimeout as exc:
        await _finish_progress()
        async with get_session() as session:
            await jobs_repo.update_job_status(
                session=session,
                job_id=job_id,
                status="failed",
                error_code="SOLVER_TIMEOUT",
                error_message=str(exc),
                timings=timings,
            )
        SOLVER_JOBS_TOTAL.labels(job.operation, "failed").inc()
        return None
    except DomainError as exc:
        await _finish_progress()
        async with get_session() as session:
            await jobs_repo.update_job_status(
                session=session,
                job_id=job_id,
                status="failed",
                error_code=type(exc).__name__.upper(),
                error_message=str(exc),
                traceback=traceback.format_exc(),
                timings=timings,
            )
        SOLVER_JOBS_TOTAL.labels(job.operation, "failed").inc()
        return None
    except Exception as exc:
        await _finish_progress()
        async with get_session() as session:
            await jobs_repo.update_job_status(
                session=session,
                job_id=job_id,
                status="running",
                error_code="TRANSIENT",
                error_message=str(exc),
                traceback=traceback.format_exc(),
                timings=timings,
            )
        SOLVER_JOBS_TOTAL.labels(job.operation, "failed").inc()
        raise Retry(defer=2 ** min(int(job.attempt), 3)) from exc
    finally:
        cancel_event.set()
        poller.cancel()
        # Idempotent: if a branch above already drained (the normal case),
        # this is a no-op — an extra sentinel on a closed queue is harmless
        # and awaiting an already-finished task returns immediately. This
        # remains as a safety net for any exit path that doesn't go through
        # `_finish_progress()` above.
        await _finish_progress()
        # CAS-release the lock: only delete when this job still owns it.
        with contextlib.suppress(Exception):
            lua = (
                "if redis.call('get', KEYS[1]) == ARGV[1] then "
                "return redis.call('del', KEYS[1]) else return 0 end"
            )
            await redis_client.eval(lua, 1, lock_key, str(job_id))


# --------------------------------------------------------------------------
# Input resolution
# --------------------------------------------------------------------------


async def _resolve_inputs(
    job: Any,
) -> tuple[
    BreadboardModel | PerfboardModel,
    BoardIndex | None,
    list[Component],
    list[Net],
    Layout,
    SolverOptions,
]:
    """Load the (board, index, components, nets, layout, options) tuple for ``job``.

    ``index`` is ``None`` when ``board`` is a :class:`PerfboardModel` — the
    breadboard-specific :class:`BoardIndex` (electrical groups, rail lattice,
    center-gap row split) has no perfboard equivalent; perfboard routing
    builds its own :class:`~app.domain.traces.maze.MazeGraph` instead.
    """
    async with get_session() as session:
        project = await session.get(Project, job.project_id)
        if project is None:
            raise AppError("NOT_FOUND", f"project {job.project_id} not found", status=404)
        document_dict: dict[str, Any] = project.document
        if job.revision_id is not None:
            rev = await session.get(ProjectRevision, job.revision_id)
            if rev is not None:
                document_dict = rev.document

    document = ProjectDocument.model_validate(document_dict)
    board = get_board_model(document.board.model_id)
    index = BoardIndex.build(board) if isinstance(board, BreadboardModel) else None
    options = SolverOptions.model_validate(job.options)
    return (
        board,
        index,
        list(document.components),
        list(document.nets),
        document.layout,
        options,
    )


@dataclass(slots=True)
class _PerfboardPipelineResult:
    layout: dict[str, Any]
    score: dict[str, Any]
    diagnostics: list[dict[str, Any]]
    trace: dict[str, Any] | None


async def _run_perfboard_pipeline(
    *,
    op: str,
    board: PerfboardModel,
    components: list[Component],
    nets: list[Net],
    layout: Layout,
    options: SolverOptions,
    cancel: Callable[[], bool],
    progress: Callable[[str, int], None],
    timings: dict[str, float],
) -> _PerfboardPipelineResult:
    """Run the perfboard trace pipeline and return its results.

    ``trace-solve`` places every unlocked component then routes the result
    (`app.domain.traces.solve.solve`); ``trace-place`` places every unlocked component
    without routing (`app.domain.traces.solve.place_only`); ``trace-route`` routes the
    placements already present in ``layout`` verbatim, without placing anything
    (`app.domain.traces.solve.route_only`).
    """
    initial_layout = TraceLayout(board_id=board.id, placements=list(layout.placements))
    if op == "trace-solve":
        pipeline = trace_solve
    elif op == "trace-place":
        pipeline = trace_place_only
    else:
        pipeline = trace_route_only
    t0 = time.perf_counter()
    solved = await asyncio.to_thread(
        pipeline,
        board=board,
        footprints=dict(PERFBOARD_FOOTPRINTS),
        components=components,
        nets=nets,
        options=options,
        initial_layout=initial_layout,
        cancel=cancel,
        progress=progress,
    )
    timings[op] = (time.perf_counter() - t0) * 1000.0
    for d in solved.diagnostics:
        SOLVER_DIAGNOSTICS_TOTAL.labels(d.severity, d.code).inc()
    return _PerfboardPipelineResult(
        layout=solved.layout.model_dump(by_alias=True),
        score=solved.score.model_dump(by_alias=True),
        diagnostics=[d.model_dump(by_alias=True) for d in solved.diagnostics],
        trace=solved.trace.model_dump(by_alias=True) if solved.trace is not None else None,
    )
