"""Builtin board models and registry."""

from __future__ import annotations

from app.domain.boards.half400 import build_half400
from app.domain.boards.registry import BUILTIN_BOARDS, get_board_model

__all__ = ["BUILTIN_BOARDS", "build_half400", "get_board_model"]
