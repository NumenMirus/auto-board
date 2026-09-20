# Project JSON format

The wire format is **camelCase JSON**, validated by Pydantic models in
`backend/app/domain/models.py`. This document is a hand-maintained mirror
of those models, written for humans loading a project file into the
AutoBreadboard editor. The canonical schema is the code; treat this
document as a tour.

## Top-level `ProjectDocument`

```jsonc
{
  "format":   "autobreadboard-project",
  "version":  1,
  "name":     "string",            // project display name
  "board":    { "modelId": "..." }, // see Boards below
  "components": [ ... ],            // required
  "nets":       [ ... ],            // required, can be empty
  "layout":     { ... },            // initial layout; usually empty for fresh projects
  "settings":   { ... },            // solver defaults; see Settings below
  "footprintOverrides": []          // per-project pin remapping
}
```

`format` and `version` are mandatory and **must** be exactly
`"autobreadboard-project"` and `1`. The API rejects anything else.

## Boards

The `board.modelId` field selects between two board families. They share the
same wire format (`ProjectDocument`), but the solver pipeline is different.

### Breadboards (jumpers)

```json
{ "modelId": "half-400-standard-split-rails" }
{ "modelId": "half-400-standard-continuous-rails" }
```

Half-size 400-tie-point board. Has power rails, a centre gap, and tie-point
groups. Connections are made with insulated jumper wires. Solver operations:
`place`, `route`, `solve`, `optimize`, `validate`, `export`. See the rest of
this document for the breadboard pipeline.

### Perfboards / stripboards (soldered copper traces)

```json
{ "modelId": "strip-20x30-single" }
{ "modelId": "strip-20x30-double" }
{ "modelId": "strip-15x20-double" }
```

A perfboard is a uniform grid of isolated through-holes on one or two copper
layers — **no power rails, no centre gap, no electrical groups**. Every hole
is isolated by default; connections are made by routing soldered copper
traces (and vias for two-layer boards). Hole ids are zero-padded
`"<row>-<col>"` (e.g. `1-1`, `10-3`, `12-15`).

Perfboard layouts use `TraceLayout` instead of `Layout`:

```jsonc
{
  "version": 1,
  "boardId": "strip-20x30-double",
  "componentPlacements": [ /* same shape as breadboard placements */ ],
  "traces": [
    { "id": "T1", "netId": "gnd", "layer": "bottom",
      "segments": [ { "from": "1-1", "to": "1-5", "widthMm": 0.8 } ] }
  ],
  "vias": [
    { "id": "V1", "holeId": "1-3", "netId": "gnd", "diameterMm": 0.8 }
  ]
}
```

Solver operations on a perfboard: **`trace-route`** (route only) and
**`trace-solve`** (place + route). The breadboard operations (`solve`,
`optimize`, …) are rejected with `operation '…' is not valid for perfboard
…`. There is no jumper drawing on perfboards.

For a list of every available board:

```bash
curl -s http://localhost:8000/api/v1/board-models | jq '.[] | {id, kind}'
```

The response's `kind` field is `"breadboard"` or `"perfboard"`.

## Components

```jsonc
{
  "ref":         "R1",                  // unique, matches ^[A-Za-z][A-Za-z0-9_]*$
  "value":       "330",                 // optional, free string ("10k", "100nF", "BC547")
  "footprintId": "AXIAL-R",             // see docs/FOOTPRINTS.md
  "pins":        ["1", "2"],            // pin names that participate in nets
  "locked":      false,                 // true → solver never moves this part
  "tags":        ["bypass", "decoupling"]
}
```

Rules:

- `ref` must be unique within the project.
- `footprintId` must exist in the registry (returns `UNKNOWN_FOOTPRINT` otherwise).
- `pins` must be a subset of the footprint's pin set.
- `locked` components are placed by hand; the solver preserves their position
  and pin-hole mapping exactly.

## Nets

```jsonc
{
  "id":        "drive",                  // unique, stable id
  "name":      "LED_DRIVE",              // human-readable
  "pins": [
    { "componentRef": "R1",  "pin": "2" },
    { "componentRef": "LED1","pin": "1" }
  ],
  "netClass":  "digital",                // see Net classes below
  "priority":  5,                        // higher = routed first
  "constraints": []                      // optional, see Constraints below
}
```

A pin may appear in **at most one** net (`PIN_IN_MULTIPLE_NETS` otherwise). A
net with fewer than two pins raises `NET_SINGLE_PIN` (warning, not error).

### Net classes

| Class              | Solver behaviour |
|--------------------|------------------|
| `ground`           | Strong rail preference; coloured black. |
| `power`            | Strong rail preference; coloured red. |
| `high-current`     | Refused unless `allowCriticalNetClasses=true`; raises `HIGH_CURRENT_ON_RAIL` if it reaches a rail. |
| `analog-sensitive` | Refused unless `allowCriticalNetClasses=true`. |
| `clock`            | Refused unless `allowCriticalNetClasses=true`. |
| `switching`        | Refused unless `allowCriticalNetClasses=true`. |
| `digital`          | Default. |
| `low-priority`     | Routed last; may be left partially routed under tight fit. |
| `custom`           | Routed by `priority` only; no class-specific behaviour. |

### Constraints

Discriminated union on `type`. Each entry is one of:

```jsonc
{ "type": "max-length-mm",  "value": 80 }
{ "type": "prefer-rail" }
{ "type": "avoid-zone",     "zoneId": "..." }
{ "type": "must-be-local",  "componentRef": "U1" }
{ "type": "manual",         "note": "see schematic revision B" }
```

`prefer-rail` is only meaningful for nets that physically fit on a rail
(it is a hint, not a guarantee).

## Layout (initial)

For a fresh project, ship:

```json
{
  "version": 1,
  "boardId": "half-400-standard-split-rails",
  "placements": [],
  "jumpers": [],
  "manualElectricalLinks": []
}
```

When saving a worked-on board, fill in:

- `placements`: per-component pose (see below)
- `jumpers`: explicit wires drawn by hand
- `manualElectricalLinks`: pairs of holes joined without a wire (rare)

A placement:

```jsonc
{
  "componentRef": "U1",
  "anchorHoleId": "a10",
  "orientation":  0,
  "span":         null,
  "pinHoles":     { "1": "a10", "2": "b10", "3": "c10", "4": "d10", "5": "e10", "6": "f10", "7": "g10", "8": "h10" },
  "occupiedHoleIds": ["a10","b10","c10","d10","e10","f10","g10","h10"],
  "locked": false
}
```

A jumper:

```jsonc
{
  "id":   "J12",
  "netId": "gnd",
  "startHoleId": "rail-bottom-minus-17",
  "endHoleId":   "e17",
  "path": {
    "points": [
      { "x": 43.18, "y": 38.10 },
      { "x": 43.18, "y": 17.78 }
    ],
    "layer": "lower"
  },
  "color": "#1a1a1a",
  "estimatedLengthMm": 30.5,
  "locked": false
}
```

Coordinates in `path.points` are millimetres, board-absolute.

## Settings

```jsonc
{
  "seed":                     12345,
  "solverPreset":             "balanced",     // fast | balanced | quality
  "placementWeights": {
    "weightedDistance": 1.0,
    "congestion":       15.0,
    "mechanical":       10.0,
    "criticalRule":     500.0,
    "accessibility":    25.0,
    "overlap":          1000000.0,
    "cluster":          8.0
  },
  "routingWeights": {
    "lengthMm":            1.0,
    "jumperCount":         12.0,
    "crossing":            40.0,
    "congestion":          30.0,
    "avoidZone":           100.0,
    "criticalViolation":   500.0,
    "unroutedTerminal":    10000.0
  },
  "allowCriticalNetClasses": false
}
```

Preset defaults:

| Preset     | Restarts | Local-search iters | Ripup iters |
|------------|----------|--------------------|-------------|
| `fast`     | 1        | 300                | 5           |
| `balanced` | 4        | 2000               | 20          |
| `quality`  | 8        | 8000               | 40          |

## Footprint overrides

Use when a part does not match its stock footprint pin semantics. Two common
cases:

- **Renaming DIP pins** for clarity in the BOM and assembly guide (a 555
  wired as an oscillator has different pin semantics than stock):

  ```jsonc
  {
    "componentRef": "U1",
    "footprintId":  "DIP-8",
    "pinMap":       { "1": "VCC", "2": "TRIG", "3": "OUT", "4": "RESET",
                      "5": "CTRL", "6": "THR", "7": "DIS", "8": "GND" }
  }
  ```

- **Choosing a transistor pinout.** `TO-92` is a generic 3-pin footprint;
  pin 1 / 2 / 3 are positional. Pick the permutation your part family uses:

  ```jsonc
  { "componentRef": "Q1", "footprintId": "TO-92",
    "pinMap": { "1": "E", "2": "B", "3": "C" } }   // EBC (BC547, 2N3904, …)
  { "componentRef": "Q2", "footprintId": "TO-92",
    "pinMap": { "1": "E", "2": "C", "3": "B" } }   // ECB (2SC1815, …)
  ```

  The pin numbers you put in `components[].pins` and `nets[].pins[*].pin`
  stay as the positional ids `"1"`, `"2"`, `"3"`. The mapping above only
  affects labels in the BOM, the assembly guide, and the SVG. See the
  full TO-92 pinout table in [`FOOTPRINTS.md`](./FOOTPRINTS.md).

`pinMap` does not affect the solver's electrical model; it only renames pins
in the BOM and assembly instructions.

## Minimal working example

A two-LED, two-resistor, one-supply circuit:

```json
{
  "format": "autobreadboard-project",
  "version": 1,
  "name": "Two LEDs",
  "board": { "modelId": "half-400-standard-split-rails" },
  "components": [
    { "ref": "J1",  "footprintId": "HEADER-1x2", "pins": ["1","2"], "locked": false, "tags": [] },
    { "ref": "R1",  "footprintId": "AXIAL-R",    "pins": ["1","2"], "locked": false, "tags": [], "value": "330" },
    { "ref": "R2",  "footprintId": "AXIAL-R",    "pins": ["1","2"], "locked": false, "tags": [], "value": "330" },
    { "ref": "LED1","footprintId": "LED-2P",     "pins": ["1","2"], "locked": false, "tags": [] },
    { "ref": "LED2","footprintId": "LED-2P",     "pins": ["1","2"], "locked": false, "tags": [] }
  ],
  "nets": [
    { "id": "vcc",   "name": "VCC",   "pins": [
        { "componentRef": "J1",   "pin": "1" },
        { "componentRef": "R1",   "pin": "1" },
        { "componentRef": "R2",   "pin": "1" }
      ], "netClass": "power",    "priority": 10, "constraints": [] },
    { "id": "led1",  "name": "LED1", "pins": [
        { "componentRef": "R1",   "pin": "2" },
        { "componentRef": "LED1", "pin": "1" }
      ], "netClass": "digital",  "priority": 5,  "constraints": [] },
    { "id": "led2",  "name": "LED2", "pins": [
        { "componentRef": "R2",   "pin": "2" },
        { "componentRef": "LED2", "pin": "1" }
      ], "netClass": "digital",  "priority": 5,  "constraints": [] },
    { "id": "gnd",   "name": "GND",  "pins": [
        { "componentRef": "J1",   "pin": "2" },
        { "componentRef": "LED1", "pin": "2" },
        { "componentRef": "LED2", "pin": "2" }
      ], "netClass": "ground",   "priority": 10, "constraints": [] }
  ],
  "layout": {
    "version": 1,
    "boardId": "half-400-standard-split-rails",
    "placements": [], "jumpers": [], "manualElectricalLinks": []
  },
  "settings": {
    "seed": 12345, "solverPreset": "balanced",
    "placementWeights": {
      "weightedDistance": 1.0, "congestion": 15.0, "mechanical": 10.0,
      "criticalRule": 500.0, "accessibility": 25.0, "overlap": 1000000.0, "cluster": 8.0
    },
    "routingWeights": {
      "lengthMm": 1.0, "jumperCount": 12.0, "crossing": 40.0, "congestion": 30.0,
      "avoidZone": 100.0, "criticalViolation": 500.0, "unroutedTerminal": 10000.0
    },
    "allowCriticalNetClasses": false
  },
  "footprintOverrides": []
}
```

Save as `two-leds.json` and load via the *New project from JSON* button on
the project list page, or `POST /api/v1/projects` with `{"name": "Two LEDs", "document": <…>}`.

### Minimal perfboard example

A two-LED, two-resistor circuit on a 20×30 single-sided perfboard. The
`layout` field is a `TraceLayout`, and the document is solved with
`trace-route` / `trace-solve`, **not** `solve`:

```json
{
  "format": "autobreadboard-project",
  "version": 1,
  "name": "Two LEDs (perfboard)",
  "board": { "modelId": "strip-20x30-single" },
  "components": [
    { "ref": "J1",  "footprintId": "HEADER-1x2", "pins": ["1","2"], "locked": false, "tags": [] },
    { "ref": "R1",  "footprintId": "AXIAL-R",    "pins": ["1","2"], "locked": false, "tags": [], "value": "330" },
    { "ref": "R2",  "footprintId": "AXIAL-R",    "pins": ["1","2"], "locked": false, "tags": [], "value": "330" },
    { "ref": "LED1","footprintId": "LED-2P",     "pins": ["1","2"], "locked": false, "tags": [] },
    { "ref": "LED2","footprintId": "LED-2P",     "pins": ["1","2"], "locked": false, "tags": [] }
  ],
  "nets": [
    { "id": "vcc",  "name": "VCC",  "pins": [
        { "componentRef": "J1",   "pin": "1" },
        { "componentRef": "R1",   "pin": "1" },
        { "componentRef": "R2",   "pin": "1" }
      ], "netClass": "power",   "priority": 10, "constraints": [] },
    { "id": "led1", "name": "LED1","pins": [
        { "componentRef": "R1",   "pin": "2" },
        { "componentRef": "LED1", "pin": "1" }
      ], "netClass": "digital", "priority": 5,  "constraints": [] },
    { "id": "led2", "name": "LED2","pins": [
        { "componentRef": "R2",   "pin": "2" },
        { "componentRef": "LED2", "pin": "1" }
      ], "netClass": "digital", "priority": 5,  "constraints": [] },
    { "id": "gnd",  "name": "GND", "pins": [
        { "componentRef": "J1",   "pin": "2" },
        { "componentRef": "LED1", "pin": "2" },
        { "componentRef": "LED2", "pin": "2" }
      ], "netClass": "ground",  "priority": 10, "constraints": [] }
  ],
  "layout": {
    "version": 1,
    "boardId": "strip-20x30-single",
    "componentPlacements": [],
    "traces": [],
    "vias": []
  },
  "settings": {
    "seed": 12345, "solverPreset": "balanced",
    "placementWeights": {
      "weightedDistance": 1.0, "congestion": 15.0, "mechanical": 10.0,
      "criticalRule": 500.0, "accessibility": 25.0, "overlap": 1000000.0, "cluster": 8.0
    },
    "routingWeights": {
      "lengthMm": 1.0, "jumperCount": 12.0, "crossing": 40.0, "congestion": 30.0,
      "avoidZone": 100.0, "criticalViolation": 500.0, "unroutedTerminal": 10000.0
    },
    "allowCriticalNetClasses": false
  },
  "footprintOverrides": []
}
```

Submit jobs as `trace-route` (route only against an existing placement) or
`trace-solve` (place + route):

```bash
curl -s -X POST http://localhost:8000/api/v1/projects/$PROJECT_ID/jobs \
  -H 'content-type: application/json' \
  -d '{"operation":"trace-solve","seed":12345}'
```

## Round-trip guarantees

`ProjectDocument.model_validate(json)` → `model_dump(by_alias=True)` returns
the original dict byte-identically, *except* for fields that have defaults you
didn't send — those are written back in canonical form. Tests assert this
for the ten fixtures under `backend/tests/fixtures/`.

## Error reference (relevant subset)

| Diagnostic code               | Severity | Meaning |
|-------------------------------|----------|---------|
| `UNKNOWN_FOOTPRINT`           | error    | `footprintId` not in the registry. |
| `DUPLICATE_COMPONENT_REF`     | error    | Two components share the same `ref`. |
| `PIN_IN_MULTIPLE_NETS`        | error    | A `PinRef` is in more than one net. |
| `UNKNOWN_PIN_REFERENCE`       | error    | A net pin references a component or pin not declared in `components`. |
| `NET_SINGLE_PIN`              | warning  | A net has fewer than two pins. |
| `HOLE_COLLISION`              | error    | Two placements claim the same hole. |
| `BODY_COLLISION`              | error    | Two component bodies overlap. |
| `PIN_OUT_OF_BOARD`            | error    | A placement references an off-board hole. |
| `PLACEMENT_RULE_VIOLATION`    | error    | A placement violates a footprint rule (e.g. DIP not straddling the gap). |
| `SHORT_BETWEEN_NETS`          | error    | Two nets share an electrical node (via jumper or internal connection). |
| `NET_OPEN`                    | error    | A net's pins do not all reach the same electrical node. |
| `INVALID_JUMPER_ENDPOINT`     | error    | A jumper references a missing or disabled hole. *(breadboard only)* |
| `CRITICAL_NET_CLASS_ROUTED`   | warning  | A `high-current`/`clock`/`switching`/`analog-sensitive` net was routed. |
| `HIGH_CURRENT_ON_RAIL`        | warning  | A `high-current` net reaches a rail. *(breadboard only)* |
| `HIGH_CONGESTION`             | warning  | A column bucket carries more than 6 jumpers. *(breadboard only)* |

See `backend/app/domain/diagnostics.py` for the full catalog. Perfboard
diagnostics are emitted by `backend/app/domain/traces/validate.py`; codes
it raises include `DUPLICATE_COMPONENT_REF`, `UNKNOWN_FOOTPRINT`,
`NET_SINGLE_PIN`, `PIN_IN_MULTIPLE_NETS`, `PIN_OUT_OF_BOARD`,
`UNPLACED_COMPONENT`, and `UNROUTED_TERMINAL`.