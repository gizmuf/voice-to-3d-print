from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

import trimesh
from cadquery import exporters as cq_exporters, importers as cq_importers

from services.editable_model import BodyNode, EditableModel, Manufacturability


@dataclass
class ImportedStep:
    workspace_model: EditableModel
    glb_path: Path
    stl_path: Path
    import_mode: str


def import_step_reference(content: bytes, filename: str, output_dir: Path) -> ImportedStep:
    output_dir.mkdir(parents=True, exist_ok=True)
    step_path = output_dir / filename
    step_path.write_bytes(content)

    imported = cq_importers.importStep(str(step_path))
    stl_path = output_dir / "imported-reference.stl"
    glb_path = output_dir / "imported-reference.glb"
    cq_exporters.export(imported, str(stl_path))
    mesh = trimesh.load_mesh(stl_path, force="mesh")
    trimesh.Scene(mesh).export(glb_path)
    extents = mesh.extents.tolist() if hasattr(mesh, "extents") else [0.0, 0.0, 0.0]

    model = EditableModel(
        id=uuid.uuid4().hex,
        source="step_import",
        revision_id=uuid.uuid4().hex,
        bodies=[
            BodyNode(
                id="step:root",
                kind="body",
                label=filename,
                editable=False,
                confidence=0.0,
                unsupported_reason="STEP import is available, but this file is reference-only until a supported semantic feature set is recognized.",
                params={
                    "_template_id": "step_reference",
                    "_object_label": filename,
                    "width_mm": float(extents[0] if len(extents) > 0 else 0.0),
                    "depth_mm": float(extents[1] if len(extents) > 1 else 0.0),
                    "height_mm": float(extents[2] if len(extents) > 2 else 0.0),
                },
                children=[],
            )
        ],
        manufacturability=Manufacturability(
            status="risk",
            messages=["STEP import succeeded in reference mode. Editable feature recognition is intentionally limited in v1."],
        ),
    )
    return ImportedStep(workspace_model=model, glb_path=glb_path, stl_path=stl_path, import_mode="reference")

