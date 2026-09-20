"""Assembly instructions for perfboard trace layouts.

Mirrors :func:`app.domain.instructions.build_instructions` but tailored for
soldered perfboards: the steps are ordered for hand assembly (anchor
components first, then short traces, then long traces, then vias last) and
the language matches the spec's Italian colour-name conventions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.models import (
    Component,
    Net,
    PerfboardModel,
    Trace,
    TraceLayout,
)

__all__ = ["AssemblyInstructions", "build_instructions"]


_COLOR_NAMES: dict[str, str] = {
    "#1f77b4": "blu",
    "#ff7f0e": "arancione",
    "#2ca02c": "verde",
    "#d62728": "rosso",
    "#9467bd": "viola",
    "#8c564b": "marrone",
    "#e377c2": "rosa",
    "#bcbd22": "giallo",
    "#17becf": "ciano",
    "#cc4125": "rosso scuro",
    "#1a1a1a": "nero",
    "#d92b2b": "rosso",
    "#cccccc": "grigio chiaro",
}


@dataclass(slots=True)
class AssemblyInstructions:
    title: str
    steps: list[str] = field(default_factory=list)
    bom_lines: list[str] = field(default_factory=list)


def _color_name(hex_color: str) -> str:
    return _COLOR_NAMES.get(hex_color.lower(), hex_color)


def _polyline_length(trace: Trace) -> float:
    total = 0.0
    for seg in trace.segments:
        dx = seg.end.x - seg.start.x
        dy = seg.end.y - seg.start.y
        total += (dx * dx + dy * dy) ** 0.5
    return total


def build_instructions(
    board: PerfboardModel,
    components: list[Component],
    nets: list[Net],
    layout: TraceLayout,
) -> AssemblyInstructions:
    """Build a human-readable assembly guide for ``layout``."""
    title = f"AutoBoard — guida al montaggio ({board.metadata.cols}x{board.metadata.rows})"
    steps: list[str] = []
    bom: list[str] = []

    comp_by_ref = {c.ref: c for c in components}
    placements_sorted = sorted(layout.placements, key=lambda p: p.component_ref)

    # BOM grouped by (value, footprint_id)
    grouped: dict[tuple[str | None, str], list[str]] = {}
    for placement in placements_sorted:
        comp = comp_by_ref.get(placement.component_ref)
        if comp is None:
            continue
        key = (comp.value, comp.footprint_id)
        grouped.setdefault(key, []).append(comp.ref)
    for (value, fp_id), refs in sorted(grouped.items()):
        refs_str = ", ".join(refs)
        bom.append(f"{value or '?'}  {fp_id}  x{len(refs)}  ({refs_str})")

    # Component placement steps
    for placement in placements_sorted:
        comp = comp_by_ref.get(placement.component_ref)
        if comp is None:
            continue
        steps.append(
            f"Inserisci {placement.component_ref} ({comp.value or '?'} — {comp.footprint_id}) "
            f"al foro {placement.anchor_hole_id}, orientamento {placement.orientation}°."
        )

    # Trace routing steps — group by net, order short → long
    net_id_to_name = {n.id: n.name for n in nets}
    traces_with_cost: list[tuple[float, Trace]] = [(_polyline_length(t), t) for t in layout.traces]
    traces_with_cost.sort(key=lambda x: x[0])
    for i, (length, trace) in enumerate(traces_with_cost, start=1):
        net_name = net_id_to_name.get(trace.net_id, trace.net_id)
        layers = sorted({seg.layer for seg in trace.segments})
        layer_label = " + ".join(layers)
        steps.append(
            f"Traccia {i} — Net: {net_name} — lunghezza {length:.1f} mm — layer {layer_label}"
            + (f" — {len(trace.vias)} via" if trace.vias else "")
        )

    # Vias last
    via_count = sum(len(t.vias) for t in layout.traces)
    if via_count:
        steps.append(f"Salda {via_count} via placcati (layer top + bottom).")

    steps.append("Verifica continuità e polarità prima di alimentare il circuito.")
    steps.append("AutoBoard non garantisce che un layout sia elettricamente corretto.")

    return AssemblyInstructions(title=title, steps=steps, bom_lines=bom)
