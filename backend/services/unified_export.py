from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from services.editable_model import EditableModel
from services.editable_rebuild import export_editable_build


@dataclass
class ExportResult:
    glb_path: Path
    stl_path: Path
    validation: dict


def export_workspace_model(model: EditableModel, output_dir: Path) -> ExportResult:
    glb_path, stl_path, validation = export_editable_build(model, output_dir)
    return ExportResult(glb_path=glb_path, stl_path=stl_path, validation=validation)

