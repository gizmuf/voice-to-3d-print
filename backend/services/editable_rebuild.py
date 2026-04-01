from __future__ import annotations

from pathlib import Path
from typing import Any

import trimesh
from cadquery import exporters as cq_exporters

from services.editable_model import EditableModel
from services.native_converter import editable_to_structured_spec
from services.useful_objects import _cadquery_workplane_for_spec, cadquery_available
from slicer_service import validate_mesh_file


def rebuild_from_editable(model: EditableModel):
    if model.source not in {"native", "step_import", "stl_reconstructed"}:
        raise ValueError(f"Unsupported editable model source: {model.source}")
    if not cadquery_available():
        raise RuntimeError("CadQuery is not installed in the backend environment.")
    spec = editable_to_structured_spec(model)
    return _cadquery_workplane_for_spec(spec)


def export_editable_preview(model: EditableModel, output_dir: Path) -> tuple[Path, Path, dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    workplane = rebuild_from_editable(model)
    stl_path = output_dir / "preview.stl"
    glb_path = output_dir / "preview.glb"
    cq_exporters.export(workplane, str(stl_path))
    mesh = trimesh.load_mesh(stl_path, force="mesh")
    trimesh.Scene(mesh).export(glb_path)
    validation = validate_mesh_file(stl_path)
    return glb_path, stl_path, validation


def export_editable_build(model: EditableModel, output_dir: Path) -> tuple[Path, Path, dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    workplane = rebuild_from_editable(model)
    stl_path = output_dir / "model.stl"
    glb_path = output_dir / "model.glb"
    cq_exporters.export(workplane, str(stl_path))
    mesh = trimesh.load_mesh(stl_path, force="mesh")
    trimesh.Scene(mesh).export(glb_path)
    validation = validate_mesh_file(stl_path)
    return glb_path, stl_path, validation

