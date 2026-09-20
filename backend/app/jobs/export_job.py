"""Export job — renders a layout in the requested format and uploads to S3.

The actual rendering lives in :mod:`app.services.export` (a stub for this
wave; the real renderer ships in wave 3). Storage upload is via
:mod:`app.services.storage`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from app.core.errors import AppError
from app.core.logging import bind_context, get_logger
from app.core.metrics import EXPORT_JOBS_TOTAL
from app.db.models import Project
from app.db.session import get_session
from app.domain.boards.registry import get_board_model
from app.domain.models import ProjectDocument
from app.repositories import exports as exports_repo
from app.repositories import layouts as layouts_repo
from app.services import export as export_service
from app.services import storage
from app.settings import get_settings

__all__ = ["run_export_job"]


async def run_export_job(ctx: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any] | None:
    """Render and upload one ``exports`` row."""
    settings = get_settings()
    export_id_raw = payload.get("exportId")
    project_id_raw = payload.get("projectId")
    layout_id_raw = payload.get("layoutId")
    fmt = payload.get("format")
    if not export_id_raw or not project_id_raw or not layout_id_raw or not fmt:
        raise AppError("VALIDATION_ERROR", "export payload missing required fields", status=422)

    export_id = UUID(str(export_id_raw))
    project_id = UUID(str(project_id_raw))
    layout_id = UUID(str(layout_id_raw))
    bind_context(
        project_id=str(project_id),
        operation=f"export:{fmt}",
    )

    async with get_session() as session:
        export_row = await exports_repo.get_export(session, export_id)
        if export_row is None:
            get_logger().warning("export row missing", export_id=str(export_id))
            return None
        if export_row.status == "succeeded":
            return None
        layout_row = await layouts_repo.get_layout(session, layout_id)
        if layout_row is None:
            await exports_repo.update_export(
                session=session,
                export_id=export_id,
                status="failed",
                error_message=f"layout {layout_id} not found",
            )
            EXPORT_JOBS_TOTAL.labels(fmt, "failed").inc()
            return None
        project_row = await session.get(Project, project_id)
        if project_row is None:
            await exports_repo.update_export(
                session=session,
                export_id=export_id,
                status="failed",
                error_message=f"project {project_id} not found",
            )
            EXPORT_JOBS_TOTAL.labels(fmt, "failed").inc()
            return None

        await exports_repo.update_export(session=session, export_id=export_id, status="running")

        document = ProjectDocument.model_validate(project_row.document)
        board = get_board_model(document.board.model_id)
        components = list(document.components)
        nets = list(document.nets)
        layout_dict = layout_row.layout
        project_name = project_row.name

    try:
        from app.domain.models import Layout, PerfboardModel, TraceLayout

        layout_obj: Layout | TraceLayout = (
            TraceLayout.model_validate(layout_dict)
            if isinstance(board, PerfboardModel)
            else Layout.model_validate(layout_dict)
        )

        body, content_type = await export_service.render_export(
            fmt, board, components, nets, layout_obj, project_name
        )
    except Exception as exc:
        get_logger().exception("export render failed", export_id=str(export_id), error=str(exc))
        async with get_session() as session:
            await exports_repo.update_export(
                session=session,
                export_id=export_id,
                status="failed",
                error_message=str(exc),
            )
        EXPORT_JOBS_TOTAL.labels(fmt, "failed").inc()
        return None

    ext = _ext_for(fmt)
    key = storage.build_export_key(str(project_id), str(export_id), ext)
    try:
        size, sha = await storage.put_object(key, body, content_type)
    except Exception as exc:
        get_logger().exception("export upload failed", export_id=str(export_id), error=str(exc))
        async with get_session() as session:
            await exports_repo.update_export(
                session=session,
                export_id=export_id,
                status="failed",
                error_message=f"upload failed: {exc}",
            )
        EXPORT_JOBS_TOTAL.labels(fmt, "failed").inc()
        return None

    retention_until = datetime.now(tz=UTC) + timedelta(days=settings.export_retention_days)
    async with get_session() as session:
        await exports_repo.update_export(
            session=session,
            export_id=export_id,
            status="succeeded",
            storage_key=key,
            content_type=content_type,
            size_bytes=size,
            checksum_sha256=sha,
            retention_until=retention_until,
        )
    EXPORT_JOBS_TOTAL.labels(fmt, "succeeded").inc()
    return {"exportId": str(export_id), "key": key}


def _ext_for(fmt: str) -> str:
    return {
        "svg": "svg",
        "png": "png",
        "pdf": "pdf",
        "json": "json",
        "bom-csv": "csv",
        "jumpers-csv": "csv",
        "instructions-md": "md",
        "gerber-top": "gtl",
        "gerber-bottom": "gbl",
        "gerber-outline": "gko",
        "drill": "drl",
        "placement-csv": "csv",
    }[fmt]
