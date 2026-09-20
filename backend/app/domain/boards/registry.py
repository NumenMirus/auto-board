"""Builtin board registry — breadboard and perfboard.

`BUILTIN_BOARDS` is a plain dict populated at module import time. Each entry
is built via an `lru_cache`-wrapped factory so the (large) hole list is
constructed at most once per factory even if the registry is re-imported under
module-cache invalidation.

A board id may resolve to either a :class:`BreadboardModel` or a
:class:`PerfboardModel`; the helper :func:`get_board_model` returns the
appropriate concrete type and the discriminator used by callers (API, solver
dispatch) is the registered id namespace, not the returned instance class.
"""

from __future__ import annotations

from functools import lru_cache

from app.domain.boards.half400 import build_half400
from app.domain.boards.perfboard import build_perfboard
from app.domain.errors import InvalidInput
from app.domain.models import BreadboardModel, PerfboardModel

__all__ = ["BUILTIN_BOARDS", "BUILTIN_PERFBOARDS", "get_board_model", "is_perfboard_id"]


@lru_cache(maxsize=1)
def _split_rails_board() -> BreadboardModel:
    return build_half400(split_rails=True)


@lru_cache(maxsize=1)
def _continuous_rails_board() -> BreadboardModel:
    return build_half400(split_rails=False)


@lru_cache(maxsize=1)
def _perfboard_20x30_single() -> PerfboardModel:
    return build_perfboard(rows=20, cols=30, layers=1)


@lru_cache(maxsize=1)
def _perfboard_20x30_double() -> PerfboardModel:
    return build_perfboard(rows=20, cols=30, layers=2)


@lru_cache(maxsize=1)
def _perfboard_15x20_double() -> PerfboardModel:
    return build_perfboard(rows=15, cols=20, layers=2)


# Id prefix ``strip-`` is the convention for perfboard entries; ``half-``
# denotes breadboard entries. The dispatch layer (solver_job) keys off the
# ``strip-`` prefix to pick the trace pipeline.
BUILTIN_BOARDS: dict[str, BreadboardModel | PerfboardModel] = {
    "half-400-standard-split-rails": _split_rails_board(),
    "half-400-standard-continuous-rails": _continuous_rails_board(),
    "strip-20x30-single": _perfboard_20x30_single(),
    "strip-20x30-double": _perfboard_20x30_double(),
    "strip-15x20-double": _perfboard_15x20_double(),
}

# Subset of BUILTIN_BOARDS containing only perfboard entries — convenient for
# callers (e.g. seed script, board-listing UI) that want just this family
# without re-checking isinstance on every entry.
BUILTIN_PERFBOARDS: dict[str, PerfboardModel] = {
    board_id: model for board_id, model in BUILTIN_BOARDS.items() if isinstance(model, PerfboardModel)
}


def get_board_model(board_id: str) -> BreadboardModel | PerfboardModel:
    """Return the registered board model for ``board_id``.

    Raises ``InvalidInput`` when the id is unknown so callers (API/repositories)
    can map the failure to the proper API error envelope.
    """
    if board_id not in BUILTIN_BOARDS:
        raise InvalidInput(f"Unknown board model {board_id!r}")
    return BUILTIN_BOARDS[board_id]


def is_perfboard_id(board_id: str) -> bool:
    """Return ``True`` when ``board_id`` resolves to a perfboard entry."""
    model = BUILTIN_BOARDS.get(board_id)
    return model is not None and isinstance(model, PerfboardModel)
