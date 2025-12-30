from __future__ import annotations

import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx
from meshlib import mrmeshpy as mm

from config import settings


@dataclass
class ProcessResult:
    job_id: str
    glb_path: Path
    stl_path: Path
    gcode_path: Path


def _ensure_output_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _download_file(url: str, dest_path: Path) -> None:
    with httpx.stream("GET", url, timeout=60) as response:
        response.raise_for_status()
        with dest_path.open("wb") as handle:
            for chunk in response.iter_bytes():
                handle.write(chunk)


def _repair_mesh(glb_path: Path, stl_path: Path) -> None:
    mesh = mm.loadMesh(str(glb_path))

    mm.uniteCloseVertices(mesh, closeDist=settings.mesh_merge_tolerance, uniteOnlyBd=False)
    holes = mesh.topology.findHoleRepresentiveEdges()
    if holes and len(holes) > 0:
        mm.fillHoles(mesh, holes)

    mm.saveMesh(mesh, str(stl_path))


def _slice_mesh(stl_path: Path, gcode_path: Path) -> None:
    cmd = [
        settings.prusaslicer_path,
        "--export-gcode",
        "--load",
        settings.prusaslicer_config,
        "--support-material",
        "--output",
        str(gcode_path),
        str(stl_path),
    ]
    completed = subprocess.run(cmd, check=True, capture_output=True, text=True)
    if completed.stderr:
        # PrusaSlicer writes some warnings to stderr; keep for debugging if needed.
        pass


def process_model(glb_url: str) -> ProcessResult:
    job_id = uuid.uuid4().hex
    job_dir = settings.output_dir / job_id
    _ensure_output_dir(job_dir)

    glb_path = job_dir / "model.glb"
    stl_path = job_dir / "model.stl"
    gcode_path = job_dir / "output.gcode"

    _download_file(glb_url, glb_path)
    _repair_mesh(glb_path, stl_path)
    _slice_mesh(stl_path, gcode_path)

    return ProcessResult(
        job_id=job_id,
        glb_path=glb_path,
        stl_path=stl_path,
        gcode_path=gcode_path,
    )
