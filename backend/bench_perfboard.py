"""Performance benchmark — perfboard trace-solve on a DIP-14 + passives fixture.

Mirrors bench.py's breadboard benchmark but exercises the perfboard pipeline
(maze router + rip-up) on a comparably-sized circuit: DIP-14 + 2 resistors +
1 LED, four nets, on strip-20x30-double. Must finish under 5s per the plan's
Verification item.
"""

import time

from app.settings import get_settings

get_settings()

from app.domain.boards.registry import get_board_model
from app.domain.models import (
    Component,
    ComponentPlacement,
    Net,
    PerfboardModel,
    PinRef,
    SolverOptions,
    TraceLayout,
)
from app.domain.perfboards.registry import PERFBOARD_FOOTPRINTS
from app.domain.traces.solve import solve as trace_solve

board = get_board_model("strip-20x30-double")
assert isinstance(board, PerfboardModel)

# DIP-14 anchored at row 5 col 5 (7 pins per side, rows 5 and 6)
dip_pins = {}
for k in range(7):
    dip_pins[str(k + 1)] = f"5-{5 + k}"
for k in range(7):
    dip_pins[str(8 + k)] = f"6-{11 - k}"

placements = [
    ComponentPlacement(
        component_ref="U1",
        anchor_hole_id="5-5",
        orientation=0,
        span=None,
        pin_holes=dip_pins,
        occupied_hole_ids=list(dip_pins.values()),
        locked=False,
    ),
    ComponentPlacement(
        component_ref="R1",
        anchor_hole_id="2-2",
        orientation=0,
        span=None,
        pin_holes={"1": "2-2", "2": "2-5"},
        occupied_hole_ids=["2-2", "2-3", "2-4", "2-5"],
        locked=False,
    ),
    ComponentPlacement(
        component_ref="R2",
        anchor_hole_id="2-8",
        orientation=0,
        span=None,
        pin_holes={"1": "2-8", "2": "2-11"},
        occupied_hole_ids=["2-8", "2-9", "2-10", "2-11"],
        locked=False,
    ),
    ComponentPlacement(
        component_ref="LED1",
        anchor_hole_id="10-5",
        orientation=0,
        span=None,
        pin_holes={"1": "10-5", "2": "10-8"},
        occupied_hole_ids=["10-5", "10-6", "10-7", "10-8"],
        locked=False,
    ),
]
components = [
    Component(ref="U1", value="74HC14", footprint_id="DIP-14", pins=[str(i) for i in range(1, 15)], locked=False, tags=[]),
    Component(ref="R1", value="330", footprint_id="AXIAL-R", pins=["1", "2"], locked=False, tags=[]),
    Component(ref="R2", value="10k", footprint_id="AXIAL-R", pins=["1", "2"], locked=False, tags=[]),
    Component(ref="LED1", value=None, footprint_id="LED-2P", pins=["1", "2"], locked=False, tags=[]),
]
nets = [
    Net(id="VCC", name="VCC", pins=[PinRef(component_ref="U1", pin="14"), PinRef(component_ref="R2", pin="1")], net_class="power", priority=10, constraints=[]),
    Net(id="GND", name="GND", pins=[PinRef(component_ref="U1", pin="7"), PinRef(component_ref="LED1", pin="2")], net_class="ground", priority=10, constraints=[]),
    Net(id="IN1", name="IN1", pins=[PinRef(component_ref="U1", pin="1"), PinRef(component_ref="R1", pin="1")], net_class="digital", priority=5, constraints=[]),
    Net(id="OUT1", name="OUT1", pins=[PinRef(component_ref="U1", pin="2"), PinRef(component_ref="LED1", pin="1")], net_class="digital", priority=5, constraints=[]),
]

initial_layout = TraceLayout(board_id=board.id, placements=placements)
options = SolverOptions(preset="balanced")

t0 = time.perf_counter()
result = trace_solve(
    board=board,
    footprints=dict(PERFBOARD_FOOTPRINTS),
    components=components,
    nets=nets,
    options=options,
    initial_layout=initial_layout,
)
elapsed = time.perf_counter() - t0

print(
    f"perfboard trace-solve: {elapsed:5.2f}s  traces={len(result.layout.traces)}  "
    f"vias={len(result.layout.vias)}  errors={result.score.error_count}  "
    f"netsCompleted={result.score.nets_completed}/{result.score.nets_total}"
)
for d in result.diagnostics:
    print(f"  {d.severity} {d.code}: {d.message}")

if elapsed >= 5.0:
    print(f"FAIL — {elapsed:.2f}s exceeds 5s budget")
    raise SystemExit(1)
print("PASS — perfboard trace-solve under 5s")
