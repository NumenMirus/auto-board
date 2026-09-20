"""Golden-file tests for ``app.domain.render`` and ``app.services.export``.

These tests assert byte-for-byte equality of the SVG output against committed
``.svg`` files under ``tests/golden/``. The PNG test asserts the PNG magic bytes
and a non-trivial size (no pixel-level comparison).

NOTE on ``cairosvg`` runtime: ``cairosvg`` imports cleanly on this development
machine, but its native dependency (``libcairo``) is only on
``/opt/homebrew/opt/cairo/lib`` and must be on the dynamic loader path when the
PNG/PDF tests run. Set ``DYLD_LIBRARY_PATH=/opt/homebrew/opt/cairo/lib`` in
the environment before invoking pytest. This is a local-dev-machine quirk only;
the production Docker image installs ``libcairo2`` via apt and needs no
override. The tests below are NOT skipped — they MUST run and pass when
invoked correctly.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.domain.boards.half400 import build_half400
from app.domain.footprints.registry import FOOTPRINTS
from app.domain.index import BoardIndex
from app.domain.models import (
    BreadboardModel,
    Component,
    ComponentPlacement,
    Diagnostic,
    Jumper,
    JumperPath,
    Layout,
    Net,
    Point,
)
from app.domain.render import render_svg
from app.services.export import render_export

pytest_plugins: list[str] = []

GOLDEN_DIR = Path(__file__).resolve().parent


# --------------------------------------------------------------------------
# Fixture builders (each mirrors one of the three committed .svg files).
# --------------------------------------------------------------------------


def _components_a() -> list[Component]:
    return [
        Component(ref="R1", value="470", footprint_id="AXIAL-R", pins=["1", "2"]),
        Component(ref="D1", value="red", footprint_id="LED-2P", pins=["1", "2"]),
    ]


def _placements_a() -> list[ComponentPlacement]:
    return [
        ComponentPlacement(
            component_ref="R1",
            anchor_hole_id="a1",
            orientation=0,
            span=None,
            pin_holes={"1": "a1", "2": "a4"},
            occupied_hole_ids=["a1", "a2", "a3", "a4"],
            locked=False,
        ),
        ComponentPlacement(
            component_ref="D1",
            anchor_hole_id="a20",
            orientation=0,
            span=None,
            pin_holes={"1": "a20", "2": "a22"},
            occupied_hole_ids=["a20", "a21", "a22"],
            locked=False,
        ),
    ]


def _layout_a(board: BreadboardModel) -> Layout:
    index = BoardIndex.build(board)
    a4 = index.hole_point("a4")
    a20 = index.hole_point("a20")
    return Layout(
        version=1,
        board_id=board.id,
        placements=_placements_a(),
        jumpers=[
            Jumper(
                id="J1",
                net_id="N1",
                start_hole_id="a4",
                end_hole_id="a20",
                path=JumperPath(points=[Point(x=a4[0], y=a4[1]), Point(x=a20[0], y=a20[1])], layer="lower"),
                color="#1f77b4",
                estimated_length_mm=12.0,
                locked=False,
            ),
        ],
    )


def _layout_b(board: BreadboardModel) -> Layout:
    """Same as A but with no jumpers — diagnostic marker renders alone."""
    return Layout(
        version=1,
        board_id=board.id,
        placements=_placements_a(),
        jumpers=[],
    )


def _components_c() -> list[Component]:
    pins = ["1", "2", "3", "4", "5", "6", "7", "8"]
    return [Component(ref="U1", value="74HC00", footprint_id="DIP-8", pins=pins)]


def _placements_c() -> list[ComponentPlacement]:
    pins_above = ["a10", "a11", "a12", "a13"]
    pins_below = ["f10", "f11", "f12", "f13"]
    pin_names = ["1", "2", "3", "4", "8", "7", "6", "5"]
    pin_holes = dict(zip(pin_names, pins_above + pins_below, strict=True))
    return [
        ComponentPlacement(
            component_ref="U1",
            anchor_hole_id="a10",
            orientation=0,
            span=None,
            pin_holes=pin_holes,
            occupied_hole_ids=pins_above + pins_below,
            locked=False,
        ),
    ]


def _layout_c(board: BreadboardModel) -> Layout:
    index = BoardIndex.build(board)
    a10 = index.hole_point("a10")
    a15 = index.hole_point("a15")
    f13 = index.hole_point("f13")
    f20 = index.hole_point("f20")
    return Layout(
        version=1,
        board_id=board.id,
        placements=_placements_c(),
        jumpers=[
            Jumper(
                id="J1",
                net_id="N1",
                start_hole_id="a10",
                end_hole_id="a15",
                path=JumperPath(points=[Point(x=a10[0], y=a10[1]), Point(x=a15[0], y=a15[1])], layer="lower"),
                color="#1f77b4",
                estimated_length_mm=15.0,
                locked=False,
            ),
            Jumper(
                id="J2",
                net_id="N2",
                start_hole_id="f13",
                end_hole_id="f20",
                path=JumperPath(points=[Point(x=f13[0], y=f13[1]), Point(x=f20[0], y=f20[1])], layer="upper"),
                color="#ff7f0e",
                estimated_length_mm=18.0,
                locked=False,
            ),
        ],
    )


def _nets_a() -> list[Net]:
    return [Net(id="N1", name="sig", pins=[], net_class="digital", priority=0, constraints=[])]


def _nets_c() -> list[Net]:
    return [
        Net(id="N1", name="sig1", pins=[], net_class="digital", priority=0, constraints=[]),
        Net(id="N2", name="sig2", pins=[], net_class="digital", priority=0, constraints=[]),
    ]


# --------------------------------------------------------------------------
# SVG goldens
# --------------------------------------------------------------------------


def _read_golden(name: str) -> str:
    return (GOLDEN_DIR / name).read_text(encoding="utf-8")


def test_golden_a_simple_circuit() -> None:
    """Fixture A: trivial 2-component circuit on split rails."""
    board = build_half400(split_rails=True)
    index = BoardIndex.build(board)
    layout = _layout_a(board)
    actual = render_svg(board, index, FOOTPRINTS, _components_a(), _nets_a(), layout)
    expected = _read_golden("fixture_a_simple_circuit.svg")
    assert actual == expected, "golden SVG mismatch for fixture_a"


def test_golden_b_with_diagnostic() -> None:
    """Fixture B: same as A but with one diagnostic attached (with a related hole so the marker renders)."""
    board = build_half400(split_rails=True)
    index = BoardIndex.build(board)
    layout = _layout_b(board)
    diag = Diagnostic(
        id="INVALID_JUMPER_ENDPOINT:J1",
        severity="error",
        code="INVALID_JUMPER_ENDPOINT",
        message="Jumper J1 references unknown or disabled hole a1",
        related_hole_ids=["a1"],
        related_component_refs=[],
        related_net_ids=[],
        suggestion=None,
    )
    actual = render_svg(
        board,
        index,
        FOOTPRINTS,
        _components_a(),
        _nets_a(),
        layout,
        diagnostics=[diag],
    )
    expected = _read_golden("fixture_b_with_diagnostic.svg")
    assert actual == expected, "golden SVG mismatch for fixture_b"


def test_golden_c_dip8_two_layers() -> None:
    """Fixture C: DIP-8 straddling the center gap + two jumpers on different layers."""
    board = build_half400(split_rails=True)
    index = BoardIndex.build(board)
    layout = _layout_c(board)
    actual = render_svg(board, index, FOOTPRINTS, _components_c(), _nets_c(), layout)
    expected = _read_golden("fixture_c_dip8_two_layers.svg")
    assert actual == expected, "golden SVG mismatch for fixture_c"


# --------------------------------------------------------------------------
# PNG export (magic + non-zero size, no pixel-level comparison)
# --------------------------------------------------------------------------


def test_png_export_has_png_magic_and_non_trivial_size() -> None:
    """The PNG export MUST start with the standard PNG magic bytes and be non-trivial.

    NOTE: this test requires the native ``libcairo`` library on the dynamic
    loader path. On this development machine, run with
    ``DYLD_LIBRARY_PATH=/opt/homebrew/opt/cairo/lib uv run pytest ...``.
    """
    board = build_half400(split_rails=True)
    layout = _layout_a(board)
    body, content_type = asyncio.run(
        render_export(
            "png",
            board,
            _components_a(),
            _nets_a(),
            layout,
            "fixture_a",
        )
    )
    assert content_type == "image/png"
    assert body[:8] == b"\x89PNG\r\n\x1a\n", "PNG magic bytes mismatch"
    assert len(body) > 100, f"PNG payload suspiciously small: {len(body)} bytes"


# --------------------------------------------------------------------------
# End-to-end JSON / CSV round-trip sanity checks
# --------------------------------------------------------------------------


def test_json_export_envelope_is_self_describing() -> None:
    """The JSON export is a self-describing envelope, NOT a `ProjectDocument`."""
    import json as _json

    board = build_half400(split_rails=True)
    layout = _layout_a(board)
    body, content_type = asyncio.run(
        render_export(
            "json",
            board,
            _components_a(),
            _nets_a(),
            layout,
            "fixture_a",
        )
    )
    assert content_type == "application/json"
    payload = _json.loads(body)
    assert payload["format"] == "autobreadboard-export"
    assert payload["version"] == 1
    assert payload["projectName"] == "fixture_a"
    assert payload["board"]["id"] == board.id
    assert isinstance(payload["components"], list)
    assert isinstance(payload["nets"], list)
    assert isinstance(payload["layout"], dict)


def test_bom_csv_aggregates_components() -> None:
    import csv as _csv
    import io as _io

    board = build_half400(split_rails=True)
    layout = _layout_a(board)
    body, content_type = asyncio.run(
        render_export(
            "bom-csv",
            board,
            _components_a(),
            _nets_a(),
            layout,
            "fixture_a",
        )
    )
    assert content_type == "text/csv"
    rows = list(_csv.reader(_io.StringIO(body.decode("utf-8"))))
    # Header + 2 component rows.
    assert rows[0] == ["value", "footprintId", "quantity", "refs"]
    assert len(rows) == 3
    # Stable sort by footprintId then by value.
    assert rows[1][1] == "AXIAL-R"
    assert rows[1][0] == "470"
    assert rows[1][3] == "R1"
    assert rows[2][1] == "LED-2P"
    assert rows[2][0] == "red"
    assert rows[2][3] == "D1"


def test_jumpers_csv_has_correct_columns() -> None:
    import csv as _csv
    import io as _io

    board = build_half400(split_rails=True)
    layout = _layout_a(board)
    body, content_type = asyncio.run(
        render_export(
            "jumpers-csv",
            board,
            _components_a(),
            _nets_a(),
            layout,
            "fixture_a",
        )
    )
    assert content_type == "text/csv"
    rows = list(_csv.reader(_io.StringIO(body.decode("utf-8"))))
    assert rows[0] == ["id", "netId", "netName", "fromHole", "toHole", "color", "lengthMm", "layer"]
    assert len(rows) == 2  # header + 1 jumper
    assert rows[1][0] == "J1"
    assert rows[1][2] == "sig"
    assert rows[1][7] == "lower"


def test_unknown_format_raises_value_error() -> None:
    board = build_half400(split_rails=True)
    layout = Layout(version=1, board_id=board.id, placements=[], jumpers=[])
    try:
        asyncio.run(render_export("docx", board, [], [], layout, "fixture_a"))
    except ValueError as exc:
        assert "unknown export format" in str(exc)
    else:
        raise AssertionError("expected ValueError for unknown format")
