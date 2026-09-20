"""Repository-level exceptions.

These are raised by the persistence layer when a write fails for a reason the
caller can recover from (optimistic-lock collision). Infrastructure failures
(network errors, lost connections, constraint violations that aren't a
conflict) propagate as the underlying driver exception so the caller can decide
whether to retry or surface the failure.
"""

from __future__ import annotations

__all__ = ["ConflictError"]


class ConflictError(Exception):
    """Raised when an optimistic-locking update finds no row matching.

    The repository increments ``draft_version`` only when the
    ``WHERE id=:id AND draft_version=:expected`` clause still matches; if zero
    rows are affected the caller is operating on a stale view of the document
    and the write is rejected with this exception so the API can return 409.
    """
