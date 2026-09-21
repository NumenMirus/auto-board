"""Tests for the `schematic` field on `ProjectDocument`.

Validates the wire-format contract for the schematic editor: a document
without `schematic` still validates (old stored documents keep loading), a
document with a full schematic round-trips through camelCase aliasing, and
an unknown node `kind` is rejected by the discriminated union.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.models import ProjectDocument

pytest_plugins: list[str] = []


def _base_document() -> dict[str, object]:
    return {
        "format": "autobreadboard-project",
        "version": 1,
        "name": "led-blinker",
        "board": {"modelId": "half-400"},
        "components": [],
        "nets": [],
        "layout": {
            "version": 1,
            "boardId": "half-400",
            "placements": [],
            "jumpers": [],
            "manualElectricalLinks": [],
        },
        "settings": {
            "seed": 1,
            "solverPreset": "balanced",
            "placementWeights": {},
            "routingWeights": {},
            "allowCriticalNetClasses": False,
        },
        "footprintOverrides": [],
    }


def test_document_without_schematic_validates() -> None:
    """Old stored documents (no `schematic` key at all) keep loading, and the
    field defaults to `None` on dump."""
    doc = ProjectDocument.model_validate(_base_document())
    dumped = doc.model_dump(by_alias=True)
    assert dumped["schematic"] is None


def test_document_with_schematic_round_trips_camel_case() -> None:
    """A full schematic (one symbol node, one ground port, one connection, one
    net override) round-trips with camelCase keys intact."""
    body = _base_document()
    body["schematic"] = {
        "version": 1,
        "nodes": [
            {
                "kind": "symbol",
                "id": "sym-1",
                "ref": "R1",
                "value": "10k",
                "footprintId": "AXIAL-R",
                "pins": ["1", "2"],
                "x": 4,
                "y": 2,
                "rotation": 0,
            },
            {
                "kind": "port",
                "id": "port-1",
                "portKind": "ground",
                "netName": "GND",
                "x": 4,
                "y": 6,
                "rotation": 0,
            },
        ],
        "connections": [
            {
                "id": "w-1",
                "a": {"nodeId": "sym-1", "pin": "2"},
                "b": {"nodeId": "port-1", "pin": None},
            }
        ],
        "netOverrides": [{"netName": "GND", "netClass": "ground", "priority": 5}],
    }

    doc = ProjectDocument.model_validate(body)
    dumped = doc.model_dump(by_alias=True)
    schematic = dumped["schematic"]

    assert schematic["nodes"][0]["footprintId"] == "AXIAL-R"
    assert schematic["nodes"][1]["portKind"] == "ground"
    assert schematic["nodes"][1]["netName"] == "GND"
    assert schematic["connections"][0]["a"]["nodeId"] == "sym-1"
    assert schematic["netOverrides"][0]["netName"] == "GND"
    assert schematic["netOverrides"][0]["netClass"] == "ground"


def test_unknown_node_kind_is_rejected() -> None:
    """The `SchematicNode` discriminated union is closed: a `kind` outside
    `symbol`/`port` raises `ValidationError`."""
    body = _base_document()
    body["schematic"] = {
        "version": 1,
        "nodes": [{"kind": "wire", "id": "w-1", "x": 0, "y": 0}],
        "connections": [],
        "netOverrides": [],
    }

    with pytest.raises(ValidationError):
        ProjectDocument.model_validate(body)
