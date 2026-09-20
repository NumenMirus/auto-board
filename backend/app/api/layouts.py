"""Layout read endpoint.

Layouts are append-only: the only writer is the worker (via ``create_layout``).
Exports reference a layout by id; this endpoint is the canonical way to fetch
either one for re-rendering or display.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sanic import Blueprint
from sanic.request import Request
from sanic.response import HTTPResponse, json

from app.core.errors import AppError
from app.db.session import get_session
from app.repositories.layouts import get_layout

__all__ = ["bp"]


bp = Blueprint("layouts", url_prefix="/api/v1")


def _parse_uuid(raw: str) -> UUID:
    try:
        return UUID(raw)
    except (ValueError, TypeError) as exc:
        raise AppError("VALIDATION_ERROR", f"invalid uuid {raw!r}", status=422) from exc


@bp.get("/layouts/<layout_id>")
async def fetch_layout(_: Request, layout_id: str) -> HTTPResponse:
    lid = _parse_uuid(layout_id)
    async with get_session() as session:
        layout = await get_layout(session, lid)
    if layout is None:
        raise AppError("NOT_FOUND", f"layout {layout_id} not found", status=404)

    body: dict[str, Any] = {
        "id": str(layout.id),
        "layout": layout.layout,
        "score": layout.score,
        "diagnostics": layout.diagnostics or [],
    }
    return json(body, status=200)
