"""Export endpoints: create, poll, download.

Creates an ``exports`` row, enqueues an ``run_export_job`` arq job, and exposes
the S3-backed download once the worker reports success.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sanic import Blueprint
from sanic.request import Request
from sanic.response import HTTPResponse, json, raw

from app.core.errors import AppError
from app.core.logging import get_logger
from app.db.session import get_session
from app.repositories import exports as exports_repo
from app.repositories import layouts as layouts_repo
from app.services import storage

__all__ = ["bp"]


bp = Blueprint("exports", url_prefix="/api/v1")


_FORMAT_TO_CONTENT_TYPE: dict[str, str] = {
    "svg": "image/svg+xml",
    "png": "image/png",
    "pdf": "application/pdf",
    "json": "application/json",
    "bom-csv": "text/csv",
    "jumpers-csv": "text/csv",
    "instructions-md": "text/markdown",
}


def _parse_uuid(raw: str) -> UUID:
    try:
        return UUID(raw)
    except (ValueError, TypeError) as exc:
        raise AppError("VALIDATION_ERROR", f"invalid uuid {raw!r}", status=422) from exc


def _export_to_wire(row: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": str(row.id),
        "format": row.format,
        "status": row.status,
        "contentType": row.content_type,
        "sizeBytes": row.size_bytes,
        "createdAt": row.created_at.isoformat(),
    }
    if row.storage_key is not None:
        body["storageKey"] = row.storage_key
    if row.completed_at is not None:
        body["completedAt"] = row.completed_at.isoformat()
    return body


@bp.post("/layouts/<layout_id>/exports")
async def create_export(request: Request, layout_id: str) -> HTTPResponse:
    """Create + enqueue an export job for a layout."""
    lid = _parse_uuid(layout_id)
    body: dict[str, Any] = request.json or {}
    fmt = body.get("format")
    if not isinstance(fmt, str) or fmt not in _FORMAT_TO_CONTENT_TYPE:
        raise AppError(
            "VALIDATION_ERROR",
            f"format must be one of {sorted(_FORMAT_TO_CONTENT_TYPE)}",
            status=422,
        )
    content_type = _FORMAT_TO_CONTENT_TYPE[fmt]

    async with get_session() as session:
        layout = await layouts_repo.get_layout(session, lid)
        if layout is None:
            raise AppError("NOT_FOUND", f"layout {layout_id} not found", status=404)
        export_row = await exports_repo.create_export(
            session=session,
            project_id=layout.project_id,
            revision_id=layout.revision_id,
            layout_id=lid,
            format=fmt,
            content_type=content_type,
        )

    arq_pool = request.app.ctx.arq
    payload = {
        "exportId": str(export_row.id),
        "projectId": str(layout.project_id),
        "layoutId": str(lid),
        "format": fmt,
    }
    job_key = f"export:{export_row.id}"
    try:
        await arq_pool.enqueue_job("run_export_job", payload, _job_id=job_key)
    except Exception as exc:
        get_logger().warning("arq enqueue failed (export)", export_id=str(export_row.id), error=str(exc))

    return json(_export_to_wire(export_row), status=202)


@bp.get("/exports/<export_id>")
async def get_export(_: Request, export_id: str) -> HTTPResponse:
    eid = _parse_uuid(export_id)
    async with get_session() as session:
        row = await exports_repo.get_export(session, eid)
    if row is None:
        raise AppError("NOT_FOUND", f"export {export_id} not found", status=404)
    return json(_export_to_wire(row), status=200)


@bp.get("/exports/<export_id>/download")
async def download_export(request: Request, export_id: str) -> HTTPResponse:
    """Stream the rendered artefact from S3 / MinIO."""
    eid = _parse_uuid(export_id)
    async with get_session() as session:
        row = await exports_repo.get_export(session, eid)
    if row is None:
        raise AppError("NOT_FOUND", f"export {export_id} not found", status=404)
    if row.status != "succeeded" or row.storage_key is None:
        raise AppError(
            "EXPORT_NOT_READY",
            f"export {export_id} status is {row.status}, not succeeded",
            status=404,
        )

    body_bytes, content_type = await storage.get_object_bytes(row.storage_key, fallback_ct=row.content_type)
    filename = f"{export_id}.{_ext_for(row.format)}"
    headers = {
        "Content-Type": content_type,
        "Content-Length": str(len(body_bytes)),
        "Content-Disposition": f'attachment; filename="{filename}"',
    }
    return raw(body_bytes, headers=headers)


def _ext_for(fmt: str) -> str:
    return {
        "svg": "svg",
        "png": "png",
        "pdf": "pdf",
        "json": "json",
        "bom-csv": "csv",
        "jumpers-csv": "csv",
        "instructions-md": "md",
    }[fmt]
