"""Domain-level exceptions raised by the pure solver core.

These carry no HTTP semantics; `app.core.errors` maps them to the API error envelope.
"""

from __future__ import annotations

__all__ = ["DomainError", "InvalidInput", "SolverCancelled", "SolverTimeout"]


class DomainError(Exception):
    """Base class for deterministic solver/domain failures.

    A `DomainError` raised from a solver job must never be retried by the job queue: the
    same input will fail the same way again.
    """


class InvalidInput(DomainError):
    """The request failed structural validation before the solver could run."""


class SolverCancelled(DomainError):
    """The solver observed a cancellation signal and stopped early."""


class SolverTimeout(DomainError):
    """The solver exceeded its configured or default deadline."""
