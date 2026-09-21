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

__all__ = [
    "BUILTIN_BOARDS",
    "BUILTIN_PERFBOARDS",
    "get_board_model",
    "is_perfboard_id",
    "PERFBOARD_ID_ALIASES",
    "resolve_board_id",
]


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
#
# The board-model id namespace is being migrated from the legacy ``strip-``
# prefix to the more explicit ``perfboard-`` prefix because every entry in
# this registry is an isolated-hole, two-layer perfboard — the legacy
# ``strip-`` name is misleading for the actual electrical substrate (see
# ``docs/perfboard-cpsat-placer.md`` for the rationale). The legacy ids
# remain registered as primary keys; the new ids are documented aliases
# that resolve to the same model object.
BUILTIN_BOARDS: dict[str, BreadboardModel | PerfboardModel] = {
    "half-400-standard-split-rails": _split_rails_board(),
    "half-400-standard-continuous-rails": _continuous_rails_board(),
    "strip-20x30-single": _perfboard_20x30_single(),
    "strip-20x30-double": _perfboard_20x30_double(),
    "strip-15x20-double": _perfboard_15x20_double(),
}

# Documented aliases — every entry here resolves to the same model as its
# primary key in ``BUILTIN_BOARDS``. New project documents should use the
# ``perfboard-*`` namespace; old documents using ``strip-*`` keep working.
PERFBOARD_ID_ALIASES: dict[str, str] = {
    "perfboard-20x30-single-sided": "strip-20x30-single",
    "perfboard-20x30-double-sided": "strip-20x30-double",
    "perfboard-15x20-double-sided": "strip-15x20-double",
}

# Subset of BUILTIN_BOARDS containing only perfboard entries — convenient for
# callers (e.g. seed script, board-listing UI) that want just this family
# without re-checking isinstance on every entry.
BUILTIN_PERFBOARDS: dict[str, PerfboardModel] = {
    board_id: model for board_id, model in BUILTIN_BOARDS.items() if isinstance(model, PerfboardModel)
}


def resolve_board_id(board_id: str) -> str:
    """Return the canonical primary key for ``board_id``.

    Both primary ids (``strip-*``) and documented aliases
    (``perfboard-*``) resolve to the same primary id; unknown ids are
    returned unchanged so :func:`get_board_model` can raise the
    :class:`InvalidInput` error.
    """
    return PERFBOARD_ID_ALIASES.get(board_id, board_id)


def get_board_model(board_id: str) -> BreadboardModel | PerfboardModel:
    """Return the registered board model for ``board_id``.

    Accepts both primary ids (``strip-*``) and documented aliases
    (``perfboard-*``). Raises ``InvalidInput`` when the resolved primary
    id is unknown so callers (API/repositories) can map the failure to
    the proper API error envelope.
    """
    canonical = resolve_board_id(board_id)
    if canonical not in BUILTIN_BOARDS:
        raise InvalidInput(f"Unknown board model {board_id!r}")
    return BUILTIN_BOARDS[canonical]


def is_perfboard_id(board_id: str) -> bool:
    """Return ``True`` when ``board_id`` resolves to a perfboard entry.

    Accepts both primary ids (``strip-*``) and documented aliases
    (``perfboard-*``).
    """
    canonical = resolve_board_id(board_id)
    model = BUILTIN_BOARDS.get(canonical)
    return model is not None and isinstance(model, PerfboardModel)
