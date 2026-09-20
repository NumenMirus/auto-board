"""Builtin breadboard registry.

`BUILTIN_BOARDS` is a plain dict populated at module import time. Each entry is built via
an `lru_cache`-wrapped factory so the (large) hole list is constructed at most once per
factory even if the registry is re-imported under module-cache invalidation.
"""

from __future__ import annotations

from functools import lru_cache

from app.domain.boards.half400 import build_half400
from app.domain.errors import InvalidInput
from app.domain.models import BreadboardModel

__all__ = ["BUILTIN_BOARDS", "get_board_model"]


@lru_cache(maxsize=1)
def _split_rails_board() -> BreadboardModel:
    return build_half400(split_rails=True)


@lru_cache(maxsize=1)
def _continuous_rails_board() -> BreadboardModel:
    return build_half400(split_rails=False)


BUILTIN_BOARDS: dict[str, BreadboardModel] = {
    "half-400-standard-split-rails": _split_rails_board(),
    "half-400-standard-continuous-rails": _continuous_rails_board(),
}


def get_board_model(board_id: str) -> BreadboardModel:
    """Return the registered `BreadboardModel` for `board_id`.

    Raises `InvalidInput` when the id is unknown so callers (API/repositories) can map
    the failure to the proper API error envelope.
    """
    if board_id not in BUILTIN_BOARDS:
        raise InvalidInput(f"Unknown board model {board_id!r}")
    return BUILTIN_BOARDS[board_id]
