"""Aggregate :class:`LayoutScore` for a perfboard trace layout.

Reuses the same :class:`LayoutScore` shape the breadboard produces so the
frontend and API don't need to special-case the two board families.
"""

from __future__ import annotations

from app.domain.models import ComponentPlacement, LayoutScore, TraceLayout

__all__ = ["score_layout"]


def score_layout(
    *,
    placements: list[ComponentPlacement],
    components_placed: int,
    components_total: int,
    layout: TraceLayout,
    diagnostics: list | None = None,
) -> LayoutScore:
    diagnostics = diagnostics or []
    error_count = sum(1 for d in diagnostics if d.severity == "error")
    warning_count = sum(1 for d in diagnostics if d.severity == "warning")
    total_length = sum(t.estimated_length_mm for t in layout.traces)
    trace_count = len(layout.traces)
    # Treat each trace as one "jumper" for downstream display consistency.
    return LayoutScore(
        total=total_length + 5.0 * sum(len(t.vias) for t in layout.traces),
        placement_cost=0.0,  # placement cost is reported by the breadboard pipeline, not the trace pipeline
        routing_cost=total_length,
        components_placed=components_placed,
        components_total=components_total,
        # "nets completed" means traces + unrouted are accounted for.
        nets_completed=trace_count,
        nets_total=trace_count + sum(1 for d in diagnostics if d.code == "UNROUTED_TERMINAL"),
        jumper_count=trace_count,
        total_jumper_length_mm=round(total_length, 2),
        crossings=0,  # not tracked yet at score time (no A*-aware crossing count)
        error_count=error_count,
        warning_count=warning_count,
    )
