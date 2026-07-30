from __future__ import annotations

import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
from meshlib import mrmeshpy as mm
import trimesh

from config import settings


@dataclass
class ProcessResult:
    job_id: str
    glb_path: Path
    stl_path: Path
    gcode_path: Path | None
    validation: dict


def _ensure_output_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _download_file(url: str, dest_path: Path) -> None:
    with httpx.stream("GET", url, timeout=60) as response:
        response.raise_for_status()
        with dest_path.open("wb") as handle:
            for chunk in response.iter_bytes():
                handle.write(chunk)


def _find_object_mesh(root: mm.Object) -> mm.ObjectMesh | None:
    if isinstance(root, mm.ObjectMesh):
        return root
    try:
        children = root.children()
    except Exception:
        return None
    for child in children:
        mesh_obj = _find_object_mesh(child)
        if mesh_obj is not None:
            return mesh_obj
    return None


def _repair_mesh(glb_path: Path, stl_path: Path) -> None:
    try:
        mesh = mm.loadMesh(str(glb_path))
    except Exception:
        loaded = mm.loadSceneFromAnySupportedFormat(str(glb_path))
        mesh_obj = _find_object_mesh(loaded.obj)
        if mesh_obj is None:
            raise RuntimeError("No mesh found in GLB scene") from None
        mesh = mesh_obj.mesh()

    mm.uniteCloseVertices(mesh, closeDist=settings.mesh_merge_tolerance, uniteOnlyBd=False)
    holes = mesh.topology.findHoleRepresentiveEdges()
    if holes and len(holes) > 0:
        mm.fillHoles(mesh, holes)

    mm.saveMesh(mesh, str(stl_path))


def validate_mesh_file(stl_path: Path) -> dict:
    try:
        mesh = trimesh.load_mesh(stl_path, force="mesh")
    except Exception as exc:
        return {
            "validation_status": "failed",
            "warnings": [f"Could not load STL for validation: {exc}"],
            "dimensions_mm": [],
            "estimated_print_risk": "high",
            "preview_vs_final_delta": None,
            "stl_ready": False,
            "gcode_status": "unknown",
        }

    warnings: list[str] = []
    extents = [round(float(value), 2) for value in mesh.bounding_box.extents.tolist()]
    volume = float(abs(mesh.volume))
    watertight = bool(mesh.is_watertight)
    winding_consistent = bool(mesh.is_winding_consistent)

    if not watertight:
        warnings.append("Mesh is not watertight after repair.")
    if not winding_consistent:
        warnings.append("Mesh normals are inconsistent.")
    if volume <= 0:
        warnings.append("Mesh volume is zero or invalid.")
    if extents and max(extents) < 10:
        warnings.append("Model appears very small; confirm scale in millimeters.")
    if extents and min(extents) < 1.2:
        warnings.append("Thin geometry detected below roughly 1.2 mm.")
    if extents and max(extents) > 350:
        warnings.append("Large geometry detected; verify printer bed fit.")

    if not watertight or volume <= 0:
        status = "failed"
        risk = "high"
    elif warnings:
        status = "needs_attention"
        risk = "medium"
    else:
        status = "ready"
        risk = "low"

    return {
        "validation_status": status,
        "warnings": warnings,
        "dimensions_mm": extents,
        "estimated_print_risk": risk,
        "preview_vs_final_delta": None,
        "stl_ready": stl_path.exists(),
        "gcode_status": "not_requested",
    }


def _slice_mesh(stl_path: Path, gcode_path: Path, profile_id: str | None = None) -> bool:
    from services.printer_profiles import get_profile, profile_config_path

    slicer_path = Path(settings.prusaslicer_path)
    if not slicer_path.exists():
        return False

    profile = get_profile(profile_id)
    cmd = [
        str(slicer_path),
        "--export-gcode",
    ]
    config_path = profile_config_path(profile)
    if config_path is not None:
        cmd.extend(["--load", str(config_path)])
    if profile.supports_material:
        cmd.append("--support-material")
    cmd.extend(
        [
            "--output",
            str(gcode_path),
            str(stl_path),
        ]
    )
    completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
    if completed.stderr:
        # PrusaSlicer writes some warnings to stderr; keep for debugging if needed.
        pass
    if not gcode_path.is_file() or gcode_path.stat().st_size == 0:
        raise RuntimeError("PrusaSlicer completed without producing G-code.")
    return True


def _resolve_local_artifact(glb_url: str) -> Path | None:
    if glb_url.startswith("/artifacts/"):
        rel_path = glb_url.removeprefix("/artifacts/")
        return settings.output_dir / rel_path
    parsed = urlparse(glb_url)
    if parsed.path.startswith("/artifacts/"):
        rel_path = parsed.path.removeprefix("/artifacts/")
        return settings.output_dir / rel_path
    return None


def process_model(glb_url: str, job_id: str | None = None) -> ProcessResult:
    job_id = job_id or uuid.uuid4().hex
    job_dir = settings.output_dir / job_id
    _ensure_output_dir(job_dir)

    glb_path = job_dir / "model.glb"
    stl_path = job_dir / "model.stl"
    gcode_path = job_dir / "output.gcode"

    local_source = _resolve_local_artifact(glb_url)
    if local_source and local_source.exists():
        shutil.copy(local_source, glb_path)
    else:
        _download_file(glb_url, glb_path)
    _repair_mesh(glb_path, stl_path)
    validation = validate_mesh_file(stl_path)
    gcode_generated = _slice_mesh(stl_path, gcode_path)
    validation["gcode_status"] = "generated" if gcode_generated else "not_generated"

    return ProcessResult(
        job_id=job_id,
        glb_path=glb_path,
        stl_path=stl_path,
        gcode_path=gcode_path if gcode_generated else None,
        validation=validation,
    )
