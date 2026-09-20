"""Wire-format domain models for AutoBreadboard.

These Pydantic models are the single source of truth for the JSON contract shared by the
API, the worker, the solver core, and (mirrored by hand) the frontend TypeScript types.

This module MUST NOT import Sanic, SQLAlchemy, redis, boto3, or ``app.settings``. It is
covered by ``tests/test_architecture.py``, which enforces domain purity for the whole
``app.domain`` package.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

__all__ = [
    "DEFAULT_PLACEMENT_WEIGHTS",
    "DEFAULT_ROUTING_WEIGHTS",
    "BoardMetadata",
    "BoardRef",
    "BoardZone",
    "BreadboardFootprint",
    "BreadboardModel",
    "Component",
    "ComponentPlacement",
    "CopperLayer",
    "Diagnostic",
    "DiagnosticSeverity",
    "ElectricalGroup",
    "FlexibleLeadSpan",
    "FootprintGeometry",
    "FootprintOverride",
    "GridPoint",
    "Hole",
    "Jumper",
    "JumperPath",
    "Layout",
    "LayoutScore",
    "ManualLink",
    "Net",
    "NetClass",
    "NetConstraint",
    "NetConstraintAvoidZone",
    "NetConstraintManual",
    "NetConstraintMaxLength",
    "NetConstraintMustBeLocal",
    "NetConstraintPreferRail",
    "PerfboardMetadata",
    "PerfboardModel",
    "PinRef",
    "PlacementRule",
    "PlacementRuleAllowedZones",
    "PlacementRuleBoardEdge",
    "PlacementRuleMainArea",
    "PlacementRuleMinClearance",
    "PlacementRuleStraddleCenterGap",
    "Point",
    "RelativeHole",
    "SolveRequest",
    "SolveRequestNetlist",
    "SolveResult",
    "SolverOptions",
    "SolverTrace",
    "ThroughHoleFootprint",
    "Trace",
    "TraceLayout",
    "TraceSegment",
    "PlacementResult",
    "PoseChoice",
    "ProjectDocument",
    "ProjectSettings",
    "RouteRequest",
    "RouteResult",
    "ScoreRequest",
    "TraceRejection",
    "TraceRipup",
    "ValidateRequest",
    "ValidationResult",
    "Via",
]


class WireModel(BaseModel):
    """Base for every model that crosses the wire or is persisted as JSONB."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
    )


# --------------------------------------------------------------------------
# 4.1 Coordinate types
# --------------------------------------------------------------------------


class Point(WireModel):
    """Absolute board coordinate in millimetres."""

    x: float
    y: float


class GridPoint(WireModel):
    col: int
    row: str


# --------------------------------------------------------------------------
# 4.2 Board physical and electrical model
# --------------------------------------------------------------------------


class Hole(WireModel):
    id: str
    point: Point
    grid: GridPoint
    enabled: bool
    label: str


class ElectricalGroup(WireModel):
    id: str
    hole_ids: list[str]
    kind: Literal["tie-point", "rail", "custom"]


class BoardZone(WireModel):
    id: str
    kind: Literal["main", "rail", "center-gap", "reserved"]
    polygon: list[Point]


class BoardMetadata(WireModel):
    columns: int
    rail_configuration: str
    rows: list[str]
    rail_lines: list[str]


class BreadboardModel(WireModel):
    id: str
    version: Literal[1]
    pitch_mm: float
    holes: list[Hole]
    electrical_groups: list[ElectricalGroup]
    zones: list[BoardZone]
    metadata: BoardMetadata


# --------------------------------------------------------------------------
# 4.3 Netlist
# --------------------------------------------------------------------------

NetClass = Literal[
    "ground",
    "power",
    "high-current",
    "analog-sensitive",
    "clock",
    "switching",
    "digital",
    "low-priority",
    "custom",
]


class PinRef(WireModel):
    component_ref: str
    pin: str


class NetConstraintMaxLength(WireModel):
    type: Literal["max-length-mm"] = "max-length-mm"
    value: float


class NetConstraintPreferRail(WireModel):
    type: Literal["prefer-rail"] = "prefer-rail"


class NetConstraintAvoidZone(WireModel):
    type: Literal["avoid-zone"] = "avoid-zone"
    zone_id: str


class NetConstraintMustBeLocal(WireModel):
    type: Literal["must-be-local"] = "must-be-local"
    component_ref: str


class NetConstraintManual(WireModel):
    type: Literal["manual"] = "manual"
    note: str


NetConstraint = Annotated[
    NetConstraintMaxLength
    | NetConstraintPreferRail
    | NetConstraintAvoidZone
    | NetConstraintMustBeLocal
    | NetConstraintManual,
    Field(discriminator="type"),
]


class Net(WireModel):
    id: str
    name: str
    pins: list[PinRef]
    net_class: NetClass
    priority: int
    constraints: list[NetConstraint] = Field(default_factory=list)


# --------------------------------------------------------------------------
# 4.4 Components and footprints
# --------------------------------------------------------------------------


class Component(WireModel):
    ref: str
    value: str | None = None
    footprint_id: str
    pins: list[str]
    locked: bool = False
    tags: list[str] = Field(default_factory=list)


Orientation = Literal[0, 90, 180, 270]


class RelativeHole(WireModel):
    """Lattice-step offset, never millimetres."""

    x: int
    y: int


class PlacementRuleStraddleCenterGap(WireModel):
    type: Literal["must-straddle-center-gap"] = "must-straddle-center-gap"


class PlacementRuleMainArea(WireModel):
    type: Literal["must-be-on-main-area"] = "must-be-on-main-area"


class PlacementRuleBoardEdge(WireModel):
    type: Literal["must-be-on-board-edge"] = "must-be-on-board-edge"


class PlacementRuleAllowedZones(WireModel):
    type: Literal["allowed-zones"] = "allowed-zones"
    zone_ids: list[str]


class PlacementRuleMinClearance(WireModel):
    type: Literal["min-clearance-holes"] = "min-clearance-holes"
    value: int


PlacementRule = Annotated[
    PlacementRuleStraddleCenterGap
    | PlacementRuleMainArea
    | PlacementRuleBoardEdge
    | PlacementRuleAllowedZones
    | PlacementRuleMinClearance,
    Field(discriminator="type"),
]


class FlexibleLeadSpan(WireModel):
    min_holes: int
    max_holes: int
    preferred_holes: int
    orientations: list[Literal["horizontal", "vertical"]]


class FootprintGeometry(WireModel):
    pins_per_side: int | None = None
    nominal_body_width_mm: float | None = None
    nominal_body_length_mm: float | None = None
    flexible_lead_span: FlexibleLeadSpan | None = None


class BreadboardFootprint(WireModel):
    id: str
    display_name: str
    pin_offsets: dict[str, RelativeHole]
    body_cells: list[RelativeHole]
    supported_orientations: list[Orientation]
    placement_rules: list[PlacementRule]
    geometry: FootprintGeometry
    internal_connections: list[list[str]] = Field(default_factory=list)
    polarity: dict[str, str] = Field(default_factory=dict)


# --------------------------------------------------------------------------
# 4.5 Placement and jumpers
# --------------------------------------------------------------------------


class ComponentPlacement(WireModel):
    component_ref: str
    anchor_hole_id: str
    orientation: Orientation
    span: int | None = None
    pin_holes: dict[str, str]
    occupied_hole_ids: list[str]
    locked: bool = False


class JumperPath(WireModel):
    points: list[Point]
    layer: Literal["lower", "upper"]


class Jumper(WireModel):
    id: str
    net_id: str
    start_hole_id: str
    end_hole_id: str
    path: JumperPath
    color: str | None = None
    estimated_length_mm: float
    locked: bool = False


class ManualLink(WireModel):
    hole_a: str
    hole_b: str
    net_id: str | None = None


class Layout(WireModel):
    version: Literal[1]
    board_id: str
    placements: list[ComponentPlacement]
    jumpers: list[Jumper]
    manual_electrical_links: list[ManualLink] = Field(default_factory=list)


# --------------------------------------------------------------------------
# 8.3 Diagnostics
# --------------------------------------------------------------------------

DiagnosticSeverity = Literal["error", "warning", "info"]


class Diagnostic(WireModel):
    id: str
    severity: DiagnosticSeverity
    code: str
    message: str
    related_hole_ids: list[str] = Field(default_factory=list)
    related_component_refs: list[str] = Field(default_factory=list)
    related_net_ids: list[str] = Field(default_factory=list)
    suggestion: str | None = None


# --------------------------------------------------------------------------
# 14 Score
# --------------------------------------------------------------------------


class LayoutScore(WireModel):
    total: float
    placement_cost: float
    routing_cost: float
    components_placed: int
    components_total: int
    nets_completed: int
    nets_total: int
    jumper_count: int
    total_jumper_length_mm: float
    crossings: int
    error_count: int
    warning_count: int


# --------------------------------------------------------------------------
# 6.3 / 7.5 default weight presets
# --------------------------------------------------------------------------

DEFAULT_PLACEMENT_WEIGHTS: dict[str, float] = {
    "weightedDistance": 1,
    "congestion": 15,
    "mechanical": 10,
    "criticalRule": 500,
    "accessibility": 25,
    "overlap": 1_000_000,
    "cluster": 8,
}

DEFAULT_ROUTING_WEIGHTS: dict[str, float] = {
    "lengthMm": 1,
    "jumperCount": 12,
    "crossing": 40,
    "congestion": 30,
    "avoidZone": 100,
    "criticalViolation": 500,
    "unroutedTerminal": 10_000,
}


class SolverOptions(WireModel):
    seed: int = 12345
    max_placement_restarts: int = 4
    max_local_search_iterations: int = 2000
    max_ripup_iterations: int = 20
    placement_weights: dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_PLACEMENT_WEIGHTS))
    routing_weights: dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_ROUTING_WEIGHTS))
    allow_critical_net_classes: bool = False
    timeout_seconds: int | None = None
    preset: Literal["fast", "balanced", "quality"] = "balanced"


# --------------------------------------------------------------------------
# 12 Solver trace / API
# --------------------------------------------------------------------------


class PoseChoice(WireModel):
    component_ref: str
    anchor_hole_id: str
    orientation: Orientation
    span: int | None = None
    cost: float


class TraceRejection(WireModel):
    component_ref: str
    reason: str
    detail: str | None = None


class TraceRipup(WireModel):
    net_id: str
    removed_jumper_ids: list[str]
    reason: str


class SolverTrace(WireModel):
    seed: int
    placement_order: list[str]
    pose_choices: list[PoseChoice] = Field(default_factory=list)
    rejections: list[TraceRejection] = Field(default_factory=list)
    failed_nets: list[str] = Field(default_factory=list)
    ripups: list[TraceRipup] = Field(default_factory=list)
    iteration_scores: list[float] = Field(default_factory=list)
    phase_timings_ms: dict[str, float] = Field(default_factory=dict)


class SolveRequestNetlist(WireModel):
    components: list[Component]
    nets: list[Net]


class SolveRequest(WireModel):
    board: BreadboardModel
    netlist: SolveRequestNetlist
    initial_layout: Layout | None = None
    options: SolverOptions


class SolveResult(WireModel):
    layout: Layout
    score: LayoutScore
    diagnostics: list[Diagnostic]
    trace: SolverTrace | None = None


class PlacementResult(WireModel):
    placements: list[ComponentPlacement]
    unplaced: list[str]
    trace: SolverTrace
    cost: float


class RouteRequest(WireModel):
    board: BreadboardModel
    netlist: SolveRequestNetlist
    layout: Layout
    options: SolverOptions


class RouteResult(WireModel):
    jumpers: list[Jumper]
    unrouted_nets: list[str]
    trace: SolverTrace
    cost: float


class ValidateRequest(WireModel):
    board: BreadboardModel
    netlist: SolveRequestNetlist
    layout: Layout
    options: SolverOptions


class ValidationResult(WireModel):
    diagnostics: list[Diagnostic]
    score: LayoutScore


class ScoreRequest(WireModel):
    board: BreadboardModel
    netlist: SolveRequestNetlist
    layout: Layout
    diagnostics: list[Diagnostic]
    options: SolverOptions


# --------------------------------------------------------------------------
# 10 Project document
# --------------------------------------------------------------------------


class BoardRef(WireModel):
    model_id: str


class ProjectSettings(WireModel):
    seed: int
    solver_preset: str
    placement_weights: dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_PLACEMENT_WEIGHTS))
    routing_weights: dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_ROUTING_WEIGHTS))
    allow_critical_net_classes: bool = False


class FootprintOverride(WireModel):
    component_ref: str
    footprint_id: str
    pin_map: dict[str, str] | None = None


class ProjectDocument(WireModel):
    format: Literal["autobreadboard-project"] = "autobreadboard-project"
    version: Literal[1] = 1
    name: str
    board: BoardRef
    components: list[Component]
    nets: list[Net]
    layout: Layout
    settings: ProjectSettings
    footprint_overrides: list[FootprintOverride] = Field(default_factory=list)


# --------------------------------------------------------------------------
# 4.7 Perfboard (soldered through-hole) — sibling of the breadboard model
# --------------------------------------------------------------------------


class PerfboardMetadata(WireModel):
    rows: int
    cols: int
    layers: int = Field(ge=1, le=2)


class PerfboardModel(WireModel):
    """A uniform grid of isolated holes (stripboard / protoboard).

    All holes are electrically isolated by default; copper traces (added at
    routing time) join them. There are no rails and no center gap; the only
    zone is the rectangular board area. Pin offsets and body cells use the
    same ``(x, y)`` integer-lattice convention as :class:`BreadboardFootprint`.
    """

    id: str
    version: Literal[1]
    pitch_mm: float = 2.54
    rows: int
    cols: int
    layers: int = Field(ge=1, le=2)
    holes: list[Hole]
    zones: list[BoardZone] = Field(default_factory=list)
    metadata: PerfboardMetadata


class ThroughHoleFootprint(WireModel):
    """Through-hole component footprint usable on both breadboard and perfboard.

    For perfboard use the placement-rule set is intentionally smaller than
    :class:`BreadboardFootprint`: no rail rules and no center-gap straddle.
    Reuses the same ``pin_offsets`` / ``body_cells`` / ``internal_connections``
    conventions so a footprint can be shared across both board families.
    """

    id: str
    display_name: str
    pin_offsets: dict[str, RelativeHole]
    body_cells: list[RelativeHole]
    supported_orientations: list[Orientation]
    placement_rules: list[PlacementRule]
    geometry: FootprintGeometry
    internal_connections: list[list[str]] = Field(default_factory=list)
    polarity: dict[str, str] = Field(default_factory=dict)


# Back-compat alias — every existing breadboard-side consumer (placement,
# routing, validation, frontend) imports ``BreadboardFootprint``. The two
# types are structurally identical today; the alias keeps that import path
# working without rewriting the breadboard solver code.
BreadboardFootprint = ThroughHoleFootprint


# --------------------------------------------------------------------------
# 4.8 Perfboard trace routing — copper traces and vias
# --------------------------------------------------------------------------


CopperLayer = Literal["top", "bottom"]


class TraceSegment(WireModel):
    """One straight segment of a copper trace on a single layer.

    ``start`` and ``end`` are board-absolute millimetres. A trace is a list
    of segments emitted in order; bends happen where one segment ends and
    the next begins.
    """

    start: Point
    end: Point
    layer: CopperLayer
    width_mm: float = 0.4


class Via(WireModel):
    """Plated through-hole connecting the top and bottom copper layers.

    Only meaningful when the board is double-sided; single-sided boards
    must never carry a via.
    """

    point: Point
    diameter_mm: float = 0.8
    drill_mm: float = 0.5


class Trace(WireModel):
    id: str
    net_id: str
    segments: list[TraceSegment]
    vias: list[Via] = Field(default_factory=list)
    estimated_length_mm: float
    width_mm: float = 0.4
    locked: bool = False


class TraceLayout(WireModel):
    """Perfboard layout: placements + copper traces + vias.

    Reuses the breadboard :class:`ComponentPlacement` (the body cells and
    pin-hole map are identical on a perfboard). Jumpers and manual electrical
    links do not apply to perfboards.
    """

    version: Literal[1] = 1
    board_id: str
    placements: list[ComponentPlacement]
    traces: list[Trace] = Field(default_factory=list)
    vias: list[Via] = Field(default_factory=list)

