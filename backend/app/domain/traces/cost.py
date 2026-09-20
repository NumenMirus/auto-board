"""Per-trace and aggregate cost for perfboard trace layouts."""

from __future__ import annotations

from app.domain.models import Trace, TraceLayout

__all__ = ["trace_cost", "aggregate_cost"]

DEFAULT_TRACE_WEIGHTS: dict[str, float] = {
    "lengthMm": 1.0,
    "jumperCount": 12.0,  # repurposed as trace-count cost per metre — perfboards have no jumpers
    "crossing": 40.0,
    "congestion": 30.0,
    "via": 5.0,
}


def trace_cost(trace: Trace, *, weights: dict[str, float] | None = None) -> float:
    """Linear combination of trace cost components with the given weights."""
    w = weights or DEFAULT_TRACE_WEIGHTS
    length_term = trace.estimated_length_mm * w.get("lengthMm", 1.0)
    via_term = len(trace.vias) * w.get("via", 5.0)
    return length_term + via_term


def aggregate_cost(layout: TraceLayout, *, weights: dict[str, float] | None = None) -> float:
    """Sum of trace cost across the whole layout."""
    return sum(trace_cost(t, weights=weights) for t in layout.traces)
