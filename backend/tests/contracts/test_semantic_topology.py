from __future__ import annotations

from services.codegen.engine import audit_then_run
from services.codegen.templates import get_seed_script


def test_brep_face_references_survive_a_dimensional_rebuild() -> None:
    _, script = get_seed_script("simple_box")

    before = audit_then_run(
        script=script,
        parameter_overrides={"width": 120.0},
        targets=["stl", "glb"],
        trusted_source=True,
    )
    after = audit_then_run(
        script=script,
        parameter_overrides={"width": 150.0},
        targets=["stl", "glb"],
        trusted_source=True,
    )

    assert before.ok and after.ok
    before_map = before.payload.get("selection_map") or {}
    after_map = after.payload.get("selection_map") or {}
    assert {entry["topology_ref"] for entry in before_map.values()} == {
        entry["topology_ref"] for entry in after_map.values()
    }
    assert {entry["feature_id"] for entry in before_map.values()} == {
        entry["feature_id"] for entry in after_map.values()
    }
