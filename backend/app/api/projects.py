"""Project CRUD + revision endpoints.

The mutable document is stored as a JSONB ``ProjectDocument`` (camelCase via
``model_dump(by_alias=True)``). The route handlers translate ``Project`` ORM
rows into the same wire shape the editor consumes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sanic import Blueprint
from sanic.request import Request
from sanic.response import HTTPResponse, json

from app.core.errors import AppError
from app.db.models import Project, ProjectRevision
from app.db.session import get_session
from app.domain.models import ProjectDocument
from app.repositories import projects as projects_repo
from app.repositories import revisions as revisions_repo
from app.repositories.errors import ConflictError

__all__ = ["bp"]


bp = Blueprint("projects", url_prefix="/api/v1")


def _isoformat(value: datetime) -> str:
    return value.isoformat()


def _project_to_wire(project: Project) -> dict[str, Any]:
    return {
        "id": str(project.id),
        "name": project.name,
        "boardModelId": project.board_model_id,
        "draftVersion": project.draft_version,
        "document": project.document,
        "createdAt": _isoformat(project.created_at),
        "updatedAt": _isoformat(project.updated_at),
    }


def _revision_to_wire(rev: ProjectRevision) -> dict[str, Any]:
    return {
        "id": str(rev.id),
        "projectId": str(rev.project_id),
        "revisionNumber": rev.revision_number,
        "document": rev.document,
        "documentSha256": rev.document_sha256,
        "createdAt": _isoformat(rev.created_at),
    }


@bp.post("/projects")
async def create_project(request: Request) -> HTTPResponse:
    """Create a new project from a name + board id + optional document body."""
    body: dict[str, Any] = request.json or {}
    name = body.get("name")
    board_model_id = body.get("boardModelId") or body.get("board_model_id")
    if not isinstance(name, str) or not name.strip():
        raise AppError("VALIDATION_ERROR", "name is required", status=422)
    if not isinstance(board_model_id, str) or not board_model_id.strip():
        raise AppError("VALIDATION_ERROR", "boardModelId is required", status=422)

    document_body = body.get("document")
    if document_body is not None:
        # Validate via the wire model so callers get fast feedback on typos.
        try:
            document = ProjectDocument.model_validate(document_body).model_dump(by_alias=True)
        except Exception as exc:
            raise AppError("VALIDATION_ERROR", str(exc), status=422) from exc
    else:
        document = {
            "format": "autobreadboard-project",
            "version": 1,
            "name": name,
            "board": {"modelId": board_model_id},
            "components": [],
            "nets": [],
            "layout": {
                "version": 1,
                "boardId": board_model_id,
                "placements": [],
                "jumpers": [],
                "manualElectricalLinks": [],
            },
            "settings": {
                "seed": 12345,
                "solverPreset": "balanced",
                "placementWeights": {},
                "routingWeights": {},
                "allowCriticalNetClasses": False,
            },
            "footprintOverrides": [],
        }

    async with get_session() as session:
        project = await projects_repo.create_project(
            session=session,
            name=name,
            board_model_id=board_model_id,
            document=document,
        )
    return json(_project_to_wire(project), status=201)


@bp.get("/projects")
async def list_projects(request: Request) -> HTTPResponse:
    """Paginated list of projects."""
    try:
        limit = max(1, min(int(request.args.get("limit", 50)), 200))
        offset = max(0, int(request.args.get("offset", 0)))
    except ValueError as exc:
        raise AppError("VALIDATION_ERROR", "limit/offset must be integers", status=422) from exc

    async with get_session() as session:
        items, total = await projects_repo.list_projects(session, limit=limit, offset=offset)
    return json(
        {
            "items": [_project_to_wire(p) for p in items],
            "total": total,
        },
        status=200,
    )


def _parse_uuid(raw: str) -> UUID:
    try:
        return UUID(raw)
    except (ValueError, TypeError) as exc:
        raise AppError("VALIDATION_ERROR", f"invalid uuid {raw!r}", status=422) from exc


@bp.get("/projects/<project_id>")
async def get_project(_: Request, project_id: str) -> HTTPResponse:
    pid = _parse_uuid(project_id)
    async with get_session() as session:
        project = await projects_repo.get_project(session, pid)
    if project is None:
        raise AppError("NOT_FOUND", f"project {project_id} not found", status=404)
    return json(_project_to_wire(project), status=200)


@bp.put("/projects/<project_id>/document")
async def update_document(request: Request, project_id: str) -> HTTPResponse:
    """Optimistic-locked document update (If-Match: <draftVersion>)."""
    pid = _parse_uuid(project_id)
    expected_header = request.headers.get("If-Match")
    if expected_header is None:
        raise AppError(
            "VALIDATION_ERROR",
            "If-Match header with the current draftVersion is required",
            status=428,
        )
    try:
        expected_version = int(expected_header)
    except ValueError as exc:
        raise AppError("VALIDATION_ERROR", "If-Match must be an integer draftVersion", status=422) from exc

    body: dict[str, Any] = request.json or {}
    document_body = body.get("document")
    if not isinstance(document_body, dict):
        raise AppError("VALIDATION_ERROR", "document is required", status=422)
    try:
        document = ProjectDocument.model_validate(document_body).model_dump(by_alias=True)
    except Exception as exc:
        raise AppError("VALIDATION_ERROR", str(exc), status=422) from exc

    try:
        async with get_session() as session:
            project = await projects_repo.update_project_document(
                session=session,
                project_id=pid,
                document=document,
                expected_version=expected_version,
            )
    except ConflictError as exc:
        raise AppError("CONFLICT", str(exc), status=409) from exc

    return json(_project_to_wire(project), status=200)


@bp.delete("/projects/<project_id>")
async def delete_project(_: Request, project_id: str) -> HTTPResponse:
    pid = _parse_uuid(project_id)
    async with get_session() as session:
        removed = await projects_repo.delete_project(session, pid)
    if not removed:
        raise AppError("NOT_FOUND", f"project {project_id} not found", status=404)
    return HTTPResponse(status=204)


@bp.post("/projects/<project_id>/revisions")
async def create_revision(_: Request, project_id: str) -> HTTPResponse:
    """Freeze the current document as an immutable revision."""
    pid = _parse_uuid(project_id)
    async with get_session() as session:
        project = await projects_repo.get_project(session, pid)
        if project is None:
            raise AppError("NOT_FOUND", f"project {project_id} not found", status=404)
        revision = await revisions_repo.create_revision(
            session=session,
            project_id=pid,
            document=project.document,
        )
    return json(_revision_to_wire(revision), status=201)


@bp.get("/projects/<project_id>/revisions")
async def list_revisions(_: Request, project_id: str) -> HTTPResponse:
    pid = _parse_uuid(project_id)
    async with get_session() as session:
        rows = await revisions_repo.list_revisions(session, pid)
    return json([_revision_to_wire(r) for r in rows], status=200)


@bp.get("/revisions/<revision_id>")
async def get_revision(_: Request, revision_id: str) -> HTTPResponse:
    rid = _parse_uuid(revision_id)
    async with get_session() as session:
        revision = await revisions_repo.get_revision(session, rid)
    if revision is None:
        raise AppError("NOT_FOUND", f"revision {revision_id} not found", status=404)
    return json(_revision_to_wire(revision), status=200)
