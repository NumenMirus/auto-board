"""Performance benchmark — solve fixtures 4/5/6 with preset=balanced; each <5s."""
import json
import time
from pathlib import Path

from app.settings import get_settings
get_settings()

from app.domain import solve as solve_mod
from app.domain.models import (
    ProjectDocument,
    SolverOptions,
)
from app.domain.boards.registry import BUILTIN_BOARDS
from app.domain.footprints.registry import FOOTPRINTS
from app.domain.index import BoardIndex

FIXTURES = ["04-74hc14-flagship", "05-transistor-led", "06-dip8-header-breakout"]
ROOT = Path("tests/fixtures")

board_models = BUILTIN_BOARDS
footprints = FOOTPRINTS

failures = []
for name in FIXTURES:
    doc = ProjectDocument.model_validate(json.loads((ROOT / f"{name}.json").read_text()))
    board = board_models[doc.board.model_id]
    index = BoardIndex.build(board)
    options = SolverOptions(preset="balanced")
    t0 = time.perf_counter()
    try:
        result = solve_mod.solve(
            board=board,
            index=index,
            footprints=footprints,
            components=doc.components,
            nets=doc.nets,
            options=options,
        )
    except Exception as exc:
        print(f"{name}: EXCEPTION {type(exc).__name__}: {exc}")
        failures.append((name, "exception"))
        continue
    elapsed = time.perf_counter() - t0
    diag_codes = sorted({d.code for d in result.diagnostics})
    errs = sum(1 for d in result.diagnostics if d.severity == "error")
    print(
        f"{name}: {elapsed:5.2f}s  components={len(result.layout.placements)}/{len(doc.components)}  "
        f"netsCompleted={result.score.nets_completed}/{result.score.nets_total}  "
        f"jumpers={result.score.jumper_count}  errors={errs}  codes={diag_codes}"
    )
    if elapsed >= 5.0:
        failures.append((name, f"{elapsed:.2f}s exceeds 5s budget"))

print()
if failures:
    print("FAIL:", failures)
    raise SystemExit(1)
print("PASS — all fixtures solved in <5s")
