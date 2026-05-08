from __future__ import annotations

from pathlib import Path

import trimesh

from services.codegen.engine import run_manufacturability
from services.codegen.orientation import compute_overhang_fraction


def _box_on_bed(extents: tuple[float, float, float]) -> trimesh.Trimesh:
    mesh = trimesh.creation.box(extents=extents)
    mesh.apply_translation((0, 0, extents[2] / 2.0))
    return mesh


def test_build_plate_contact_face_is_not_counted_as_overhang(tmp_path: Path) -> None:
    mesh = _box_on_bed((20.0, 20.0, 10.0))
    stl_path = tmp_path / "box.stl"
    mesh.export(stl_path)

    report = run_manufacturability(stl_path=stl_path, process="fdm")

    assert report.status == "safe"
    assert [issue.code for issue in report.issues] == []
    assert compute_overhang_fraction(mesh, max_overhang_deg=55.0) == 0.0


def test_real_unsupported_downward_face_still_counts_as_overhang() -> None:
    mesh = _box_on_bed((20.0, 20.0, 10.0))
    shelf = trimesh.creation.box(extents=(12.0, 12.0, 2.0))
    shelf.apply_translation((0, 0, 25.0))
    combined = trimesh.util.concatenate([mesh, shelf])

    assert compute_overhang_fraction(combined, max_overhang_deg=55.0) > 0.0

