"""API-facing error envelope.

`AppError` is the single exception type every route handler and middleware maps into the
`{"error": {...}}` JSON body. Domain exceptions (`app.domain.errors`) are translated into an
`AppError` at the API/job boundary, never raised directly to the client.
"""

from __future__ import annotations

from typing import Any

__all__ = ["AppError", "to_response"]


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details

    def to_response(self) -> dict[str, Any]:
        return to_response(self.code, self.message, self.details)


def to_response(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return body
