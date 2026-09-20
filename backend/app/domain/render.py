"""Breadboard layout SVG renderer.

Pure string-building SVG generator: no XML library is used so the produced bytes are
deterministic down to attribute order, float formatting, and element ordering. The
golden-file tests under ``backend/tests/golden/`` compare the output byte-for-byte.

Determinism rules (do not violate):

* every float coordinate is formatted with ``f"{v:.2f}"`` — never ``str(v)``, never ``repr(v)``;
* every SVG element emits its attributes in a fixed order chosen once here and never varied
  between elements of the same kind;
* the iteration order over ``board.holes``, ``board.electrical_groups``, ``layout.placements``
  and ``layout.jumpers`` is their natural Pydantic list order (already deterministic);
* the only ``dict`` lookups used internally are for O(1) hole-id → coordinate resolution;
  no ``dict`` / ``set`` is iterated where its order would leak into the output.

The z-order is back-to-front: board outline → tie-point group shading → rail background
strips → holes → component bodies → jumpers → diagnostic markers → axis labels.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.index import BoardIndex
from app.domain.models import (
    BreadboardFootprint,
    BreadboardModel,
    Component,
    ComponentPlacement,
    Diagnostic,
    Jumper,
    Layout,
    Net,
    Point,
)

__all__ = ["RenderOptions", "render_svg"]


# --------------------------------------------------------------------------
# Public configuration
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RenderOptions:
    """Knobs for :func:`render_svg`.

    All defaults reproduce the unhighlighted, full-detail rendering used by the
    browser's :class:`BoardCanvas` and by the SVG/PNG/PDF exporters.
    """

    show_labels: bool = True
    highlight_net_id: str | None = None
    show_groups: bool = True
    width_scale: float = 4.0


# Module-level singleton default to satisfy B008 without recomputing it per call.
_DEFAULT_RENDER_OPTIONS: RenderOptions = RenderOptions()


# --------------------------------------------------------------------------
# Tunables — kept as module constants so golden bytes are reproducible.
# --------------------------------------------------------------------------


_FONT_FAMILY: str = "DejaVu Sans, sans-serif"

# Board outline margin in mm (kept small but large enough that the top rail at y=-12.70
# and the bottom rail at y=40.64 are fully inside the viewport).
_MARGIN_MM: float = 6.0

# Stroke widths in millimetres (the SVG's native coordinate space — see the
# viewBox/width/height split below). They do not need a manual width_scale
# multiplication: the SVG's own viewBox-to-viewport mapping already scales
# every native-mm quantity uniformly when the document is rendered at its
# declared (scaled) pixel `width`/`height`.
_HOLE_STROKE: float = 0.6
_BOARD_STROKE: float = 1.0
_GROUP_STROKE: float = 0.4
_RAIL_BG_STROKE: float = 0.0  # background strips are fills only

# Jumper stroke widths in millimetres — see the note above `_HOLE_STROKE`.
_JUMPER_STROKE_LOWER_MUL: float = 1.2
_JUMPER_STROKE_UPPER_MUL: float = 1.6

# Diagnostic marker radii in millimetres — see the note above `_HOLE_STROKE`.
_DIAG_MARKER_R_ERROR: float = 3.5
_DIAG_MARKER_R_WARNING: float = 3.0
_DIAG_MARKER_R_INFO: float = 2.5

# Pin / polarity marker sizes in mm (so they scale with the board).
_POLARITY_TRIANGLE_SIZE_MM: float = 3.0

# Column / row label font size in millimetres — see the note above
# `_HOLE_STROKE`.
_LABEL_FONT_SIZE_MUL: float = 1.6

# Jumper midpoint circle radius in millimetres — see the note above
# `_HOLE_STROKE`.
_JUMPER_LABEL_R_MUL: float = 0.9

# Lock-icon size in mm — small visual cue, not load-bearing.
_LOCK_SIZE_MM: float = 3.0

# Label column spacing: render at columns 1, 5, 10, 15, 20, 25, 30 (matches main spec §9.3).
_LABEL_COLS: tuple[int, ...] = (1, 5, 10, 15, 20, 25, 30)

# Colour palette — fixed so the goldens stay byte-identical.
_COL_BOARD_OUTLINE: str = "#222222"
_COL_GROUP_FILL: str = "#f0f0f0"
_COL_GROUP_STROKE: str = "#cccccc"
_COL_HOLE_FILL: str = "#ffffff"
_COL_HOLE_STROKE: str = "#888888"
_COL_RAIL_PLUS_FILL: str = "#d92b2b"
_COL_RAIL_MINUS_FILL: str = "#1a1a1a"
_COL_RAIL_BG_OPACITY: str = "0.18"
_COL_COMPONENT_FILL: str = "#e6f2ff"
_COL_COMPONENT_STROKE: str = "#3b7dd8"
_COL_COMPONENT_LABEL: str = "#0b3d91"
_COL_LOCK_FILL: str = "#444444"
_COL_JUMPER_LABEL_FILL: str = "#ffffff"
_COL_JUMPER_LABEL_STROKE: str = "#222222"
_COL_LABEL_TEXT: str = "#444444"
_COL_POLARITY_FILL: str = "#1a1a1a"

_DIAG_COLORS: dict[str, str] = {
    "error": "#d92b2b",
    "warning": "#e0a800",
    "info": "#3b7dd8",
}
_DIAG_STROKE: str = "#222222"

_DEFAULT_JUMPER_COLOR: str = "#1f77b4"

_RAIL_LINE_RE = re.compile(r"^rail-(?P<line>[a-z]+-[a-z]+)-(?P<seq>\d+)$")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _fmt(v: float) -> str:
    """Format a coordinate with fixed precision; goldens depend on this exact string."""
    return f"{v:.2f}"


def _hole_xy(index: BoardIndex, hole_id: str) -> tuple[float, float]:
    """Return ``(x, y)`` in mm for ``hole_id`` via O(1) index lookup."""
    return index.hole_point(hole_id)


def _group_bounds_mm(
    index: BoardIndex,
    group_hole_ids: list[str],
) -> tuple[float, float, float, float]:
    """Bounding box ``(xmin, ymin, xmax, ymax)`` in mm over a list of hole ids."""
    xs: list[float] = []
    ys: list[float] = []
    for hid in group_hole_ids:
        try:
            x, y = _hole_xy(index, hid)
        except KeyError:
            continue
        xs.append(x)
        ys.append(y)
    if not xs:
        return 0.0, 0.0, 0.0, 0.0
    return min(xs), min(ys), max(xs), max(ys)


def _component_placement_box_mm(
    placement: ComponentPlacement,
    index: BoardIndex,
    margin_mm: float,
) -> tuple[float, float, float, float] | None:
    """Bounding box of a placed component's occupied holes, with a small margin."""
    xs: list[float] = []
    ys: list[float] = []
    for hid in placement.occupied_hole_ids:
        try:
            x, y = _hole_xy(index, hid)
        except KeyError:
            continue
        xs.append(x)
        ys.append(y)
    if not xs:
        return None
    return min(xs) - margin_mm, min(ys) - margin_mm, max(xs) + margin_mm, max(ys) + margin_mm


def _pin_hole_xy(
    placement: ComponentPlacement,
    pin_name: str,
    index: BoardIndex,
) -> tuple[float, float] | None:
    """Resolve a footprint pin name to ``(x, y)`` mm via the placement's pin mapping."""
    hole_id = placement.pin_holes.get(pin_name)
    if hole_id is None:
        return None
    try:
        return _hole_xy(index, hole_id)
    except KeyError:
        return None


def _net_pin_holes_for_component(
    component_ref: str,
    nets: list[Net],
    placement: ComponentPlacement,
) -> set[str]:
    """Return the set of hole ids belonging to pins of ``component_ref`` that belong to ``nets``."""
    out: set[str] = set()
    for net in nets:
        for pin in net.pins:
            if pin.component_ref != component_ref:
                continue
            hid = placement.pin_holes.get(pin.pin)
            if hid is not None:
                out.add(hid)
    return out


def _placement_belongs_to_highlighted_net(
    placement: ComponentPlacement,
    component: Component | None,
    nets: list[Net],
    highlight_net_id: str | None,
) -> bool:
    """True when any pin of ``placement`` belongs to the highlighted net."""
    if highlight_net_id is None:
        return False
    for net in nets:
        if net.id != highlight_net_id:
            continue
        for pin in net.pins:
            if pin.component_ref == placement.component_ref and pin.pin in placement.pin_holes:
                return True
    _ = component  # component not used in the highlight test; kept for future extension
    return False


def _jumper_belongs_to_highlighted_net(jumper: Jumper, highlight_net_id: str | None) -> bool:
    if highlight_net_id is None:
        return False
    return jumper.net_id == highlight_net_id


def _polygon_points_str(points: list[Point]) -> str:
    """Format a list of points as an SVG ``points`` attribute (``"x,y x,y …"``)."""
    return " ".join(f"{_fmt(p.x)},{_fmt(p.y)}" for p in points)


def _midpoint(points: list[Point]) -> tuple[float, float]:
    """Geometric midpoint of a polyline (arithmetic mean of its vertices)."""
    if not points:
        return 0.0, 0.0
    sx = sum(p.x for p in points) / len(points)
    sy = sum(p.y for p in points) / len(points)
    return sx, sy


# --------------------------------------------------------------------------
# Main entry point
# --------------------------------------------------------------------------


def render_svg(
    board: BreadboardModel,
    index: BoardIndex,
    footprints: dict[str, BreadboardFootprint],
    components: list[Component],
    nets: list[Net],
    layout: Layout,
    options: RenderOptions | None = None,
    diagnostics: list[Diagnostic] | None = None,
) -> str:
    """Render the layout as a deterministic SVG document string.

    The optional ``diagnostics`` parameter is appended as the LAST positional parameter so
    the previously-documented positional signature is preserved; callers that omit it get
    no diagnostic markers.
    """
    if options is None:
        options = _DEFAULT_RENDER_OPTIONS
    # O(1) component lookup by ref — never iterated (only used for membership checks).
    component_by_ref: dict[str, Component] = {c.ref: c for c in components}

    # Resolve the placement's footprint id from the matching Component.
    # Note: ComponentPlacement does NOT carry footprint_id — it is looked up via
    # Component.footprint_id of the placement's component_ref.
    footprint_for_placement: dict[str, BreadboardFootprint] = {}
    for placement in layout.placements:
        component = component_by_ref.get(placement.component_ref)
        if component is None:
            continue
        fp = footprints.get(component.footprint_id)
        if fp is not None:
            footprint_for_placement[placement.component_ref] = fp

    # Compute the viewport in mm. Include the rails at y = -12.70 and y = 40.64 plus a
    # small margin so labels do not touch the edges.
    all_xs: list[float] = [p[0] for p in index.points]
    all_ys: list[float] = [p[1] for p in index.points]
    xmin = min(all_xs) - _MARGIN_MM
    ymin = min(all_ys) - _MARGIN_MM
    xmax = max(all_xs) + _MARGIN_MM
    ymax = max(all_ys) + _MARGIN_MM
    width_mm = xmax - xmin
    height_mm = ymax - ymin

    # `viewBox` stays in the document's native millimetre coordinate space —
    # every element below is positioned/sized directly in mm. `width`/
    # `height` are the *output* pixel dimensions; the SVG's own
    # viewBox-to-viewport mapping stretches the native-mm content to fill
    # them, so `width_scale` only needs to appear here (not on every
    # element's coordinates).
    view_min_x = xmin
    view_min_y = ymin
    view_w = width_mm
    view_h = height_mm
    output_w = width_mm * options.width_scale
    output_h = height_mm * options.width_scale

    # Label font size in millimetres — see the viewBox/width/height note
    # above; no manual width_scale multiplication needed.
    label_font_px = _LABEL_FONT_SIZE_MUL
    component_label_font_px = label_font_px
    jumper_label_font_px = label_font_px * 0.9

    parts: list[str] = []

    # --- header --------------------------------------------------------
    parts.append(
        f'<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="{_fmt(view_min_x)} {_fmt(view_min_y)} {_fmt(view_w)} {_fmt(view_h)}" '
        f'width="{_fmt(output_w)}" height="{_fmt(output_h)}" '
        f'font-family="{_FONT_FAMILY}">'
    )

    # --- (a) board outline rect ---------------------------------------
    parts.append(
        f'<rect x="{_fmt(xmin)}" y="{_fmt(ymin)}" '
        f'width="{_fmt(width_mm)}" height="{_fmt(height_mm)}" '
        f'fill="#fafafa" stroke="{_COL_BOARD_OUTLINE}" stroke-width="{_fmt(_BOARD_STROKE)}"/>'
    )

    # --- (b) tie-point group shading ----------------------------------
    if options.show_groups:
        for group in board.electrical_groups:
            if group.kind != "tie-point":
                continue
            x0, y0, x1, y1 = _group_bounds_mm(index, group.hole_ids)
            # Inset so the shaded rectangle stays inside the holes rather than crossing
            # through them; tie-point groups have 5 holes stacked vertically so y-span is
            # roughly 4 pitches.
            parts.append(
                f'<rect x="{_fmt(x0 - 1.27)}" y="{_fmt(y0 - 1.27)}" '
                f'width="{_fmt((x1 - x0) + 2.54)}" height="{_fmt((y1 - y0) + 2.54)}" '
                f'rx="0.6" ry="0.6" '
                f'fill="{_COL_GROUP_FILL}" stroke="{_COL_GROUP_STROKE}" '
                f'stroke-width="{_fmt(_GROUP_STROKE)}"/>'
            )

    # --- (c) rail background strips -----------------------------------
    # Determine the rail-line grouping (top-plus / top-minus / bottom-minus / bottom-plus)
    # by inspecting the hole ids and rail_lines metadata. We build one strip per line, not
    # per segment, so the strip covers the full 25-hole run.
    rail_lines_meta = list(board.metadata.rail_lines)
    # Stable iteration order from metadata, NOT from a set.
    seen_lines: list[str] = []
    for line in rail_lines_meta:
        if line not in seen_lines:
            seen_lines.append(line)
    # Append any line referenced by holes but not declared in metadata (defensive).
    for hole in board.holes:
        m = _RAIL_LINE_RE.match(hole.id)
        if m is None:
            continue
        line = m.group("line")
        if line not in seen_lines:
            seen_lines.append(line)

    for line in seen_lines:
        polarity = "plus" if line.endswith("-plus") else "minus"
        # Collect the rail-hole ids for this line.
        line_holes: list[str] = []
        for hole in board.holes:
            if not hole.id.startswith(f"rail-{line}-"):
                continue
            line_holes.append(hole.id)
        if not line_holes:
            continue
        x0, y0, x1, y1 = _group_bounds_mm(index, line_holes)
        strip_height = 4.0  # mm — covers the hole row with a small margin
        strip_y = (y0 + y1) / 2.0 - strip_height / 2.0
        strip_x = x0 - 1.27
        strip_w = (x1 - x0) + 2.54
        fill = _COL_RAIL_PLUS_FILL if polarity == "plus" else _COL_RAIL_MINUS_FILL
        parts.append(
            f'<rect x="{_fmt(strip_x)}" y="{_fmt(strip_y)}" '
            f'width="{_fmt(strip_w)}" height="{_fmt(strip_height)}" '
            f'rx="0.6" ry="0.6" '
            f'fill="{fill}" fill-opacity="{_COL_RAIL_BG_OPACITY}" '
            f'stroke="{fill}" stroke-opacity="0" stroke-width="{_fmt(_RAIL_BG_STROKE)}"/>'
        )

    # --- (d) holes -----------------------------------------------------
    hole_r_mm = 0.4
    parts.append('<g class="holes">')
    for hole in board.holes:
        x, y = _hole_xy(index, hole.id)
        parts.append(
            f'<circle cx="{_fmt(x)}" cy="{_fmt(y)}" r="{_fmt(hole_r_mm)}" '
            f'fill="{_COL_HOLE_FILL}" stroke="{_COL_HOLE_STROKE}" '
            f'stroke-width="{_fmt(_HOLE_STROKE)}"/>'
        )
    parts.append("</g>")

    # --- (e) component bodies -----------------------------------------
    # Decide dimming up-front so component / jumper layers stay consistent.
    highlight_net_id = options.highlight_net_id
    dim_opacity = "0.25"

    parts.append('<g class="components">')
    for placement in layout.placements:
        component = component_by_ref.get(placement.component_ref)
        footprint = footprint_for_placement.get(placement.component_ref)
        bbox = _component_placement_box_mm(placement, index, margin_mm=1.27)
        if bbox is None:
            continue
        bx0, by0, bx1, by1 = bbox
        bw = bx1 - bx0
        bh = by1 - by0

        if footprint is not None and component is not None:
            is_on_highlighted = _placement_belongs_to_highlighted_net(
                placement, component, nets, highlight_net_id
            )
        else:
            is_on_highlighted = False
        opacity_attr = (
            f' opacity="{dim_opacity}"' if highlight_net_id is not None and not is_on_highlighted else ""
        )

        parts.append(f'<g class="component" data-ref="{placement.component_ref}"{opacity_attr}>')
        parts.append(
            f'<rect x="{_fmt(bx0)}" y="{_fmt(by0)}" '
            f'width="{_fmt(bw)}" height="{_fmt(bh)}" '
            f'rx="0.5" ry="0.5" '
            f'fill="{_COL_COMPONENT_FILL}" stroke="{_COL_COMPONENT_STROKE}" '
            f'stroke-width="0.6"/>'
        )

        # Component ref label centred in the body box; value appears below in smaller text.
        cx = (bx0 + bx1) / 2.0
        cy = (by0 + by1) / 2.0
        if component is not None:
            label_text = component.ref
            parts.append(
                f'<text x="{_fmt(cx)}" y="{_fmt(cy)}" '
                f'font-size="{_fmt(component_label_font_px)}" '
                f'fill="{_COL_COMPONENT_LABEL}" text-anchor="middle" '
                f'dominant-baseline="central">{label_text}</text>'
            )
            if component.value:
                parts.append(
                    f'<text x="{_fmt(cx)}" y="{_fmt(cy + component_label_font_px * 0.9)}" '
                    f'font-size="{_fmt(component_label_font_px * 0.7)}" '
                    f'fill="{_COL_COMPONENT_LABEL}" text-anchor="middle" '
                    f'dominant-baseline="central">{component.value}</text>'
                )
        else:
            parts.append(
                f'<text x="{_fmt(cx)}" y="{_fmt(cy)}" '
                f'font-size="{_fmt(component_label_font_px)}" '
                f'fill="{_COL_COMPONENT_LABEL}" text-anchor="middle" '
                f'dominant-baseline="central">{placement.component_ref}</text>'
            )

        # Polarity marker: a small filled triangle pointing at the cathode pin.
        if footprint is not None and footprint.polarity:
            cathode_pin = _first_pin_with_role(footprint.polarity, "cathode")
            if cathode_pin is not None:
                xy = _pin_hole_xy(placement, cathode_pin, index)
                if xy is not None:
                    _append_polarity_triangle(parts, xy[0], xy[1])
            anode_pin = _first_pin_with_role(footprint.polarity, "anode")
            if anode_pin is not None and anode_pin != cathode_pin:
                # Mark the anode with a small filled square so the two ends are visually
                # distinct — minimal additional ink.
                xy = _pin_hole_xy(placement, anode_pin, index)
                if xy is not None:
                    s = _POLARITY_TRIANGLE_SIZE_MM / 2.0
                    parts.append(
                        f'<rect x="{_fmt(xy[0] - s)}" y="{_fmt(xy[1] - s)}" '
                        f'width="{_fmt(2 * s)}" height="{_fmt(2 * s)}" '
                        f'fill="{_COL_POLARITY_FILL}"/>'
                    )

        # Lock glyph for locked placements: a tiny drawn padlock near the top-left of
        # the component box.
        if placement.locked:
            _append_lock_glyph(parts, bx0 + 0.5, by0 + 0.5)

        parts.append("</g>")
    parts.append("</g>")

    # --- (f) jumpers ---------------------------------------------------
    parts.append('<g class="jumpers">')
    for idx, jumper in enumerate(layout.jumpers, start=1):
        stroke = jumper.color or _DEFAULT_JUMPER_COLOR
        stroke_w_mm = _JUMPER_STROKE_UPPER_MUL if jumper.path.layer == "upper" else _JUMPER_STROKE_LOWER_MUL
        is_on_highlighted = _jumper_belongs_to_highlighted_net(jumper, highlight_net_id)
        opacity_attr = (
            f' opacity="{dim_opacity}"' if highlight_net_id is not None and not is_on_highlighted else ""
        )

        parts.append(f'<g class="jumper" data-id="{jumper.id}"{opacity_attr}>')
        parts.append(
            f'<polyline points="{_polygon_points_str(jumper.path.points)}" '
            f'fill="none" stroke="{stroke}" stroke-width="{_fmt(stroke_w_mm)}" '
            f'stroke-linecap="round" stroke-linejoin="round"/>'
        )
        # Numbered circle at the midpoint.
        mx, my = _midpoint(jumper.path.points)
        r = _JUMPER_LABEL_R_MUL
        parts.append(
            f'<circle cx="{_fmt(mx)}" cy="{_fmt(my)}" r="{_fmt(r)}" '
            f'fill="{_COL_JUMPER_LABEL_FILL}" stroke="{_COL_JUMPER_LABEL_STROKE}" '
            f'stroke-width="0.4"/>'
        )
        parts.append(
            f'<text x="{_fmt(mx)}" y="{_fmt(my)}" '
            f'font-size="{_fmt(jumper_label_font_px)}" '
            f'fill="{_COL_JUMPER_LABEL_STROKE}" text-anchor="middle" '
            f'dominant-baseline="central">{idx}</text>'
        )
        parts.append("</g>")
    parts.append("</g>")

    # --- (g) diagnostic markers ---------------------------------------
    if diagnostics:
        parts.append('<g class="diagnostics">')
        for diag in diagnostics:
            if not diag.related_hole_ids:
                continue
            color = _DIAG_COLORS.get(diag.severity, _COL_DIAG_INFO_DEFAULT())
            radius = _DIAG_RADIUS_FOR[diag.severity]
            for hid in diag.related_hole_ids:
                try:
                    hx, hy = _hole_xy(index, hid)
                except KeyError:
                    continue
                parts.append(
                    f'<circle cx="{_fmt(hx)}" cy="{_fmt(hy)}" r="{_fmt(radius)}" '
                    f'fill="{color}" stroke="{_DIAG_STROKE}" stroke-width="0.4" '
                    f'fill-opacity="0.85"/>'
                )
        parts.append("</g>")

    # --- (h) column / row labels --------------------------------------
    if options.show_labels:
        parts.append('<g class="labels">')
        # Top edge — column numbers at the labelled columns, anchored above the board.
        for col in _LABEL_COLS:
            x = (col - 1) * 2.54
            parts.append(
                f'<text x="{_fmt(x)}" y="{_fmt(ymin + 1.5)}" '
                f'font-size="{_fmt(label_font_px)}" '
                f'fill="{_COL_LABEL_TEXT}" text-anchor="middle">{col}</text>'
            )
            parts.append(
                f'<text x="{_fmt(x)}" y="{_fmt(ymax - 1.5)}" '
                f'font-size="{_fmt(label_font_px)}" '
                f'fill="{_COL_LABEL_TEXT}" text-anchor="middle">{col}</text>'
            )
        # Side labels for the first and last rows.
        rows = board.metadata.rows
        if rows:
            first_row = rows[0]
            last_row = rows[-1]
            # Look up the y coordinate of these rows via the index lattice if available.
            first_y = _row_y_or_none(index, first_row)
            last_y = _row_y_or_none(index, last_row)
            for y_val, label in ((first_y, first_row), (last_y, last_row)):
                if y_val is None:
                    continue
                parts.append(
                    f'<text x="{_fmt(xmin + 1.5)}" y="{_fmt(y_val)}" '
                    f'font-size="{_fmt(label_font_px)}" '
                    f'fill="{_COL_LABEL_TEXT}" text-anchor="start" '
                    f'dominant-baseline="central">{label}</text>'
                )
                parts.append(
                    f'<text x="{_fmt(xmax - 1.5)}" y="{_fmt(y_val)}" '
                    f'font-size="{_fmt(label_font_px)}" '
                    f'fill="{_COL_LABEL_TEXT}" text-anchor="end" '
                    f'dominant-baseline="central">{label}</text>'
                )
        parts.append("</g>")

    # --- footer --------------------------------------------------------
    parts.append("</svg>\n")
    return "".join(parts)


# --------------------------------------------------------------------------
# Polarity / lock glyph helpers (defined after the main function so the
# reading order matches the natural top-down flow of an SVG document).
# --------------------------------------------------------------------------


def _first_pin_with_role(polarity: dict[str, str], role: str) -> str | None:
    """Return the first pin name whose polarity role equals ``role`` (stable insertion order)."""
    for pin_name, pin_role in polarity.items():
        if pin_role == role:
            return pin_name
    return None


def _append_polarity_triangle(parts: list[str], x: float, y: float) -> None:
    """Append a small filled triangle at ``(x, y)`` pointing right (cathode marker)."""
    s = _POLARITY_TRIANGLE_SIZE_MM
    points = (
        f"{_fmt(x - s / 2.0)},{_fmt(y - s / 2.0)} "
        f"{_fmt(x + s / 2.0)},{_fmt(y)} "
        f"{_fmt(x - s / 2.0)},{_fmt(y + s / 2.0)}"
    )
    parts.append(f'<polygon points="{points}" fill="{_COL_POLARITY_FILL}"/>')


def _append_lock_glyph(parts: list[str], x: float, y: float) -> None:
    """Append a tiny padlock icon at ``(x, y)`` (top-left of a locked component body)."""
    s = _LOCK_SIZE_MM
    # Body of the lock.
    parts.append(
        f'<rect x="{_fmt(x)}" y="{_fmt(y + s * 0.4)}" '
        f'width="{_fmt(s)}" height="{_fmt(s * 0.6)}" '
        f'rx="0.3" ry="0.3" fill="{_COL_LOCK_FILL}"/>'
    )
    # Shackle (a thin arc approximated by two short vertical lines + a top arc).
    parts.append(
        f'<path d="M {_fmt(x + s * 0.25)} {_fmt(y + s * 0.4)} '
        f"V {_fmt(y + s * 0.2)} "
        f"A {_fmt(s * 0.25)} {_fmt(s * 0.25)} 0 0 1 {_fmt(x + s * 0.75)} {_fmt(y + s * 0.2)} "
        f'V {_fmt(y + s * 0.4)}" '
        f'fill="none" stroke="{_COL_LOCK_FILL}" stroke-width="0.4"/>'
    )


def _row_y_or_none(index: BoardIndex, row: str) -> float | None:
    """Resolve a row letter (e.g. ``"a"``) to its y coordinate using the index."""
    try:
        row_index = index.row_index_of[row]
    except KeyError:
        return None
    # Scan the lattice for the first hole in this row.
    for (_col, ridx), hole_idx in index.lattice.items():
        if ridx == row_index:
            return index.points[hole_idx][1]
    return None


# Constants used by the diagnostic layer (kept here so the main body stays compact).
_DIAG_RADIUS_FOR: dict[str, float] = {
    "error": _DIAG_MARKER_R_ERROR,
    "warning": _DIAG_MARKER_R_WARNING,
    "info": _DIAG_MARKER_R_INFO,
}


def _COL_DIAG_INFO_DEFAULT() -> str:
    return _DIAG_COLORS["info"]
