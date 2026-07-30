"""Multi-process export presets for a Design.

The user picks a *goal* (3D print / CNC / documentation), the engine picks
the right files. Hides the file-format zoo behind their actual question:
"what am I going to do with this?"

Presets:
- ``fdm`` — STL + G-code + manifest.json (3D printing pipeline)
- ``cnc`` — STEP + DXF + setup_notes.json + manifest.json (CAM hand-off)
- ``docs`` — PNG renders + manifest.json (documentation / sharing)
- ``all`` — everything above
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import HTTPException

from config import settings
from services.codegen.engine import build_design
from services.codegen.estimate import parse_gcode_estimate
from services.codegen.models import BuildArtifact, Design
from services.codegen.store import save_build
from services.codegen import cloud_store


SOFTWARE_VERSION = "pulsai-3d/0.1.0"
ExportPreset = Literal["fdm", "cnc", "docs", "all"]


_PRESET_TARGETS: dict[str, list[str]] = {
    "fdm": ["stl", "glb"],
    "cnc": ["step", "dxf", "stl", "glb"],
    "docs": ["stl", "glb"],
    "all": ["stl", "step", "dxf", "glb"],
}


def export_preset_bundle(
    design: Design,
    preset: ExportPreset,
    *,
    expected_revision_id: str | None = None,
    printer_profile_id: str | None = None,
) -> dict:
    """Produce a ZIP bundle for the requested preset.

    Returns ``{"bundle_url", "manifest", "artifacts"}``. The bundle is
    persisted under the design's workdir and served via /artifacts.
    """
    if expected_revision_id and expected_revision_id != design.revision_id:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Design revision is stale. Re-fetch and try again.",
                "current_revision_id": design.revision_id,
                "expected_revision_id": expected_revision_id,
            },
        )

    targets = _PRESET_TARGETS.get(preset, _PRESET_TARGETS["all"])
    process = "cnc" if preset == "cnc" else "fdm"

    build = build_design(
        design,
        targets=targets,
        printer_profile_id=printer_profile_id,
        process=process,
    )

    bundle_dir = settings.output_dir / "designs" / design.id / "exports" / preset
    bundle_dir.mkdir(parents=True, exist_ok=True)

    files_to_zip: list[Path] = []

    # FDM: also slice G-code
    gcode_path: Path | None = None
    hard_print_block = bool(
        build.manufacturability
        and build.manufacturability.status == "unprintable"
    )
    if preset in ("fdm", "all") and "stl" in build.artifacts and not hard_print_block:
        from slicer_service import _slice_mesh

        stl_path = Path(build.artifacts["stl"].path)
        gcode_path = bundle_dir / "model.gcode"
        if _slice_mesh(stl_path, gcode_path, profile_id=printer_profile_id):
            estimate = parse_gcode_estimate(gcode_path)
            if estimate is not None:
                build.print_estimate = estimate
            build.artifacts["gcode"] = BuildArtifact(
                kind="gcode",
                url=f"/artifacts/designs/{design.id}/exports/{preset}/model.gcode",
                path=str(gcode_path),
                bytes=gcode_path.stat().st_size,
            )
        else:
            gcode_path = None  # slicer not available

    # CNC: also write a setup_notes.json
    setup_notes_path: Path | None = None
    if preset in ("cnc", "all"):
        setup_notes_path = bundle_dir / "setup_notes.json"
        setup_notes_path.write_text(
            json.dumps(_make_cnc_setup_notes(design, build), indent=2)
        )

    # Stage artifacts in the bundle directory before zipping
    for kind, art in build.artifacts.items():
        src = Path(art.path)
        if not src.exists():
            continue
        dst = bundle_dir / src.name
        if src.resolve() != dst.resolve():
            shutil.copy2(src, dst)
        if kind == "gcode" and gcode_path is None:
            continue
        files_to_zip.append(dst)
    if setup_notes_path is not None:
        files_to_zip.append(setup_notes_path)

    # Persist first so the manifest contains durable Cloud Storage URLs.
    save_build(design.id, build)

    manifest = {
        "preset": preset,
        "design_id": design.id,
        "design_name": design.name,
        "revision_id": build.revision_id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "software_version": SOFTWARE_VERSION,
        "process": process,
        "mesh_hash": build.mesh_hash,
        "bounding_box_mm": list(build.bounding_box_mm) if build.bounding_box_mm else None,
        "manufacturability": (
            build.manufacturability.model_dump() if build.manufacturability else None
        ),
        "print_estimate": (
            build.print_estimate.model_dump() if build.print_estimate else None
        ),
        "artifacts": {k: a.model_dump() for k, a in build.artifacts.items()},
    }
    manifest_path = bundle_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
    files_to_zip.append(manifest_path)

    bundle_path = bundle_dir / f"{design.id}-{preset}.zip"
    with ZipFile(bundle_path, "w", compression=ZIP_DEFLATED) as zf:
        for fp in files_to_zip:
            zf.write(fp, arcname=fp.name)

    bundle_url = cloud_store.upload_export_file(design.id, preset, bundle_path)
    return {
        "preset": preset,
        "design_id": design.id,
        "revision_id": build.revision_id,
        "bundle_url": bundle_url or f"/artifacts/designs/{design.id}/exports/{preset}/{bundle_path.name}",
        "manifest": manifest,
        "artifacts": {k: a.model_dump() for k, a in build.artifacts.items()},
    }


def _make_cnc_setup_notes(design: Design, build) -> dict:
    """Notes a CNC operator would want at the start of a job.

    Phase 1 version: dimensions, hole positions if we have them, stock
    recommendation. Future: tool list, recommended feeds/speeds, machine
    fixturing diagrams.
    """
    bbox = list(build.bounding_box_mm) if build.bounding_box_mm else None
    notes: dict = {
        "design_name": design.name,
        "revision_id": build.revision_id,
        "units": "mm",
        "bounding_box_mm": bbox,
        "recommended_stock_mm": (
            [round(v + 6, 1) for v in bbox] if bbox else None
        ),
        "orientation": (
            "Z up. Largest face on the build plate (typical for 3-axis)."
        ),
        "supported_features": [
            "Through holes drilled along Z",
            "External profile contour",
            "Pockets reachable from top",
        ],
        "limitations": [
            "Undercuts (faces with negative-Z normals) are not millable from "
            "this orientation. Re-fixture or split the part.",
            "Internal corners cannot be sharper than the smallest tool radius "
            "you plan to use. Add fillets if your CAM tool warns.",
        ],
        "parameters_at_export": {p.name: p.value for p in design.parameters},
        "next_step": (
            "Open model.step (or model.dxf for 2D ops) in your CAM tool of "
            "choice (Fusion 360, MeshCAM, kiri:moto, F-Engrave, etc.) to "
            "generate toolpaths."
        ),
    }
    return notes


__all__ = ["export_preset_bundle", "ExportPreset", "SOFTWARE_VERSION"]
