"""Bundle export — STL + GLB + G-code + manifest.json.

The export endpoint enforces the revision-truth check: the caller must pass
``expected_revision_id`` and it must match the workspace's current revision.
This prevents shipping an artifact built from a stale preview after the user
made further edits.

Editability gates the export:
- ``rebuilt`` : full re-export from the parametric tree (native, stl_reconstructed).
- ``as_is``   : ship whatever artifacts already exist (step_import).
- ``blocked`` : refuse the export entirely.
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

import trimesh
from fastapi import HTTPException

from config import settings
from services.editability import EditabilityAssessment, assess
from services.editable_model import EditableModel, WorkspaceRecord
from services.editable_rebuild import export_editable_build
from services.manufacturability import _hash_mesh, check_mesh
from services.printer_profiles import PrinterProfile, get_profile
from services.workspace import get_workspace, record_build
from slicer_service import _slice_mesh

SOFTWARE_VERSION = "pulsai-3d/0.1.0"


@dataclass
class BundleResult:
    workspace_id: str
    revision_id: str
    bundle_path: Path
    bundle_url: str
    glb_url: str
    stl_url: str | None
    gcode_url: str | None
    manifest: dict[str, Any]


def _workspace_artifact_url(workspace_id: str, path: Path) -> str:
    return f"/artifacts/workspaces/{workspace_id}/{path.name}"


def _classify_source(model: EditableModel) -> str:
    """Manifest-friendly source label."""
    if model.source == "step_import":
        return "step"
    if model.source == "stl_reconstructed":
        return "stl"
    if model.source == "native":
        return "text"
    return model.source


def _safe_parameter_values(model: EditableModel) -> dict[str, Any]:
    """Flatten public params from each body for the manifest."""
    out: dict[str, Any] = {}
    for body in _walk_bodies(model.bodies):
        public = {k: v for k, v in body.params.items() if not k.startswith("_")}
        if public:
            out[body.id] = public
    return out


def _walk_bodies(bodies):
    for body in bodies:
        yield body
        yield from _walk_bodies(body.children)


def _ensure_revision(record: WorkspaceRecord, expected_revision_id: str) -> None:
    if record.editable_model.revision_id != expected_revision_id:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Workspace revision is stale. Run a fresh preview before "
                    "exporting the bundle."
                ),
                "current_revision_id": record.editable_model.revision_id,
                "expected_revision_id": expected_revision_id,
            },
        )


def _validate_export_allowed(assessment: EditabilityAssessment) -> None:
    if assessment.export_allowed:
        return
    raise HTTPException(
        status_code=409,
        detail={
            "message": "Export is not allowed for this workspace.",
            "level": assessment.level,
            "reasons": assessment.reasons,
            "repair_required": assessment.repair_required,
        },
    )


def _rebuilt_artifacts(
    record: WorkspaceRecord, profile: PrinterProfile
) -> tuple[Path, Path, Path | None, dict[str, Any], dict[str, Any]]:
    workspace_dir = settings.output_dir / "workspaces" / record.workspace_id
    glb_path, stl_path, validation = export_editable_build(
        record.editable_model, workspace_dir
    )
    gcode_path = workspace_dir / "output.gcode"
    gcode_generated = _slice_mesh(stl_path, gcode_path, profile_id=profile.id)
    validation["gcode_status"] = "generated" if gcode_generated else "not_generated"
    if not gcode_generated and gcode_path.exists():
        try:
            gcode_path.unlink()
        except OSError:
            pass
    final_gcode = gcode_path if gcode_generated else None

    mesh = trimesh.load_mesh(stl_path, force="mesh")
    if not isinstance(mesh, trimesh.Trimesh):
        mesh = trimesh.util.concatenate(tuple(mesh.dump()))  # type: ignore[arg-type]
    report = check_mesh(mesh, profile)
    return (
        glb_path,
        stl_path,
        final_gcode,
        validation,
        report.model_dump(),
    )


def _as_is_artifacts(
    record: WorkspaceRecord, profile: PrinterProfile
) -> tuple[Path, Path | None, Path | None, dict[str, Any], dict[str, Any] | None]:
    """For reference-only models — copy whatever GLB/STL the workspace already has."""
    workspace_dir = settings.output_dir / "workspaces" / record.workspace_id
    candidates_glb = list(workspace_dir.glob("*.glb"))
    candidates_stl = list(workspace_dir.glob("*.stl"))
    glb_path = candidates_glb[0] if candidates_glb else None
    stl_path = candidates_stl[0] if candidates_stl else None
    if glb_path is None and stl_path is None:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Reference-only model has no cached artifacts to ship. "
                    "Re-import the source file."
                )
            },
        )
    validation: dict[str, Any] = {
        "validation_status": "as_is",
        "warnings": ["Reference-only export: no parametric rebuild performed."],
        "gcode_status": "skipped",
    }
    report_dict: dict[str, Any] | None = None
    if stl_path is not None:
        try:
            mesh = trimesh.load_mesh(stl_path, force="mesh")
            if not isinstance(mesh, trimesh.Trimesh):
                mesh = trimesh.util.concatenate(tuple(mesh.dump()))  # type: ignore[arg-type]
            report = check_mesh(mesh, profile)
            report_dict = report.model_dump()
        except Exception as exc:
            validation["warnings"].append(
                f"Manufacturability check skipped: {exc}"
            )
    return (glb_path or stl_path, stl_path, None, validation, report_dict)


def export_bundle(
    workspace_id: str,
    expected_revision_id: str,
    *,
    printer_profile_id: str | None = None,
    model_name: str | None = None,
) -> BundleResult:
    record = get_workspace(workspace_id)
    _ensure_revision(record, expected_revision_id)

    assessment = assess(record.editable_model)
    _validate_export_allowed(assessment)

    profile = get_profile(printer_profile_id)
    workspace_dir = settings.output_dir / "workspaces" / workspace_id
    workspace_dir.mkdir(parents=True, exist_ok=True)

    if assessment.export_mode == "rebuilt":
        glb_path, stl_path, gcode_path, validation, report = _rebuilt_artifacts(
            record, profile
        )
    elif assessment.export_mode == "as_is":
        glb_path, stl_path, gcode_path, validation, report = _as_is_artifacts(
            record, profile
        )
    else:  # pragma: no cover — _validate_export_allowed should have refused earlier
        raise HTTPException(status_code=500, detail="Unsupported export mode.")

    mesh_hash = ""
    if stl_path is not None:
        try:
            mesh = trimesh.load_mesh(stl_path, force="mesh")
            if not isinstance(mesh, trimesh.Trimesh):
                mesh = trimesh.util.concatenate(tuple(mesh.dump()))  # type: ignore[arg-type]
            mesh_hash = _hash_mesh(mesh)
        except Exception:
            mesh_hash = ""

    root_label = (
        record.editable_model.bodies[0].label if record.editable_model.bodies else workspace_id
    )
    manifest: dict[str, Any] = {
        "model_name": model_name or root_label,
        "workspace_id": workspace_id,
        "revision_id": record.editable_model.revision_id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "exported_at_unix": int(time.time()),
        "source": _classify_source(record.editable_model),
        "editability_level": assessment.level,
        "export_mode": assessment.export_mode,
        "printer_profile": profile.model_dump(),
        "parameter_values": _safe_parameter_values(record.editable_model),
        "manufacturability_report": report,
        "mesh_hash": mesh_hash,
        "validation": validation,
        "software_version": SOFTWARE_VERSION,
    }

    bundle_path = workspace_dir / "bundle.zip"
    manifest_path = workspace_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    with ZipFile(bundle_path, "w", compression=ZIP_DEFLATED) as archive:
        for path in (glb_path, stl_path, gcode_path, manifest_path):
            if path and path.exists():
                archive.write(path, arcname=path.name)

    bundle_url = _workspace_artifact_url(workspace_id, bundle_path)
    glb_url = _workspace_artifact_url(workspace_id, glb_path) if glb_path else ""
    stl_url = _workspace_artifact_url(workspace_id, stl_path) if stl_path else None
    gcode_url = _workspace_artifact_url(workspace_id, gcode_path) if gcode_path else None

    if assessment.export_mode == "rebuilt" and stl_path is not None:
        record_build(
            workspace_id,
            revision_id=record.editable_model.revision_id,
            glb_url=glb_url,
            stl_url=stl_url or "",
            gcode_url=gcode_url,
            bundle_url=bundle_url,
            validation=validation,
        )

    return BundleResult(
        workspace_id=workspace_id,
        revision_id=record.editable_model.revision_id,
        bundle_path=bundle_path,
        bundle_url=bundle_url,
        glb_url=glb_url,
        stl_url=stl_url,
        gcode_url=gcode_url,
        manifest=manifest,
    )


def export_dry_run(workspace_id: str) -> dict[str, Any]:
    """Inspect what an export would produce, without actually writing files."""
    record = get_workspace(workspace_id)
    assessment = assess(record.editable_model)
    profile = get_profile()
    return {
        "workspace_id": workspace_id,
        "revision_id": record.editable_model.revision_id,
        "editability": assessment.model_dump(),
        "default_printer_profile": profile.model_dump(),
    }


__all__ = [
    "BundleResult",
    "SOFTWARE_VERSION",
    "export_bundle",
    "export_dry_run",
]
