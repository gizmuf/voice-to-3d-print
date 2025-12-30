from __future__ import annotations

import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
from meshlib import mrmeshpy as mm

from config import settings


@dataclass
class ProcessResult:
    job_id: str
    glb_path: Path
    stl_path: Path
    gcode_path: Path | None


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


def _slice_mesh(stl_path: Path, gcode_path: Path) -> bool:
    slicer_path = Path(settings.prusaslicer_path)
    if not slicer_path.exists():
        return False

    cmd = [
        str(slicer_path),
        "--export-gcode",
    ]
    config_path = Path(settings.prusaslicer_config)
    if config_path.is_file():
        cmd.extend(["--load", str(config_path)])
    cmd.extend(
        [
            "--support-material",
            "--output",
            str(gcode_path),
            str(stl_path),
        ]
    )
    completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
    if completed.stderr:
        # PrusaSlicer writes some warnings to stderr; keep for debugging if needed.
        pass
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


def process_model(glb_url: str) -> ProcessResult:
    job_id = uuid.uuid4().hex
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
    gcode_generated = _slice_mesh(stl_path, gcode_path)

    return ProcessResult(
        job_id=job_id,
        glb_path=glb_path,
        stl_path=stl_path,
        gcode_path=gcode_path if gcode_generated else None,
    )
