"""Export rendering service.

Real implementations of every format declared in :data:`FORMAT_CONTENT_TYPES`:

* ``svg`` / ``png`` / ``pdf`` — render the breadboard layout as a visual document;
* ``json`` — emit a re-parseable export envelope (NOT a full ``ProjectDocument`` since
  we only have board/components/nets/layout/project_name here);
* ``bom-csv`` / ``jumpers-csv`` — structured tabular exports;
* ``instructions-md`` — the markdown rendering of the assembly guide.

PDF is a single-page rendering of the layout SVG only. True multi-page concatenation
(layout + instructions) requires ``pypdf`` which is intentionally not in the
dependency tree (see ``pyproject.toml``); the instructions are produced separately
via the ``'instructions-md'`` format. This is an accepted scope decision for the
current milestone — see the comment above the ``'pdf'`` branch.
"""

from __future__ import annotations

import csv
import io
import json
from typing import TYPE_CHECKING

from app.domain.excellon import render_excellon
from app.domain.footprints.registry import FOOTPRINTS
from app.domain.gerber import render_gerber
from app.domain.index import BoardIndex
from app.domain.instructions import AssemblyInstructions, build_instructions
from app.domain.instructions_perfboard import build_instructions as build_perfboard_instructions
from app.domain.models import (
    BreadboardModel,
    Component,
    Layout,
    Net,
    PerfboardModel,
    TraceLayout,
)
from app.domain.perfboards.registry import PERFBOARD_FOOTPRINTS
from app.domain.render import render_svg

if TYPE_CHECKING:
    pass

__all__ = ["FORMAT_CONTENT_TYPES", "render_export"]

FORMAT_CONTENT_TYPES: dict[str, str] = {
    "svg": "image/svg+xml",
    "png": "image/png",
    "pdf": "application/pdf",
    "json": "application/json",
    "bom-csv": "text/csv",
    "jumpers-csv": "text/csv",
    "instructions-md": "text/markdown",
    # Perfboard-specific formats
    "gerber-top": "application/x-gerber",
    "gerber-bottom": "application/x-gerber",
    "gerber-outline": "application/x-gerber",
    "drill": "application/x-excellon",
    "placement-csv": "text/csv",
}


# Canonical (canonical) BOM / jumper column order — keep stable, downstream tooling
# keys off these exact header strings.
_BOM_HEADERS: tuple[str, ...] = ("value", "footprintId", "quantity", "refs")
_JUMPER_HEADERS: tuple[str, ...] = (
    "id",
    "netId",
    "netName",
    "fromHole",
    "toHole",
    "color",
    "lengthMm",
    "layer",
)

# Italian instructions page layout (used only inside the single-page PDF, not
# exported as a standalone format).
_INSTRUCTIONS_PAGE_MARGIN_MM: float = 12.0
_INSTRUCTIONS_PAGE_HEIGHT_MM: float = 297.0  # A4 portrait
_INSTRUCTIONS_PAGE_WIDTH_MM: float = 210.0
_INSTRUCTIONS_FONT_SIZE_PX: float = 11.0
_INSTRUCTIONS_TITLE_FONT_SIZE_PX: float = 16.0


async def render_export(
    format: str,
    board: BreadboardModel | PerfboardModel,
    components: list[Component],
    nets: list[Net],
    layout: Layout | TraceLayout,
    project_name: str,
) -> tuple[bytes, str]:
    """Render an export artefact.

    ``format`` is one of the keys in :data:`FORMAT_CONTENT_TYPES`. Returns a
    ``(bytes, content_type)`` tuple ready for S3 upload. ``board`` may be a
    :class:`BreadboardModel` or a :class:`PerfboardModel`; perfboard-only
    formats (``gerber-*``, ``drill``, ``placement-csv``) require the latter.
    """
    if format not in FORMAT_CONTENT_TYPES:
        raise ValueError(f"unknown export format: {format}")

    if format == "svg":
        return _render_svg(board, components, nets, layout)
    if format == "png":
        return _render_png(board, components, nets, layout)
    if format == "pdf":
        return _render_pdf(board, components, nets, layout, project_name)
    if format == "json":
        return _render_json(board, components, nets, layout, project_name)
    if format == "bom-csv":
        return _render_bom_csv(components)
    if format == "jumpers-csv":
        if not isinstance(layout, Layout):
            raise ValueError("jumpers-csv export requires a breadboard Layout")
        return _render_jumpers_csv(layout, nets)
    if format == "instructions-md":
        return _render_instructions_md(board, components, nets, layout, project_name)

    # Perfboard-only formats below
    if not isinstance(board, PerfboardModel):
        raise ValueError(f"format {format!r} is only valid for perfboard boards")
    if not isinstance(layout, TraceLayout):
        raise ValueError(f"format {format!r} requires a TraceLayout")

    if format in ("gerber-top", "gerber-bottom", "gerber-outline"):
        return _render_gerber_part(board, components, layout, format)
    if format == "drill":
        return _render_drill(board, components, layout)
    if format == "placement-csv":
        return _render_placement_csv(board, components, layout)

    # Defensive: all keys above are handled; the early-out for unknown keys already
    # raised. Kept for type-checkers that cannot narrow ``format``.
    raise ValueError(f"unknown export format: {format}")


# --------------------------------------------------------------------------
# Format implementations
# --------------------------------------------------------------------------


def _build_index(board: BreadboardModel) -> BoardIndex:
    """Build a :class:`BoardIndex` for ``board``.

    Caching by ``board.id`` is the caller's job (API / worker); this helper stays
    pure for testability.
    """
    return BoardIndex.build(board)


def _render_svg(
    board: BreadboardModel | PerfboardModel,
    components: list[Component],
    nets: list[Net],
    layout: Layout | TraceLayout,
) -> tuple[bytes, str]:
    if isinstance(board, PerfboardModel):
        if not isinstance(layout, TraceLayout):
            raise ValueError("perfboard svg export requires a TraceLayout")
        from app.domain.render_traces import render_traces as render_traces_svg

        svg_str = render_traces_svg(board, components, PERFBOARD_FOOTPRINTS, layout)
    else:
        if not isinstance(layout, Layout):
            raise ValueError("breadboard svg export requires a Layout")
        index = _build_index(board)
        svg_str = render_svg(board, index, FOOTPRINTS, components, nets, layout)
    return svg_str.encode("utf-8"), FORMAT_CONTENT_TYPES["svg"]


def _render_png(
    board: BreadboardModel | PerfboardModel,
    components: list[Component],
    nets: list[Net],
    layout: Layout | TraceLayout,
) -> tuple[bytes, str]:
    # cairosvg is imported lazily so the module is importable on machines without
    # the native libcairo (e.g. CI containers running only the SVG/JSON tests).
    import cairosvg  # type: ignore[import-untyped]

    svg_bytes, _ = _render_svg(board, components, nets, layout)
    png_bytes = cairosvg.svg2png(bytestring=svg_bytes, scale=2)
    return png_bytes, FORMAT_CONTENT_TYPES["png"]


def _render_pdf(
    board: BreadboardModel | PerfboardModel,
    components: list[Component],
    nets: list[Net],
    layout: Layout | TraceLayout,
    project_name: str,
) -> tuple[bytes, str]:
    # SCOPE NOTE (milestone): a true multi-page PDF (layout page + instructions page)
    # would require a PDF-merging library (`pypdf` or similar). `pypdf` is intentionally
    # NOT in the runtime dependency tree (see `pyproject.toml`), and `cairosvg.svg2pdf`
    # renders only one SVG per call. For this milestone we emit a single-page PDF
    # containing the layout SVG only; the assembly instructions are produced separately
    # via the `'instructions-md'` format. When a PDF merger is added to the dependency
    # tree, this branch should render both SVGs (layout + instructions page) and
    # concatenate them — see the design notes in the milestone plan.
    import cairosvg

    svg_bytes, _ = _render_svg(board, components, nets, layout)
    pdf_bytes = cairosvg.svg2pdf(bytestring=svg_bytes)
    _ = project_name  # unused for the single-page layout-only PDF
    return pdf_bytes, FORMAT_CONTENT_TYPES["pdf"]


def _render_json(
    board: BreadboardModel | PerfboardModel,
    components: list[Component],
    nets: list[Net],
    layout: Layout | TraceLayout,
    project_name: str,
) -> tuple[bytes, str]:
    # Emit a self-describing export envelope. This is intentionally NOT a full
    # `ProjectDocument`: we do not have the project's `settings` (seed / weights /
    # preset) or `footprint_overrides`, so a `ProjectDocument` round-trip would be
    # lossy. Consumers that need a re-importable project document should use the
    # project PUT/POST API; this export is for archival / sharing.
    payload: dict[str, object] = {
        "format": "autobreadboard-export",
        "version": 1,
        "projectName": project_name,
        "board": board.model_dump(by_alias=True),
        "components": [c.model_dump(by_alias=True) for c in components],
        "nets": [n.model_dump(by_alias=True) for n in nets],
        "layout": layout.model_dump(by_alias=True),
    }
    body = json.dumps(payload, indent=2).encode("utf-8")
    return body, FORMAT_CONTENT_TYPES["json"]


def _render_bom_csv(components: list[Component]) -> tuple[bytes, str]:
    # Aggregate by (value, footprint_id); value may be None (empty CSV field).
    groups: dict[tuple[str | None, str], list[str]] = {}
    for c in components:
        key = (c.value, c.footprint_id)
        groups.setdefault(key, []).append(c.ref)

    # Stable sort: by footprint_id then by value (None sorts last).
    def sort_key(item: tuple[tuple[str | None, str], list[str]]) -> tuple[str, tuple[int, str]]:
        (value, footprint_id), _refs = item
        value_sort = (1, "") if value is None else (0, value)
        return (footprint_id, value_sort)

    sorted_groups = sorted(groups.items(), key=sort_key)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_BOM_HEADERS)
    for (value, footprint_id), refs in sorted_groups:
        refs_sorted = sorted(refs)
        row = [
            value if value is not None else "",
            footprint_id,
            len(refs_sorted),
            ";".join(refs_sorted),
        ]
        writer.writerow(row)
    return buf.getvalue().encode("utf-8"), FORMAT_CONTENT_TYPES["bom-csv"]


def _render_jumpers_csv(layout: Layout, nets: list[Net]) -> tuple[bytes, str]:
    net_by_id = {n.id: n for n in nets}
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_JUMPER_HEADERS)
    for jumper in layout.jumpers:
        net = net_by_id.get(jumper.net_id)
        net_name = net.name if net is not None else ""
        writer.writerow(
            [
                jumper.id,
                jumper.net_id,
                net_name,
                jumper.start_hole_id,
                jumper.end_hole_id,
                jumper.color or "",
                f"{jumper.estimated_length_mm:.1f}",
                jumper.path.layer,
            ]
        )
    return buf.getvalue().encode("utf-8"), FORMAT_CONTENT_TYPES["jumpers-csv"]


def _render_instructions_md(
    board: BreadboardModel | PerfboardModel,
    components: list[Component],
    nets: list[Net],
    layout: Layout | TraceLayout,
    project_name: str,
) -> tuple[bytes, str]:
    if isinstance(board, PerfboardModel):
        if not isinstance(layout, TraceLayout):
            raise ValueError("perfboard instructions-md export requires a TraceLayout")
        perf_instructions = build_perfboard_instructions(board, components, nets, layout)
        body = _render_perfboard_instructions_markdown(perf_instructions, project_name)
    else:
        if not isinstance(layout, Layout):
            raise ValueError("breadboard instructions-md export requires a Layout")
        index = _build_index(board)
        instructions = build_instructions(board, index, FOOTPRINTS, components, nets, layout)
        body = _render_instructions_markdown(instructions, project_name)
    return body.encode("utf-8"), FORMAT_CONTENT_TYPES["instructions-md"]


def _render_instructions_markdown(instructions: AssemblyInstructions, project_name: str) -> str:
    """Render the instruction steps as a Markdown document.

    Pure string formatting — no markdown library. Component steps use ``description``;
    jumper steps additionally inline the formatted ``jumper_line``.
    """
    lines: list[str] = []
    lines.append(f"# Istruzioni di montaggio — {project_name}")
    lines.append("")
    lines.append(
        "Seguire i passi nell'ordine indicato. I ponticelli di potenza/massa sono "
        "sempre cablati per ultimi, indipendentemente dalla lunghezza."
    )
    lines.append("")
    for step in instructions.steps:
        if step.kind == "verify":
            lines.append(f"{step.order + 1}. **{step.description}**")
        elif step.jumper_line is not None:
            lines.append(f"{step.order + 1}. {step.description}  ")
            lines.append(f"   `{step.jumper_line}`")
        else:
            lines.append(f"{step.order + 1}. {step.description}")
    lines.append("")
    return "\n".join(lines)


def _render_perfboard_instructions_markdown(
    instructions: object,
    project_name: str,
) -> str:
    """Render a perfboard :class:`AssemblyInstructions` (title/steps/bom_lines)."""
    lines: list[str] = []
    lines.append(f"# {instructions.title}")  # type: ignore[attr-defined]
    lines.append("")
    lines.append(f"Progetto: {project_name}")
    lines.append("")
    lines.append("## Distinta componenti")
    lines.append("")
    for bom_line in instructions.bom_lines:  # type: ignore[attr-defined]
        lines.append(f"- {bom_line}")
    lines.append("")
    lines.append("## Passi di montaggio")
    lines.append("")
    for i, step in enumerate(instructions.steps, start=1):  # type: ignore[attr-defined]
        lines.append(f"{i}. {step}")
    lines.append("")
    return "\n".join(lines)


def _render_gerber_part(
    board: PerfboardModel,
    components: list[Component],
    layout: TraceLayout,
    format: str,
) -> tuple[bytes, str]:
    bundle = render_gerber(board, components, PERFBOARD_FOOTPRINTS, layout)
    if format == "gerber-top":
        body = bundle.top_copper
    elif format == "gerber-bottom":
        body = bundle.bottom_copper
    else:
        body = bundle.board_outline
    return body.encode("utf-8"), FORMAT_CONTENT_TYPES[format]


def _render_drill(
    board: PerfboardModel,
    components: list[Component],
    layout: TraceLayout,
) -> tuple[bytes, str]:
    body = render_excellon(board, components, PERFBOARD_FOOTPRINTS, layout)
    return body.encode("utf-8"), FORMAT_CONTENT_TYPES["drill"]


_PLACEMENT_CSV_HEADERS: tuple[str, ...] = (
    "ref",
    "value",
    "footprintId",
    "xMm",
    "yMm",
    "rotationDeg",
    "layer",
)


def _render_placement_csv(
    board: PerfboardModel,
    components: list[Component],
    layout: TraceLayout,
) -> tuple[bytes, str]:
    """Pick-and-place CSV: one row per component, board-absolute mm position.

    All perfboard components are placed on the top (component) side in the
    current MVP — a dedicated bottom-side assembly flow is not modelled yet,
    so ``layer`` is always ``"top"``.
    """
    comp_by_ref = {c.ref: c for c in components}
    hole_by_id = {h.id: h for h in board.holes}
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_PLACEMENT_CSV_HEADERS)
    for placement in sorted(layout.placements, key=lambda p: p.component_ref):
        comp = comp_by_ref.get(placement.component_ref)
        if comp is None:
            continue
        anchor = hole_by_id.get(placement.anchor_hole_id)
        x_mm = anchor.point.x if anchor is not None else 0.0
        y_mm = anchor.point.y if anchor is not None else 0.0
        writer.writerow(
            [
                comp.ref,
                comp.value or "",
                comp.footprint_id,
                f"{x_mm:.2f}",
                f"{y_mm:.2f}",
                str(placement.orientation),
                "top",
            ]
        )
    return buf.getvalue().encode("utf-8"), FORMAT_CONTENT_TYPES["placement-csv"]
