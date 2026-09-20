/**
 * Hand-written TypeScript mirrors of the backend Pydantic wire models
 * (`backend/app/domain/models.py`).
 *
 * Wire JSON is camelCase because every `WireModel` uses
 * `alias_generator=to_camel` and is dumped with `by_alias=True`. Python
 * attribute names stay snake_case; this file mirrors the *wire* names so
 * `JSON.parse(...)` lines up without a transformer.
 *
 * Keep these in sync with the backend; the contract test
 * `tests/test_fixtures.py::test_roundtrip` on the backend and the
 * `frontend/src/lib/types.test.ts` shape checks (added separately) catch
 * divergence.
 */

// ---------------------------------------------------------------------------
// 4.1 Coordinates
// ---------------------------------------------------------------------------

export interface Point {
  x: number;
  y: number;
}

export interface GridPoint {
  col: number;
  row: string;
}

// ---------------------------------------------------------------------------
// 4.2 Board physical and electrical model
// ---------------------------------------------------------------------------

export type ElectricalGroupKind = 'tie-point' | 'rail' | 'custom';

export interface ElectricalGroup {
  id: string;
  holeIds: string[];
  kind: ElectricalGroupKind;
}

export type BoardZoneKind = 'main' | 'rail' | 'center-gap' | 'reserved';

export interface BoardZone {
  id: string;
  kind: BoardZoneKind;
  polygon: Point[];
}

export interface BoardMetadata {
  columns: number;
  railConfiguration: string;
  rows: string[];
  railLines: string[];
}

export interface Hole {
  id: string;
  point: Point;
  grid: GridPoint;
  enabled: boolean;
  label: string;
}

export interface BreadboardModel {
  id: string;
  version: 1;
  pitchMm: number;
  holes: Hole[];
  electricalGroups: ElectricalGroup[];
  zones: BoardZone[];
  metadata: BoardMetadata;
}

// ---------------------------------------------------------------------------
// 4.7 Perfboard (soldered through-hole) — sibling of the breadboard model
// ---------------------------------------------------------------------------

export interface PerfboardMetadata {
  rows: number;
  cols: number;
  layers: number;
}

export interface PerfboardModel {
  id: string;
  version: 1;
  pitchMm: number;
  rows: number;
  cols: number;
  layers: number;
  holes: Hole[];
  zones: BoardZone[];
  metadata: PerfboardMetadata;
}

/** A board is either a breadboard or a perfboard; the discriminator lives
 * on the `kind` field returned by `/board-models` (not on the model itself,
 * since the two wire shapes differ structurally). */
export type AnyBoardModel = BreadboardModel | PerfboardModel;
export type BoardKind = 'breadboard' | 'perfboard';

// ---------------------------------------------------------------------------
// 4.3 Netlist
// ---------------------------------------------------------------------------

export type NetClass =
  | 'ground'
  | 'power'
  | 'high-current'
  | 'analog-sensitive'
  | 'clock'
  | 'switching'
  | 'digital'
  | 'low-priority'
  | 'custom';

export interface PinRef {
  componentRef: string;
  pin: string;
}

export interface NetConstraintMaxLength {
  type: 'max-length-mm';
  value: number;
}

export interface NetConstraintPreferRail {
  type: 'prefer-rail';
}

export interface NetConstraintAvoidZone {
  type: 'avoid-zone';
  zoneId: string;
}

export interface NetConstraintMustBeLocal {
  type: 'must-be-local';
  componentRef: string;
}

export interface NetConstraintManual {
  type: 'manual';
  note: string;
}

export type NetConstraint =
  | NetConstraintMaxLength
  | NetConstraintPreferRail
  | NetConstraintAvoidZone
  | NetConstraintMustBeLocal
  | NetConstraintManual;

export interface Net {
  id: string;
  name: string;
  pins: PinRef[];
  netClass: NetClass;
  priority: number;
  constraints: NetConstraint[];
}

// ---------------------------------------------------------------------------
// 4.4 Components and footprints
// ---------------------------------------------------------------------------

export interface Component {
  ref: string;
  value: string | null;
  footprintId: string;
  pins: string[];
  locked: boolean;
  tags: string[];
}

export type Orientation = 0 | 90 | 180 | 270;

export interface RelativeHole {
  /** Lattice-step offset (NOT millimetres). */
  x: number;
  y: number;
}

export interface PlacementRuleStraddleCenterGap {
  type: 'must-straddle-center-gap';
}

export interface PlacementRuleMainArea {
  type: 'must-be-on-main-area';
}

export interface PlacementRuleBoardEdge {
  type: 'must-be-on-board-edge';
}

export interface PlacementRuleAllowedZones {
  type: 'allowed-zones';
  zoneIds: string[];
}

export interface PlacementRuleMinClearance {
  type: 'min-clearance-holes';
  value: number;
}

export type PlacementRule =
  | PlacementRuleStraddleCenterGap
  | PlacementRuleMainArea
  | PlacementRuleBoardEdge
  | PlacementRuleAllowedZones
  | PlacementRuleMinClearance;

export interface FlexibleLeadSpan {
  minHoles: number;
  maxHoles: number;
  preferredHoles: number;
  orientations: Array<'horizontal' | 'vertical'>;
}

export interface FootprintGeometry {
  pinsPerSide: number | null;
  nominalBodyWidthMm: number | null;
  nominalBodyLengthMm: number | null;
  flexibleLeadSpan: FlexibleLeadSpan | null;
}

export interface BreadboardFootprint {
  id: string;
  displayName: string;
  pinOffsets: Record<string, RelativeHole>;
  bodyCells: RelativeHole[];
  supportedOrientations: Orientation[];
  placementRules: PlacementRule[];
  geometry: FootprintGeometry;
  internalConnections: string[][];
  polarity: Record<string, string>;
}

/** Alias — the backend's `BreadboardFootprint` and `ThroughHoleFootprint`
 * are the same Pydantic class (perfboard reuses the breadboard footprint
 * shape verbatim, minus the rail/center-gap placement rules at runtime). */
export type ThroughHoleFootprint = BreadboardFootprint;

// ---------------------------------------------------------------------------
// 4.5 Placement and jumpers
// ---------------------------------------------------------------------------

export interface ComponentPlacement {
  componentRef: string;
  anchorHoleId: string;
  orientation: Orientation;
  span: number | null;
  pinHoles: Record<string, string>;
  occupiedHoleIds: string[];
  locked: boolean;
}

export type JumperLayer = 'lower' | 'upper';

export interface JumperPath {
  points: Point[];
  layer: JumperLayer;
}

export interface Jumper {
  id: string;
  netId: string;
  startHoleId: string;
  endHoleId: string;
  path: JumperPath;
  color: string | null;
  estimatedLengthMm: number;
  locked: boolean;
}

export interface ManualLink {
  holeA: string;
  holeB: string;
  netId: string | null;
}

export interface Layout {
  version: 1;
  boardId: string;
  placements: ComponentPlacement[];
  jumpers: Jumper[];
  manualElectricalLinks: ManualLink[];
}

// ---------------------------------------------------------------------------
// 4.8 Perfboard trace routing — copper traces and vias
// ---------------------------------------------------------------------------

export type CopperLayer = 'top' | 'bottom';

export interface TraceSegment {
  start: Point;
  end: Point;
  layer: CopperLayer;
  widthMm: number;
}

export interface Via {
  point: Point;
  diameterMm: number;
  drillMm: number;
}

/** A soldered copper trace on a perfboard. Distinct from `SolverTrace`
 * (the solver's placement/routing decision log) below. */
export interface Trace {
  id: string;
  netId: string;
  segments: TraceSegment[];
  vias: Via[];
  estimatedLengthMm: number;
  widthMm: number;
  locked: boolean;
}

/** Perfboard layout: placements + copper traces + vias. Sibling of `Layout`
 * (which carries jumpers instead of traces for the breadboard case). */
export interface TraceLayout {
  version: 1;
  boardId: string;
  placements: ComponentPlacement[];
  traces: Trace[];
  vias: Via[];
}

export type AnyLayout = Layout | TraceLayout;

// ---------------------------------------------------------------------------
// 8.3 Diagnostics
// ---------------------------------------------------------------------------

export type DiagnosticSeverity = 'error' | 'warning' | 'info';

export interface Diagnostic {
  id: string;
  severity: DiagnosticSeverity;
  code: string;
  message: string;
  relatedHoleIds: string[];
  relatedComponentRefs: string[];
  relatedNetIds: string[];
  suggestion: string | null;
}

// ---------------------------------------------------------------------------
// 14 Score
// ---------------------------------------------------------------------------

export interface LayoutScore {
  total: number;
  placementCost: number;
  routingCost: number;
  componentsPlaced: number;
  componentsTotal: number;
  netsCompleted: number;
  netsTotal: number;
  jumperCount: number;
  totalJumperLengthMm: number;
  crossings: number;
  errorCount: number;
  warningCount: number;
}

// ---------------------------------------------------------------------------
// 10 Project document
// ---------------------------------------------------------------------------

export interface BoardRef {
  modelId: string;
}

export interface ProjectSettings {
  seed: number;
  solverPreset: string;
  placementWeights: Record<string, number>;
  routingWeights: Record<string, number>;
  allowCriticalNetClasses: boolean;
}

export interface FootprintOverride {
  componentRef: string;
  footprintId: string;
  pinMap: Record<string, string> | null;
}

export interface ProjectDocument {
  format: 'autobreadboard-project';
  version: 1;
  name: string;
  board: BoardRef;
  components: Component[];
  nets: Net[];
  layout: Layout;
  settings: ProjectSettings;
  footprintOverrides: FootprintOverride[];
}

// ---------------------------------------------------------------------------
// 12 Solver trace
// ---------------------------------------------------------------------------

export interface PoseChoice {
  componentRef: string;
  anchorHoleId: string;
  orientation: Orientation;
  span: number | null;
  cost: number;
}

export interface TraceRejection {
  componentRef: string;
  reason: string;
  detail: string | null;
}

export interface TraceRipup {
  netId: string;
  removedJumperIds: string[];
  reason: string;
}

export interface SolverTrace {
  seed: number;
  placementOrder: string[];
  poseChoices: PoseChoice[];
  rejections: TraceRejection[];
  failedNets: string[];
  ripups: TraceRipup[];
  iterationScores: number[];
  phaseTimingsMs: Record<string, number>;
}

// ---------------------------------------------------------------------------
// API envelope helpers
// ---------------------------------------------------------------------------

export interface ProjectListResponse {
  items: Array<{
    id: string;
    name: string;
    boardModelId: string;
    draftVersion: number;
    createdAt: string;
    updatedAt: string;
  }>;
  total: number;
}