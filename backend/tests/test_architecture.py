"""Architecture / purity tests for AutoBreadboard.

The domain package (``app/domain/**``) MUST stay free of infrastructure
dependencies: nothing in there may import Sanic, SQLAlchemy, Redis, boto3, arq,
or ``app.settings``. This guarantees the pure solver core can be reused
independently of the API and the worker (e.g. for fixture tests, smoke tests,
and ad-hoc Python invocations from operators).

This module walks every ``.py`` file under ``backend/app/domain/`` via
``ast.parse`` + ``ast.walk``, looks at every ``ast.Import`` /
``ast.ImportFrom`` node, extracts the top-level dotted-module component of each
import (e.g. ``app.settings.base`` -> ``app.settings``, ``sanic.testing`` ->
``sanic``), and asserts none of them match a forbidden root.

The test collects ALL violations across ALL files before raising so the failure
message lists every offender at once rather than one-at-a-time.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# Forbidden top-level dotted-module components. Adding a new infra dependency
# must come with updating this list intentionally.
_FORBIDDEN_IMPORTS: frozenset[str] = frozenset(
    {
        "sanic",
        "sqlalchemy",
        "redis",
        "boto3",
        "arq",
        "app.settings",
    }
)


def _top_level_module(module: str | None) -> str | None:
    """Return the first dotted component of ``module`` or ``None`` if empty.

    ``ast.Import`` and ``ast.ImportFrom`` give us the full dotted name; the
    rule is about the top-level package only (``sanic.testing`` -> ``sanic``,
    ``app.settings.base`` -> ``app.settings``).
    """
    if not module:
        return None
    head = module.split(".", 1)[0]
    return head or None


def _scan_file(path: Path) -> list[tuple[int, str]]:
    """Return a list of ``(line, module)`` violations for ``path``.

    The source is parsed with ``ast.parse``; the resulting ``Module`` body is
    walked once for ``ast.Import`` / ``ast.ImportFrom`` nodes. Each yielded
    node carries a ``lineno`` pointing at the ``import`` keyword.
    """
    violations: list[tuple[int, str]] = []
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = _top_level_module(alias.name)
                if top in _FORBIDDEN_IMPORTS:
                    violations.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            top = _top_level_module(node.module)
            if top in _FORBIDDEN_IMPORTS:
                violations.append((node.lineno, node.module or ""))
    return violations


def test_domain_does_not_import_infrastructure() -> None:
    """Every ``.py`` file under ``app/domain/`` must be infra-free.

    Walks the directory, collects ALL ``file:line`` violations across the whole
    tree, and then fails with a single, well-formatted multi-line listing.
    """
    domain_root = Path(__file__).resolve().parents[1] / "app" / "domain"
    assert domain_root.is_dir(), f"domain root missing: {domain_root}"

    all_violations: list[tuple[Path, int, str]] = []
    for path in sorted(domain_root.rglob("*.py")):
        # __pycache__ contains compiled artefacts that aren't on the source
        # tree; rglob already excludes them by virtue of ``*.py`` not matching,
        # but be defensive in case a stray ``*.py`` shows up there.
        if "__pycache__" in path.parts:
            continue
        for lineno, module in _scan_file(path):
            all_violations.append((path, lineno, module))

    if not all_violations:
        return

    lines = ["Domain purity violations found (forbidden imports):"]
    for path, lineno, module in all_violations:
        rel = path.relative_to(domain_root.parent.parent)
        lines.append(f"  {rel}:{lineno}  ->  {module}")
    pytest.fail("\n".join(lines))


def test_place_cpsat_has_no_io_imports() -> None:
    """Explicit, narrowly-targeted purity check for the CP-SAT placer.

    ``place_cpsat`` is allowed to import OR-Tools (its only non-app-domain
    dependency) and the rest of ``app.domain``. Anything else is a leak.
    """
    from app.domain.traces import place_cpsat as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(mod.__file__))
    forbidden = {"sanic", "sqlalchemy", "redis", "boto3", "arq", "app.settings"}
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                head = (alias.name or "").split(".", 1)[0]
                if head in forbidden:
                    offenders.append(f"line {node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            head = (node.module or "").split(".", 1)[0]
            if head in forbidden:
                offenders.append(f"line {node.lineno}: from {node.module} import ...")
    assert not offenders, "place_cpsat must not import: " + "; ".join(offenders)
