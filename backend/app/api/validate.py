"""POST /api/v1/validate — pure, in-process layout validation.

No DB writes. The validator runs in a thread so the request handler never blocks
the event loop on CPU-bound DSU / connectivity work.
"""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import ValidationError
from sanic import Blueprint
from sanic.request import Request
from sanic.response import HTTPResponse, json

from app.core.errors import AppError
from app.domain.boards.registry import get_board_model
from app.domain.errors import InvalidInput
from app.domain.footprints.registry import FOOTPRINTS
from app.domain.index import BoardIndex
from app.domain.models import (
    BreadboardFootprint,
    BreadboardModel,
    Component,
    Layout,
    Net,
    SolverOptions,
    ValidateRequest,
)
from app.domain.validate import validate_layout

__all__ = ["bp"]


bp = Blueprint("validate", url_prefix="/api/v1")


@bp.post("/validate")
async def validate_layout_endpoint(request: Request) -> HTTPResponse:
    """Validate a layout against the netlist + board model."""
    try:
        payload_dict: Any = request.json or {}
    except Exception as exc:
        raise AppError("INVALID_JSON", "request body must be valid JSON", status=400) from exc

    try:
        payload = ValidateRequest.model_validate(payload_dict)
    except ValidationError as exc:
        raise AppError("VALIDATION_ERROR", str(exc), status=422) from exc

    try:
        board: BreadboardModel = get_board_model(payload.board.id)
    except InvalidInput as exc:
        raise AppError("UNKNOWN_BOARD_MODEL", str(exc), status=404) from exc

    index = BoardIndex.build(board)
    footprints_dict: dict[str, BreadboardFootprint] = dict(FOOTPRINTS)
    components: list[Component] = list(payload.netlist.components)
    nets: list[Net] = list(payload.netlist.nets)
    layout: Layout = payload.layout
    options: SolverOptions = payload.options

    diagnostics, score = await asyncio.to_thread(
        validate_layout,
        board,
        index,
        footprints_dict,
        components,
        nets,
        layout,
        options,
    )
    return json(
        {
            "diagnostics": [d.model_dump(by_alias=True) for d in diagnostics],
            "score": score.model_dump(by_alias=True),
        },
        status=200,
    )
