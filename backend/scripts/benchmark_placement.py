"""Side-by-side perfboard placer benchmark.

Runs every fixture in ``--fixtures`` through every engine in ``--engines``
at every preset in ``--presets``, with every seed in ``--seeds``. Records
per-row metrics and writes a CSV at ``--out``. This is observability, not a
test — exit code is always 0.

Usage::

    uv run python -m scripts.benchmark_placement \\
        --fixtures tests/fixtures \\
        --seeds 1,7,42 \\
        --presets balanced \\
        --engines greedy,cpsat \\
        --out scripts/benchmark-results.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from pathlib import Path

# Make ``app`` importable when the script is invoked directly.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.domain.boards.registry import get_board_model  # noqa: E402
from app.domain.models import Component, Net, ProjectDocument, SolverOptions, TraceLayout  # noqa: E402
from app.domain.models import PerfboardModel  # noqa: E402
from app.domain.perfboards.registry import PERFBOARD_FOOTPRINTS  # noqa: E402
from app.domain.traces import maze, route as trace_route  # noqa: E402
from app.domain.traces.place import place_greedy  # noqa: E402
from app.domain.traces.place_cpsat import solve_cpsat_placement  # noqa: E402
from app.domain.traces.validate import validate_layout  # noqa: E402


# --------------------------------------------------------------------------
# Perfboard benchmark corpus — schema-valid project JSON documents kept under
# ``backend/tests/perfboard_fixtures`` so benchmarks and regression tests use
# the same representative circuits.
# --------------------------------------------------------------------------

PERFBOARD_FIXTURE_DIR = ROOT / "tests" / "perfboard_fixtures"

_FIXTURES: dict[str, ProjectDocument] = {}


def _fixture_paths() -> list[Path]:
    return sorted(PERFBOARD_FIXTURE_DIR.glob("[0-9][0-9]-*.json"))


def load_fixture_documents() -> dict[str, ProjectDocument]:
    paths = _fixture_paths()
    if not paths:
        msg = f"no perfboard benchmark fixtures found under {PERFBOARD_FIXTURE_DIR}"
        raise FileNotFoundError(msg)
    docs: dict[str, ProjectDocument] = {}
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            document = ProjectDocument.model_validate(json.load(handle))
        docs[path.stem] = document
    return docs

def _register_safe() -> None:
    _FIXTURES.clear()
    _FIXTURES.update(load_fixture_documents())


# --------------------------------------------------------------------------
# Run + record
# --------------------------------------------------------------------------


def _run_once(
    *,
    engine: str,
    document: ProjectDocument,
    seed: int,
    preset: str,
) -> dict[str, object]:
    board = get_board_model(document.board.model_id)
    if not isinstance(board, PerfboardModel):
        msg = f"benchmark fixture {document.name!r} is not a perfboard project"
        raise ValueError(msg)
    components: list[Component] = document.components
    nets: list[Net] = document.nets
    initial = TraceLayout(board_id=board.id, placements=list(document.layout.placements))
    if engine == "cpsat":
        opts = SolverOptions(
            seed=seed,
            placement_engine="cpsat",
            preset=preset,
            placement_time_limit_ms=4000,
            placement_candidate_limit=30,
            placement_solution_count=3,
            solver_seed=seed,
        )
        t0 = time.perf_counter()
        placement = solve_cpsat_placement(
            board=board, footprints=PERFBOARD_FOOTPRINTS,
            components=components, nets=nets, options=opts,
            initial_layout=initial,
        )
        place_ms = (time.perf_counter() - t0) * 1000.0
    else:
        opts = SolverOptions(seed=seed, placement_engine="greedy", preset=preset)
        t0 = time.perf_counter()
        placement = place_greedy(
            board=board, footprints=PERFBOARD_FOOTPRINTS,
            components=components, nets=nets,
            options=opts, initial_layout=initial,
        )
        place_ms = (time.perf_counter() - t0) * 1000.0

    graph = maze.build_maze(
        rows=board.rows, cols=board.cols,
        pitch_mm=board.pitch_mm, double_sided=(board.layers == 2),
    )
    t0 = time.perf_counter()
    rr = trace_route.route(
        board_id=board.id, placements=placement.placements,
        components=components, footprints=PERFBOARD_FOOTPRINTS,
        nets=nets, graph=graph,
    )
    route_ms = (time.perf_counter() - t0) * 1000.0
    validation = validate_layout(board, PERFBOARD_FOOTPRINTS, components, nets, rr.layout)
    trace_length = sum(t.estimated_length_mm for t in rr.layout.traces)
    via_count = sum(len(t.vias) for t in rr.layout.traces)
    cols = []
    rows = []
    for p in placement.placements:
        for hid in p.occupied_hole_ids:
            cols.append(int(hid.split("-")[1]))
            rows.append(int(hid.split("-")[0]))
    span_cols = (max(cols) - min(cols)) if cols else 0
    span_rows = (max(rows) - min(rows)) if rows else 0
    proxy_total = float(placement.trace.phase_timings_ms.get("cpsat_proxy_total", 0))
    return {
        "board_id": board.id,
        "place_ms": round(place_ms, 1),
        "route_ms": round(route_ms, 1),
        "placed": len(placement.placements),
        "components_total": len(components),
        "unrouted": len(rr.unrouted_nets),
        "validation_errors": sum(1 for d in validation.diagnostics if d.severity == "error"),
        "trace_length_mm": round(trace_length, 2),
        "via_count": via_count,
        "segment_count": sum(len(t.segments) for t in rr.layout.traces),
        "span_cols": span_cols,
        "span_rows": span_rows,
        "selected_candidate_index": int(placement.trace.phase_timings_ms.get("cpsat_selected_candidate_index", 0)),
        "candidate_layout_count": int(placement.trace.phase_timings_ms.get("cpsat_solution_count", 0)),
        "routed_candidate_count": int(placement.trace.phase_timings_ms.get("cpsat_routed_count", 0)),
        "proxy_total": round(proxy_total, 1),
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _parse_csv(s: str) -> list[str]:
    return [x.strip() for x in s.split(",") if x.strip()]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fixtures", default="dip14-flagship,header-breakout",
                   help="Comma-separated fixture names or 'all'")
    p.add_argument("--seeds", default="1,7", help="Comma-separated seeds")
    p.add_argument("--presets", default="balanced",
                   help="Comma-separated preset names")
    p.add_argument("--engines", default="greedy,cpsat",
                   help="Comma-separated engines")
    p.add_argument("--out", default="scripts/benchmark-results.csv",
                   help="Output CSV path")
    args = p.parse_args()

    _register_safe()
    if args.fixtures == "all":
        fixture_names = list(_FIXTURES.keys())
    else:
        fixture_names = _parse_csv(args.fixtures)
    seeds = [int(s) for s in _parse_csv(args.seeds)]
    presets = _parse_csv(args.presets)
    engines = _parse_csv(args.engines)

    rows: list[dict[str, object]] = []
    for fixture_name in fixture_names:
        if fixture_name not in _FIXTURES:
            print(f"[warn] unknown fixture: {fixture_name}", file=sys.stderr)
            continue
        document = _FIXTURES[fixture_name]
        for engine in engines:
            for preset in presets:
                for seed in seeds:
                    try:
                        r = _run_once(
                            engine=engine,
                            document=document,
                            seed=seed, preset=preset,
                        )
                    except Exception as exc:  # noqa: BLE001
                        print(f"[err] {fixture_name}/{engine}/{preset}/{seed}: {exc}",
                              file=sys.stderr)
                        continue
                    row = {
                        "fixture": fixture_name,
                        "engine": engine,
                        "preset": preset,
                        "seed": seed,
                        **r,
                    }
                    rows.append(row)
                    print(
                        f"{fixture_name:>16}  {engine:>6}  {preset:>8}  "
                        f"seed={seed:<3}  placed={r['placed']:>2}  "
                        f"unrouted={r['unrouted']:>2}  "
                        f"trace_len={r['trace_length_mm']:>7.2f} mm  "
                        f"vias={r['via_count']:>3}  "
                        f"place_ms={r['place_ms']:>6.0f}  "
                        f"route_ms={r['route_ms']:>6.0f}"
                    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        if not rows:
            f.write("")
        else:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    # Per-fixture / engine / preset median summary.
    summary_keys = ["trace_length_mm", "via_count", "place_ms", "route_ms", "unrouted"]
    by_key: dict[tuple[str, str, str], list[dict[str, object]]] = {}
    for r in rows:
        by_key.setdefault((r["fixture"], r["engine"], r["preset"]), []).append(r)
    print("\n=== median summary ===")
    for (fixture, engine, preset), rs in sorted(by_key.items()):
        med = {k: statistics.median([r[k] for r in rs]) for k in summary_keys}
        print(
            f"{fixture:>16}  {engine:>6}  {preset:>8}  "
            f"trace_len={med['trace_length_mm']:>7.2f}  "
            f"vias={med['via_count']:>3.0f}  "
            f"place_ms={med['place_ms']:>6.0f}  "
            f"route_ms={med['route_ms']:>6.0f}  "
            f"unrouted={med['unrouted']:>2.0f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())