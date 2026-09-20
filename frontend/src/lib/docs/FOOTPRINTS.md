# Footprint catalog

AutoBreadboard ships with a fixed registry of breadboard footprints. The IDs below
are the strings you set on `Component.footprintId` when authoring a project
document (see [`PROJECT_JSON.md`](./PROJECT_JSON.md)). They are also what
`GET /api/v1/footprints` returns at runtime.

> Source of truth: `backend/app/domain/footprints/registry.py`. This document
> is generated from that registry and is kept in sync by hand.

## How to read the tables

- **Footprint id** — the string used in `footprintId` / `BreadboardFootprint.id`.
- **Pins** — the pin numbers that must appear in `Component.pins`. Pin `"1"` is
  the *anchor* (the hole the placer drops the footprint on). Offsets are
  integer lattice steps, not millimetres.
- **Orientations** — which rotations the solver will consider. `0` is the
  canonical pose in the registry; rotation is applied about the anchor.
- **Rules** — placement constraints. `must-straddle-center-gap` means the part
  occupies hole rows `e` and `f` (the DIP channel). `must-be-on-main-area` is
  implicit for every footprint; rails are jumper endpoints only.
- **Polarity** — pin → `anode|cathode|...`. The editor and renderer mark these
  pins; the solver does not enforce correctness.
- **Flexible span** — for two-pin parts, the gap between pin `1` and pin `2`
  in lattice holes. The solver picks a span in the given range; `preferred`
  has zero mechanical cost.

## DIP packages

DIPs straddle the centre gap between hole rows `e` and `f`; pin 1 sits on
the anchor hole, lower-numbered pins march rightward along row `e`, then
upper-numbered pins walk back along row `f`.

| Id        | Pins              | Body (cols × rows) | Orientations | Rules |
|-----------|-------------------|--------------------|--------------|-------|
| `DIP-8`   | `1`–`8`           | 4 × 2              | 0, 180       | straddle centre gap, main area |
| `DIP-14`  | `1`–`14`          | 7 × 2              | 0, 180       | straddle centre gap, main area |
| `DIP-16`  | `1`–`16`          | 8 × 2              | 0, 180       | straddle centre gap, main area |
| `DIP-20`  | `1`–`20`          | 10 × 2             | 0, 180       | straddle centre gap, main area |
| `DIP-28`  | `1`–`28`          | 14 × 2             | 0, 180       | straddle centre gap, main area |

Pin numbering for an N-pin DIP:

```
e:  1  2  3  ...  N/2
f:  N  N-1 ...  N/2 + 1
```

## Two-pin flexible parts

Two-pin footprints share the same shape — pin `1` at offset `(0, 0)`, pin `2`
at `(span, 0)` — but differ in span range and polarity.

| Id                     | Pins | Span (holes) | Orientations | Polarity          | Notes |
|------------------------|------|--------------|--------------|-------------------|-------|
| `AXIAL-R`              | 1, 2 | 2–8, pref 3  | 0, 90, 180, 270 | —             | Through-hole resistor. |
| `AXIAL-DIODE`          | 1, 2 | 2–8, pref 3  | 0, 90, 180, 270 | pin 2 cathode | Stripe on cathode end. |
| `RADIAL-CAP-2P`        | 1, 2 | 1–3, pref 2  | 0, 90, 180, 270 | —             | Non-polar ceramic / film cap. |
| `ELECTROLYTIC-CAP-2P`  | 1, 2 | 1–3, pref 2  | 0, 90, 180, 270 | pin 1 anode, pin 2 cathode | Stripe on cathode. |
| `LED-2P`               | 1, 2 | 1–3, pref 2  | 0, 90, 180, 270 | pin 1 anode, pin 2 cathode | Long lead = anode. |

## Three-pin parts

### `TO-92` (through-hole transistor, generic)

| Field | Value |
|-------|-------|
| Id | `TO-92` |
| Pins | 1, 2, 3 |
| Layout | pin 1 → (0,0), pin 2 → (1,0), pin 3 → (2,0) |
| Orientations | 0, 90, 180, 270 |
| Notes | Approximate body; emits `APPROXIMATE_FOOTPRINT` at validation. |

`TO-92` is a **generic 3-pin inline footprint**. It does **not** assume any
particular transistor pinout — pin 1 / 2 / 3 are positional labels only,
not electrical labels. To make a project use a specific E/B/C mapping,
assign one with `footprintOverrides` (see
[`PROJECT_JSON.md`](./PROJECT_JSON.md)):

```json
{
  "componentRef": "Q1",
  "footprintId": "TO-92",
  "pinMap": { "1": "E", "2": "B", "3": "C" }
}
```

#### Common TO-92 pinouts (flat side toward you, leads down)

There are six permutations; the part family determines which one applies.
**Always check the specific datasheet.**

| Permutation | Pin 1 | Pin 2 | Pin 3 | Example parts |
|-------------|-------|-------|-------|---------------|
| **EBC**     | Emitter  | Base    | Collector | BC547, BC557, 2N3904, 2N3906, BC107, BC108, BC109 |
| **EBC flipped (BEC)** | Base | Emitter | Collector | Some European / older PNP |
| **ECB**     | Emitter  | Collector | Base    | 2SC1815, some Japanese NPN |
| **CBE**     | Collector | Base    | Emitter | Some older germanium (OC71) |
| **CEB**     | Collector | Emitter | Base    | Less common |
| **BCE**     | Base    | Collector | Emitter | Rare (some regulators) |

For TO-220 / TO-126 / TO-39 / TO-18 / TO-5 the part numbers above are wrong;
those packages have different layouts and are not in the registry.

#### Orientation reminder

When you read the flat-side-toward-you, leads-down view, "left to right"
becomes "right to left" if you flip the part over to drop it into the
board. The pin-number labels are relative to the part, not to your
perspective. The assembler instructions print pin labels from `pinMap`,
not raw numbers.

## Switches

| Id           | Pins              | Layout                       | Orientations | Internal connections |
|--------------|-------------------|------------------------------|--------------|----------------------|
| `TACT-SW-4P` | 1, 2, 3, 4        | 1 → (0,0), 2 → (2,0), 3 → (0,1), 4 → (2,1) | 0, 180 | `1↔2` and `3↔4` are one node each |

Tact switches straddle the centre gap. The two internal pairs mean a net
connected to pin `1` is *also* on pin `2` (and likewise for `3`/`4`); the
validator's DSU treats them as a single electrical node.

## Pin headers and connectors

| Id              | Pins   | Orientations | Clearance | Notes |
|-----------------|--------|--------------|-----------|-------|
| `HEADER-1x2`–`HEADER-1x10` | `1`–`N` (N = 2..10) | 0, 90, 180, 270 | none | Male pin strip. |
| `CONN-1x2`–`CONN-1x4`      | `1`–`N` (N = 2..4)  | 0, 90, 180, 270 | 1 hole around | Screw / terminal-block style connector. |

## Choosing `pins` on a component

`Component.pins` is a list of pin *names* that the component actually uses.
For fixed-pin footprints (`DIP-*`, `HEADER-*`, `CONN-*`, `TO-92`, `TACT-SW-4P`),
list exactly the pins you wire up; you can omit unused pins (e.g. `["1","2","3"]`
for a 555 wired only to GND/TRIG/OUT). For two-pin flexible parts, list
`["1", "2"]`.

## Looking up the live registry

```bash
curl -s http://localhost:8000/api/v1/footprints | jq '.[].id'
```

Returns every id above.

## Adding a new footprint

This is **not** user-extensible at runtime. To add one:

1. Edit `backend/app/domain/footprints/registry.py` and add a builder + entry in
   `FOOTPRINTS`.
2. Add the corresponding fixture or extend an existing one.
3. Bump the wire-format version if a new field is required.
4. Run `make lint && make test`.