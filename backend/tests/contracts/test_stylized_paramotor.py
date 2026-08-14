from __future__ import annotations

from services.codegen.engine import audit_then_run
from services.codegen.templates import get_seed_script
import trimesh


def test_stylized_paramotor_builds_to_requested_height_with_semantic_faces() -> None:
    _, script = get_seed_script("stylized_paramotor")

    result = audit_then_run(script=script, targets=["stl", "glb"], trusted_source=True)

    assert result.ok, result.payload
    assert abs(result.payload["bbox_mm"][2] - 120.0) < 0.1
    assert result.payload["mesh_hash"]
    assert len(result.payload.get("selection_map") or {}) >= 10
    mesh = trimesh.load_mesh(result.payload["artifacts"]["stl"], force="mesh")
    assert mesh.is_watertight
    assert mesh.body_count == 1
